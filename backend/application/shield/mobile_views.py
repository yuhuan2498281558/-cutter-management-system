import json

from django.db import IntegrityError, transaction
from django.db.models.functions import Cast
from django.db.models import Case, IntegerField, Min, Prefetch, Q, Value, When
from django.utils import timezone
from rest_framework import serializers, viewsets
from dvadmin.utils.serializers import CustomModelSerializer
from dvadmin.system.models import Users
from dvadmin.utils.viewset import CustomModelViewSet
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated

from dvadmin.utils.json_response import SuccessResponse, ErrorResponse
from application.shield.cutter_position_scope import sort_cutter_position_items, sort_cutter_position_values
from application.shield.trajectory import get_tool_trajectory
from application.shield.models import (
    MobileToolChangeTask,
    ToolChangeDetail,
    ToolCost,
    ToolInfo,
    ToolInstance,
    NewToolRecord,
    OldToolRecord,
    OldToolPhoto,
    WarehouseOpeningBasicInfo,
    TOOL_TYPES,
    NEW_RING_TYPE_CHOICES,
    NEW_COMPONENT_CONDITION_CHOICES,
    BEARING_FAILURE_REASON_CHOICES,
    HUB_FAILURE_REASON_CHOICES,
    RING_DAMAGE_CHOICES,
    OLD_TOOL_DISPOSITION_CHOICES,
    BLADE_WEAR_DESCRIPTION_CHOICES,
)
from application.shield.wear import wear_display



class AdminMobileTaskSerializer(CustomModelSerializer):
    project_name = serializers.CharField(source="warehouse.project.project_name", read_only=True)
    warehouse_id_name = serializers.CharField(source="warehouse.warehouse_id", read_only=True)
    ring_no = serializers.CharField(source="warehouse.ring_no", read_only=True)
    recorder_name = serializers.CharField(source="recorder.name", read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = MobileToolChangeTask
        fields = "__all__"
        # status 必须经 assign / submit / return_task / complete_task 流转，
        # 否则一个普通 PATCH 就能把任务改成任意状态，绕过全部校验。
        read_only_fields = ["id", "submitted_at", "status"]

    def get_progress(self, obj):
        return MobileTaskSerializer(context=self.context).get_progress(obj)

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        warehouse = attrs.get("warehouse") or (instance.warehouse if instance else None)
        scope_type = attrs.get("scope_type") or (instance.scope_type if instance else "ALL")
        tool_types = attrs.get("tool_types") if "tool_types" in attrs else (instance.tool_types if instance else [])
        position_nos = attrs.get("position_nos") if "position_nos" in attrs else (instance.position_nos if instance else [])
        status = attrs.get("status") or (instance.status if instance else "PENDING")
        if not warehouse:
            raise serializers.ValidationError("请选择开仓记录")
        if scope_type == "TOOL_TYPE" and not tool_types:
            raise serializers.ValidationError("按刀具类型分配时必须选择刀具类型")
        if scope_type == "POSITION_LIST" and not position_nos:
            raise serializers.ValidationError("按刀位分配时必须选择刀位")
        if status not in {"COMPLETED", "CANCELLED"}:
            current_positions = resolve_task_positions(warehouse, scope_type, tool_types, position_nos)
            if not current_positions:
                raise serializers.ValidationError("任务范围内没有刀位记录")
            active_tasks = MobileToolChangeTask.objects.filter(warehouse=warehouse).exclude(status__in=["COMPLETED", "CANCELLED"]).exclude(status="UNASSIGNED", recorder__isnull=True)
            if instance:
                active_tasks = active_tasks.exclude(pk=instance.pk)
            for task in active_tasks:
                other_positions = resolve_task_positions(task.warehouse, task.scope_type, task.tool_types, task.position_nos)
                overlap = current_positions & other_positions
                if overlap:
                    sample = "、".join(sort_cutter_position_values(overlap)[:5])
                    raise serializers.ValidationError(f"任务范围与已有任务重叠：{sample}")
        return attrs


def resolve_task_positions(warehouse, scope_type, tool_types=None, position_nos=None):
    queryset = ToolChangeDetail.objects.filter(warehouse=warehouse)
    if scope_type == "TOOL_TYPE":
        queryset = queryset.filter(tool_parent_type__in=tool_types or [])
    elif scope_type == "POSITION_LIST":
        queryset = queryset.filter(cutter_position_no__in=position_nos or [])
    return set(queryset.exclude(cutter_position_no__isnull=True).exclude(cutter_position_no="").values_list("cutter_position_no", flat=True))


def mobile_recorder_options():
    users = Users.objects.filter(is_active=True).prefetch_related("role").order_by("username")
    recorders = []
    for user in users:
        if user_has_mobile_access(user):
            label = getattr(user, "name", "") or user.username
            recorders.append({
                "value": user.id,
                "label": f"{label}（{user.username}）",
                "username": user.username,
                "name": label,
            })
    return recorders

class AdminMobileTaskViewSet(CustomModelViewSet):
    queryset = MobileToolChangeTask.objects.select_related("warehouse", "warehouse__project", "warehouse__shield_model", "recorder").annotate(ring_int=Cast("warehouse__ring_no", output_field=IntegerField())).order_by("ring_int", "id")
    serializer_class = AdminMobileTaskSerializer
    create_serializer_class = AdminMobileTaskSerializer
    update_serializer_class = AdminMobileTaskSerializer
    filter_fields = ["warehouse", "recorder", "scope_type", "status"]
    search_fields = ["warehouse__warehouse_id", "warehouse__ring_no", "recorder__username", "recorder__name"]

    def perform_create(self, serializer):
        instance = serializer.save()
        bind_task_details(instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        bind_task_details(instance)

    @action(detail=False, methods=["get"])
    def assign_options(self, request):
        warehouse_id = request.query_params.get("warehouse")
        recorders = mobile_recorder_options()

        details = ToolChangeDetail.objects.none()
        if warehouse_id:
            details = ToolChangeDetail.objects.filter(warehouse_id=warehouse_id).exclude(cutter_position_no__isnull=True).exclude(cutter_position_no="")

        tool_type_map = {"DISC": "滚刀", "RIPPER": "撕裂刀", "SCRAPER": "刮刀"}
        tool_types = []
        for value in sorted(set(details.exclude(tool_parent_type__isnull=True).exclude(tool_parent_type="").values_list("tool_parent_type", flat=True))):
            tool_types.append({"value": value, "label": tool_type_map.get(value, value)})

        positions = []
        detail_items = list(details.values("id", "cutter_position_no", "tool_parent_type", "cutter_position__tool_info__tool_type_name"))
        for item in sort_cutter_position_items(detail_items, key=lambda row: row.get("cutter_position_no")):
            code = item.get("cutter_position_no") or ""
            tool_type = item.get("tool_parent_type") or ""
            type_label = tool_type_map.get(tool_type, tool_type)
            type_name = item.get("cutter_position__tool_info__tool_type_name") or type_label
            positions.append({
                "value": code,
                "label": f"{code}（{type_name}）",
                "cutter_position_no": code,
                "tool_parent_type": tool_type,
                "tool_parent_type_display": type_label,
                "tool_type_name": type_name,
            })

        return SuccessResponse(data={"recorders": recorders, "tool_types": tool_types, "positions": positions})

    @action(detail=False, methods=["get"])
    def recorder_options(self, request):
        return SuccessResponse(data=mobile_recorder_options())

    @action(detail=True, methods=["get"])
    def approval_detail(self, request, pk=None):
        task = self.get_object()
        details = sort_cutter_position_items(list(scoped_details(task)), key=lambda detail: detail.cutter_position_no)
        return SuccessResponse(data={
            "task": AdminMobileTaskSerializer(task, context={"request": request}).data,
            "details": MobileToolChangeDetailSerializer(details, many=True, context={"request": request}).data,
        })

    @action(detail=True, methods=["post"])
    def return_task(self, request, pk=None):
        task = self.get_object()
        # 只有已提交的任务才谈得上退回，否则会出现 已完成→退回→改数据→再提交
        # 这种绕过审批改写历史数据的路径。
        if task.status != "SUBMITTED":
            return ErrorResponse(msg="只有已提交的任务可以退回")
        task.status = "RETURNED"
        task.returned_reason = request.data.get("reason") or ""
        task.save(update_fields=["status", "returned_reason", "update_datetime"])
        # 只回退真正提交过的明细。原来无条件 update 会把从未录入的 PENDING 行
        # 也刷成 SAVED，进度立刻虚假显示 163/163，且再次提交时不再补标未检查。
        scoped_details(task).exclude(mobile_status="PENDING").update(mobile_status="SAVED")
        return SuccessResponse(data=AdminMobileTaskSerializer(task, context={"request": request}).data, msg="任务已退回")

    @action(detail=True, methods=["post"])
    def complete_task(self, request, pk=None):
        task = self.get_object()
        # 原实现没有任何前置条件：刚建的 UNASSIGNED 空任务也能直接置为已完成，
        # 提交环节可被整体跳过。
        if task.status != "SUBMITTED":
            return ErrorResponse(msg="只有已提交的任务可以标记完成")
        task.status = "COMPLETED"
        task.save(update_fields=["status", "update_datetime"])
        return SuccessResponse(data=AdminMobileTaskSerializer(task, context={"request": request}).data, msg="任务已完成")


def bind_task_details(task):
    details = scoped_details(task)
    details.update(mobile_task_id=task.id)
    if task.recorder_id and task.status == "UNASSIGNED":
        task.status = "PENDING"
        task.save(update_fields=["status", "update_datetime"])

class MobileToolPhotoSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = OldToolPhoto
        fields = ["id", "image", "image_url", "original_filename", "file_size", "mime_type", "remark", "create_datetime"]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        if request:
            url = request.build_absolute_uri(url)
        # 文件被删除后可能沿用相同文件名，使用照片主键让浏览器重新取图。
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}v={obj.id}"


class MobileToolChangeDetailSerializer(serializers.ModelSerializer):
    old_photos = serializers.SerializerMethodField()
    new_tool_uid = serializers.SerializerMethodField()
    tool_type_name = serializers.SerializerMethodField()
    tool_info_id = serializers.SerializerMethodField()
    tool_cost_id = serializers.SerializerMethodField()
    tool_cost_options = serializers.SerializerMethodField()
    wear_condition_display = serializers.SerializerMethodField()
    new_tool = serializers.SerializerMethodField()
    old_tool_record = serializers.SerializerMethodField()
    trajectory = serializers.SerializerMethodField()

    class Meta:
        model = ToolChangeDetail
        fields = [
            "id",
            "warehouse",
            "cutter_position",
            "cutter_position_no",
            "tool_parent_type",
            "tool_number",
            "tool_info_id",
            "tool_cost_id",
            "tool_cost_options",
            "wear_condition",
            "wear_condition_display",
            "blade_wear_amount",
            "manufacturer",
            "brand",
            "price",
            "is_checked",
            "is_replaced",
            "check_result",
            "mobile_status",
            "remark",
            "checked_at",
            "new_tool_uid",
            "new_tool",
            "tool_type_name",
            "old_tool_record",
            "old_photos",
            "trajectory",
        ]

    def get_old_photos(self, obj):
        old_record = getattr(obj, "old_tool_record", None)
        if not old_record:
            return []
        return MobileToolPhotoSerializer(old_record.photos.all(), many=True, context=self.context).data

    def get_new_tool_uid(self, obj):
        record = getattr(obj, "new_tool_record", None)
        if record and record.tool_instance:
            return record.tool_instance.tool_uid
        return None

    @staticmethod
    def _cost_option(cost):
        price = str(cost.unit_price) if cost.unit_price is not None else None
        manufacturer = cost.manufacturer or ""
        brand = cost.brand or ""
        return {
            "id": cost.id,
            "value": cost.id,
            "label": f"{manufacturer or '-'} / {brand or '-'} / {price or '-'}元",
            "manufacturer": manufacturer,
            "brand": brand,
            "price": price,
            "unit_price": price,
            "cost_type": cost.cost_type,
            "tool_info_id": cost.tool_info_id,
        }

    def _tool_costs(self, obj):
        tool_info = getattr(obj.cutter_position, "tool_info", None)
        if not tool_info:
            return []
        # scoped_details 预取了成本记录；直接使用 all() 可以复用缓存，
        # 没有预取时也只会为当前序列化器补一次查询。
        return [cost for cost in tool_info.cost_records.all() if cost.cost_type == "NEW_TOOL"]

    def get_tool_info_id(self, obj):
        return obj.cutter_position.tool_info_id if obj.cutter_position else None

    def get_tool_cost_options(self, obj):
        return [self._cost_option(cost) for cost in self._tool_costs(obj)]

    def get_tool_cost_id(self, obj):
        if not obj.cutter_position or not obj.cutter_position.tool_info_id:
            return None
        for cost in self._tool_costs(obj):
            if (
                (cost.manufacturer or "") == (obj.manufacturer or "")
                and (cost.brand or "") == (obj.brand or "")
                and cost.unit_price == obj.price
            ):
                return cost.id
        return None

    def get_wear_condition_display(self, obj):
        return wear_display(obj.wear_condition)

    def get_new_tool(self, obj):
        record = getattr(obj, "new_tool_record", None)
        if not record:
            return None
        return {
            "ring_type": record.ring_type,
            "ring_type_display": record.get_ring_type_display() if record.ring_type else "",
            "ring_manufacturer": record.ring_manufacturer or "",
            "shaft_condition": record.shaft_condition,
            "shaft_condition_display": record.get_shaft_condition_display() if record.shaft_condition else "",
            "shaft_manufacturer": record.shaft_manufacturer or "",
            "hub_condition": record.hub_condition,
            "hub_condition_display": record.get_hub_condition_display() if record.hub_condition else "",
            "hub_manufacturer": record.hub_manufacturer or "",
            "scraper_manufacturer": record.scraper_manufacturer or "",
            "remark": record.remark or "",
        }

    def get_old_tool_record(self, obj):
        record = getattr(obj, "old_tool_record", None)
        if not record:
            return None
        return {
            "id": record.id,
            "ring_wear_amount": record.ring_wear_amount,
            "bias_wear_amount": record.bias_wear_amount,
            "tool_track": record.tool_track or "",
            "ring_damage": record.ring_damage or [],
            "ring_tooth_loss_count": record.ring_tooth_loss_count,
            "ring_other_condition": record.ring_other_condition or "",
            "bearing_failed": record.bearing_failed,
            "bearing_failure_reasons": record.bearing_failure_reasons or [],
            "bearing_other_condition": record.bearing_other_condition or "",
            "hub_damaged": record.hub_damaged,
            "hub_failure_reasons": record.hub_failure_reasons or [],
            "hub_other_condition": record.hub_other_condition or "",
            "disposition": record.disposition,
            "disposition_display": record.get_disposition_display() if record.disposition else "",
            "scraper_wear_amount": record.scraper_wear_amount,
            "scraper_chipped": record.scraper_chipped,
            "scraper_broken": record.scraper_broken,
            "scraper_detached": record.scraper_detached,
            "repair_result": record.repair_result or "",
            "inspection_status": record.inspection_status,
        }

    def get_tool_type_name(self, obj):
        if obj.cutter_position and obj.cutter_position.tool_info:
            return obj.cutter_position.tool_info.tool_type_name
        return ""

    def get_trajectory(self, obj):
        return get_tool_trajectory(obj.cutter_position_no, obj.tool_parent_type)


class MobileTaskSerializer(serializers.ModelSerializer):
    project_id = serializers.CharField(source="warehouse.project.project_id", read_only=True)
    project_name = serializers.CharField(source="warehouse.project.project_name", read_only=True)
    ring_no = serializers.CharField(source="warehouse.ring_no", read_only=True)
    warehouse_id_name = serializers.CharField(source="warehouse.warehouse_id", read_only=True)
    shield_machine = serializers.CharField(source="warehouse.shield_model.shield_model", read_only=True)
    progress = serializers.SerializerMethodField()
    recorder_name = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    opening_info = serializers.SerializerMethodField()

    class Meta:
        model = MobileToolChangeTask
        fields = [
            "id",
            "warehouse",
            "warehouse_id_name",
            "project_id",
            "project_name",
            "ring_no",
            "shield_machine",
            "scope_type",
            "tool_types",
            "position_nos",
            "status",
            "submitted_at",
            "returned_reason",
            "recorder_name",
            "is_locked",
            "opening_info",
            "progress",
            "create_datetime",
        ]

    def get_progress(self, obj):
        details = scoped_details(obj)
        total = details.count()
        saved = details.filter(is_checked=True).count()
        replaced = details.filter(is_replaced=True).count()
        missing_photo = 0
        for detail in details.filter(is_replaced=True):
            old_record = getattr(detail, "old_tool_record", None)
            if not old_record or not old_record.photos.exists():
                missing_photo += 1
        return {"total": total, "saved": saved, "replaced": replaced, "missing_photo": missing_photo}

    def get_recorder_name(self, obj):
        if not obj.recorder:
            return ""
        return getattr(obj.recorder, "name", "") or getattr(obj.recorder, "username", "")

    def get_is_locked(self, obj):
        request = self.context.get("request")
        return bool(request and obj.recorder_id and obj.recorder_id == getattr(request.user, "id", None))

    def get_opening_info(self, obj):
        warehouse = obj.warehouse
        return {
            "blade_track": warehouse.blade_track or "",
            "tool_change_date": warehouse.tool_change_date,
            "tool_change_duration": warehouse.tool_change_duration,
            "tool_change_ring_no": warehouse.ring_no,
            "last_tool_change_ring_no": warehouse.last_ring_no,
            "usage_distance": warehouse.usage_distance,
        }


def scoped_details(task):
    queryset = ToolChangeDetail.objects.filter(warehouse=task.warehouse).select_related(
        "warehouse",
        "cutter_position",
        "cutter_position__tool_info",
    ).prefetch_related(
        "new_tool_record",
        "old_tool_record__photos",
        Prefetch(
            "cutter_position__tool_info__cost_records",
            queryset=ToolCost.objects.filter(cost_type="NEW_TOOL").order_by(
                "manufacturer", "brand", "unit_price", "-create_datetime"
            ),
        ),
    )
    if task.scope_type == "TOOL_TYPE" and task.tool_types:
        queryset = queryset.filter(tool_parent_type__in=task.tool_types)
    elif task.scope_type == "POSITION_LIST" and task.position_nos:
        queryset = queryset.filter(cutter_position_no__in=task.position_nos)
    return queryset.order_by("cutter_position_no", "id")


def user_can_open_task(user, task):
    if getattr(user, "is_superuser", False):
        return True
    return task.recorder_id is None or task.recorder_id == user.id


def user_has_mobile_access(user):
    if getattr(user, "is_superuser", False):
        return True
    if not hasattr(user, "role"):
        return False
    for role in user.role.all():
        values = [str(getattr(role, attr, "") or "").lower() for attr in ("name", "key")]
        if any(value in {"mobile_recorder", "recorder", "移动端录入员", "录入员"} for value in values):
            return True
    return False



class MobileRecorderPermission(BasePermission):
    message = "当前账号没有移动端录入权限"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and user_has_mobile_access(request.user))


def mobile_field_options():
    as_options = lambda choices: [
        {"value": value, "label": label} for value, label in choices
    ]
    return {
        "ring_types": as_options(NEW_RING_TYPE_CHOICES),
        "component_conditions": as_options(NEW_COMPONENT_CONDITION_CHOICES),
        "bearing_failure_reasons": as_options(BEARING_FAILURE_REASON_CHOICES),
        "hub_failure_reasons": as_options(HUB_FAILURE_REASON_CHOICES),
        "ring_damage": as_options(RING_DAMAGE_CHOICES),
        "old_tool_dispositions": as_options(OLD_TOOL_DISPOSITION_CHOICES),
        "wear_descriptions": as_options(BLADE_WEAR_DESCRIPTION_CHOICES),
    }


def next_tool_numbers(detail):
    warehouse = detail.warehouse
    project_id = warehouse.project.project_id if warehouse.project else "PROJECT"
    shield_id = warehouse.shield_model.shield_model_id if warehouse.shield_model else "SHIELD"
    ring_no = warehouse.ring_no
    position_no = detail.cutter_position_no
    seq = NewToolRecord.objects.filter(
        tool_change_detail__warehouse__project=warehouse.project,
        tool_change_detail__warehouse__shield_model=warehouse.shield_model,
        tool_change_detail__cutter_position_no=position_no,
    ).count() + 1
    while True:
        display = f"{ring_no}-{position_no}-{seq:02d}"
        uid = f"{project_id}-{shield_id}-{display}"
        if not ToolInstance.objects.filter(tool_uid=uid).exists():
            return uid, display
        seq += 1


def _discard_replacement_artifacts(detail):
    """撤销一次"已更换"录入：删除新刀/旧刀记录并作废刚建的刀具实例。

    只回收本明细自己生成、且未被他处确认引用的实例，已确认配对的不动。
    """
    new_record = getattr(detail, "new_tool_record", None)
    instance = getattr(new_record, "tool_instance", None) if new_record else None
    old_record = getattr(detail, "old_tool_record", None)
    if old_record is not None:
        old_record.photos.all().delete()
        old_record.delete()
    if new_record is not None:
        new_record.delete()
    if instance is not None:
        still_referenced = (
            NewToolRecord.objects.filter(tool_instance=instance).exists()
            or OldToolRecord.objects.filter(confirmed_tool_instance=instance).exists()
        )
        if not still_referenced:
            instance.delete()
    detail.tool_number = ""


def refresh_warehouse_check_counts(warehouse_id):
    details = ToolChangeDetail.objects.filter(warehouse_id=warehouse_id)
    WarehouseOpeningBasicInfo.objects.filter(pk=warehouse_id).update(
        checked_tool_count=details.filter(is_checked=True).count(),
        replaced_tool_count=details.filter(is_replaced=True).count(),
    )


def suggested_old_tool(detail):
    try:
        current_ring = int(detail.warehouse.ring_no)
    except (TypeError, ValueError):
        return None
    candidates = (
        NewToolRecord.objects
        .filter(
            tool_change_detail__warehouse__project=detail.warehouse.project,
            tool_change_detail__warehouse__shield_model=detail.warehouse.shield_model,
            tool_change_detail__cutter_position_no=detail.cutter_position_no,
        )
        .exclude(tool_change_detail=detail)
        .select_related("tool_instance", "tool_change_detail__warehouse")
        .filter(tool_change_detail__warehouse__ring_no__regex=r"^\d+$")
        .annotate(ring_int=Cast("tool_change_detail__warehouse__ring_no", output_field=IntegerField()))
        # 与 next_replacement_detail 对称：同环第二次开仓时不能漏掉同环较早那次，
        # 否则会跨过刚装的刀去配更早的刀，产生确定性错配。
        .filter(
            Q(ring_int__lt=current_ring)
            | (
                Q(ring_int=current_ring)
                & Q(tool_change_detail__warehouse__open_time__lt=detail.warehouse.open_time)
            )
        )
        .order_by("-ring_int", "-tool_change_detail__warehouse__open_time")
    )
    used_ids = OldToolRecord.objects.exclude(confirmed_tool_instance=None).values_list("confirmed_tool_instance_id", flat=True)
    # 原写法用 candidates.exists()（过滤前）判空，却对 .exclude(...).first()（过滤后）
    # 取属性：候选存在但都已被占用时 first() 是 None，直接 AttributeError → 500，
    # 且记录员此后再也打不开这个刀位。
    record = candidates.exclude(tool_instance_id__in=used_ids).first()
    return record.tool_instance if record else None


def validate_photo(file_obj):
    mime_type = getattr(file_obj, "content_type", "") or ""
    name = getattr(file_obj, "name", "") or ""
    lower = name.lower()
    if mime_type not in {"image/jpeg", "image/jpg", "image/png"} and not (lower.endswith(".jpg") or lower.endswith(".jpeg") or lower.endswith(".png")):
        return "旧刀照片仅支持 JPG/JPEG/PNG 原图"
    if getattr(file_obj, "size", 0) > 30 * 1024 * 1024:
        return "单张旧刀照片不能超过 30MB"
    return None


def parse_old_photo_ids(value):
    """解析手机端提交的保留照片 ID；返回 None 表示字段未提交或格式无效。"""
    if value is None:
        return None
    if isinstance(value, list):
        raw_ids = value
    else:
        try:
            raw_ids = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(raw_ids, list):
        return None
    photo_ids = set()
    for raw_id in raw_ids:
        try:
            photo_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if photo_id > 0:
            photo_ids.add(photo_id)
    return photo_ids


def delete_old_tool_photos(queryset):
    """删除照片记录及其文件，只接收当前旧刀记录下的照片查询集。"""
    for photo in queryset:
        if photo.image:
            photo.image.delete(save=False)
        photo.delete()


class MobileMeViewSet(viewsets.ViewSet):
    permission_classes = [MobileRecorderPermission]

    def list(self, request):
        return SuccessResponse(data={
            "id": request.user.id,
            "username": request.user.username,
            "name": getattr(request.user, "name", ""),
            "has_mobile_access": user_has_mobile_access(request.user),
        })


class MobileTaskViewSet(viewsets.ViewSet):
    permission_classes = [MobileRecorderPermission]

    def list(self, request):
        queryset = MobileToolChangeTask.objects.select_related("warehouse", "warehouse__project", "warehouse__shield_model").annotate(ring_int=Cast("warehouse__ring_no", output_field=IntegerField()))
        if not getattr(request.user, "is_superuser", False):
            # 未分配的开仓对所有有移动端权限的账号可见；首次打开详情时再原子加锁。
            queryset = queryset.filter(Q(recorder=request.user) | Q(recorder__isnull=True))
        status_param = request.query_params.get("status")
        if status_param == "active":
            status_rank = Case(
                When(status="RETURNED", then=Value(0)),
                When(status="IN_PROGRESS", then=Value(1)),
                When(status="PENDING", then=Value(2)),
                When(status="UNASSIGNED", then=Value(3)),
                default=Value(9),
                output_field=IntegerField(),
            )
            queryset = queryset.exclude(status__in=["COMPLETED", "CANCELLED"]).annotate(status_rank=status_rank).order_by(
                "status_rank", "ring_int", "id"
            )
        else:
            queryset = queryset.order_by("ring_int", "id")
        serializer = MobileTaskSerializer(queryset, many=True, context={"request": request})
        return SuccessResponse(data=serializer.data)

    def retrieve(self, request, pk=None):
        task = self._get_task(request, pk, claim=True)
        if not task:
            return ErrorResponse(msg="任务不存在或无权访问")
        details = sort_cutter_position_items(list(scoped_details(task)), key=lambda detail: detail.cutter_position_no)
        return SuccessResponse(data={
            "task": MobileTaskSerializer(task, context={"request": request}).data,
            "details": MobileToolChangeDetailSerializer(details, many=True, context={"request": request}).data,
            "field_options": mobile_field_options(),
        })

    def _get_task(self, request, pk, claim=False):
        queryset = MobileToolChangeTask.objects.select_related(
            "warehouse", "warehouse__project", "warehouse__shield_model", "recorder"
        )
        if claim:
            with transaction.atomic():
                task = queryset.select_for_update(of=("self",)).filter(pk=pk).first()
                if not task or not user_can_open_task(request.user, task):
                    return None
                if task.recorder_id is None:
                    task.recorder = request.user
                    if task.status == "UNASSIGNED":
                        task.status = "PENDING"
                    task.save(update_fields=["recorder", "status", "update_datetime"])
                return task
        task = queryset.filter(pk=pk).first()
        if not task or not user_can_open_task(request.user, task):
            return None
        return task
    @transaction.atomic
    @action(detail=True, methods=["post"])
    def save_detail(self, request, pk=None):
        task = self._get_task(request, pk, claim=True)
        if not task:
            return ErrorResponse(msg="任务不存在或无权访问")
        if task.status in {"COMPLETED", "CANCELLED"}:
            return ErrorResponse(msg="当前任务已完成或取消，不可编辑")
        detail_id = request.data.get("detail_id")
        detail = scoped_details(task).filter(id=detail_id).first()
        if not detail:
            return ErrorResponse(msg="刀位记录不在当前任务范围内")

        is_replaced = str(request.data.get("is_replaced", "false")).lower() in {"true", "1", "yes"}
        detail.mobile_task = task
        detail.is_checked = True
        detail.is_replaced = is_replaced
        detail.checked_at = timezone.now()
        detail.remark = request.data.get("remark", detail.remark)
        if "wear_condition" in request.data:
            detail.wear_condition = str(request.data.get("wear_condition") or "").strip()[:50]
        if "blade_wear_amount" in request.data:
            try:
                detail.blade_wear_amount = (
                    float(request.data.get("blade_wear_amount"))
                    if request.data.get("blade_wear_amount") not in (None, "") else None
                )
            except (TypeError, ValueError):
                return ErrorResponse(msg="刀刃磨损量必须是数字")

        if is_replaced:
            photos = request.FILES.getlist("old_photos") or request.FILES.getlist("photos")
            old_record = getattr(detail, "old_tool_record", None)
            old_photo_ids_supplied = "old_photo_ids" in request.data
            retained_photo_ids = None
            if old_photo_ids_supplied:
                retained_photo_ids = parse_old_photo_ids(request.data.get("old_photo_ids"))
                if retained_photo_ids is None:
                    return ErrorResponse(msg="旧刀照片保留列表格式不正确，请刷新后重试")
            existing_photo_ids = set(old_record.photos.values_list("id", flat=True)) if old_record else set()
            if retained_photo_ids is None:
                retained_photo_count = len(existing_photo_ids)
            else:
                # 只允许保留当前刀位旧刀记录下的照片，避免跨刀位引用照片。
                retained_photo_ids &= existing_photo_ids
                retained_photo_count = len(retained_photo_ids)
            if not photos and retained_photo_count == 0:
                return ErrorResponse(msg="换刀记录必须上传至少 1 张旧刀照片")
            if len(photos) + retained_photo_count > 5:
                return ErrorResponse(msg="旧刀照片最多上传 5 张")
            for photo in photos:
                error = validate_photo(photo)
                if error:
                    return ErrorResponse(msg=error)

            # 刀位的 ToolInfo 是主数据绑定，移动端只能在这个固定类型下选择成本记录。
            tool_info_id = (detail.cutter_position.tool_info_id if detail.cutter_position else None) or request.data.get("tool_info")
            tool_info = ToolInfo.objects.filter(id=tool_info_id).first() if tool_info_id else None
            if not tool_info:
                return ErrorResponse(msg="请选择新刀类型")

            new_record = getattr(detail, "new_tool_record", None)
            cost_options = ToolCost.objects.filter(tool_info=tool_info, cost_type="NEW_TOOL")
            cost_id = request.data.get("tool_cost_id")
            selected_cost = None
            if cost_id not in (None, ""):
                selected_cost = cost_options.filter(pk=cost_id).first()
                if not selected_cost:
                    return ErrorResponse(msg="所选成本库记录与当前刀位类型不匹配")
            elif cost_options.exists() and not new_record:
                return ErrorResponse(msg="请选择当前刀具类型对应的成本库记录")

            selected_manufacturer = selected_cost.manufacturer if selected_cost else None
            new_tool_fields = {
                "ring_type": request.data.get("ring_type") or None,
                "ring_manufacturer": (
                    selected_manufacturer
                    if selected_cost and tool_info.tool_parent_type == "DISC"
                    else request.data.get("ring_manufacturer") or None
                ),
                "shaft_condition": request.data.get("shaft_condition") or None,
                "shaft_manufacturer": (
                    selected_manufacturer
                    if selected_cost and tool_info.tool_parent_type == "DISC"
                    else request.data.get("shaft_manufacturer") or None
                ),
                "hub_condition": request.data.get("hub_condition") or None,
                "hub_manufacturer": (
                    selected_manufacturer
                    if selected_cost and tool_info.tool_parent_type == "DISC"
                    else request.data.get("hub_manufacturer") or None
                ),
                "scraper_manufacturer": (
                    selected_manufacturer
                    if selected_cost and tool_info.tool_parent_type == "SCRAPER"
                    else request.data.get("scraper_manufacturer") or None
                ),
                "remark": request.data.get("new_tool_remark") or None,
            }

            if selected_cost:
                detail.manufacturer = selected_cost.manufacturer or ""
                detail.brand = selected_cost.brand or ""
                detail.price = selected_cost.unit_price
            elif "manufacturer" in request.data:
                detail.manufacturer = request.data.get("manufacturer") or None
            if not selected_cost and "brand" in request.data:
                detail.brand = request.data.get("brand") or None
            if not selected_cost and "price" in request.data:
                try:
                    detail.price = float(request.data.get("price")) if request.data.get("price") not in (None, "") else None
                except (TypeError, ValueError):
                    return ErrorResponse(msg="刀具价格必须是数字")
            if not new_record:
                # 编号取自 COUNT(*)+1，两名记录员同刀位同时保存会算出同一个号，
                # 第二个人 create 时撞 tool_uid 唯一约束直接 500（照片却已入库）。
                # 这里对唯一冲突做有限重试，重新取号即可。
                for _attempt in range(5):
                    tool_uid, display_no = next_tool_numbers(detail)
                    try:
                        with transaction.atomic():
                            instance = ToolInstance.objects.create(
                                tool_uid=tool_uid,
                                display_tool_no=display_no,
                                tool_info=tool_info,
                                tool_parent_type=tool_info.tool_parent_type,
                                tool_type_name=tool_info.tool_type_name,
                                status="INSTALLED",
                                creator=request.user,
                                dept_belong_id=getattr(request.user, "dept_id", None),
                            )
                        break
                    except IntegrityError:
                        continue
                else:
                    return ErrorResponse(msg="刀具编号分配冲突，请重试")
                new_record = NewToolRecord.objects.create(
                    tool_change_detail=detail,
                    tool_instance=instance,
                    installed_by=request.user,
                    installed_at=timezone.now(),
                    **new_tool_fields,
                    creator=request.user,
                    dept_belong_id=getattr(request.user, "dept_id", None),
                )
                detail.tool_number = instance.display_tool_no
                detail.tool_parent_type = tool_info.tool_parent_type
            else:
                changed_fields = []
                for field, value in new_tool_fields.items():
                    if field in request.data or (field == "remark" and "new_tool_remark" in request.data):
                        if getattr(new_record, field) != value:
                            setattr(new_record, field, value)
                            changed_fields.append(field)
                if changed_fields:
                    new_record.save(update_fields=changed_fields + ["update_datetime"])
            old_record, _ = OldToolRecord.objects.get_or_create(
                tool_change_detail=detail,
                defaults={
                    "suggested_tool_instance": suggested_old_tool(detail),
                    "creator": request.user,
                    "dept_belong_id": getattr(request.user, "dept_id", None),
                },
            )
            if retained_photo_ids is not None:
                delete_old_tool_photos(old_record.photos.exclude(id__in=retained_photo_ids))
            for photo in photos:
                OldToolPhoto.objects.create(
                    old_tool_record=old_record,
                    image=photo,
                    original_filename=getattr(photo, "name", ""),
                    file_size=getattr(photo, "size", None),
                    mime_type=getattr(photo, "content_type", ""),
                    creator=request.user,
                    dept_belong_id=getattr(request.user, "dept_id", None),
                )
            detail.check_result = "NORMAL"
        else:
            detail.check_result = request.data.get("check_result") or "NOT_REPLACED"
            detail.manufacturer = None
            detail.brand = None
            detail.price = None
            # 把"已更换"改回"未更换"时必须回收此前生成的新刀实例与配对记录，
            # 否则会留下一把永远拆不掉的幽灵刀：既虚增在役库存，又会在下次
            # 真换刀时被 suggested_old_tool 当成换下的旧刀，造成错误配对。
            _discard_replacement_artifacts(detail)

        detail.mobile_status = "SAVED"
        detail.save()
        refresh_warehouse_check_counts(task.warehouse_id)
        if task.status in {"UNASSIGNED", "PENDING", "RETURNED", "SUBMITTED"}:
            task.status = "IN_PROGRESS"
            update_fields = ["status", "update_datetime"]
            if task.submitted_at is not None:
                task.submitted_at = None
                update_fields.append("submitted_at")
            task.save(update_fields=update_fields)
        # scoped_details 预取了旧刀照片，删除/替换照片后必须重新查询，避免响应继续携带旧缓存。
        detail = scoped_details(task).get(pk=detail.pk)
        return SuccessResponse(data=MobileToolChangeDetailSerializer(detail, context={"request": request}).data, msg="保存成功")

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        task = self._get_task(request, pk, claim=True)
        if not task:
            return ErrorResponse(msg="任务不存在或无权访问")
        if task.status in {"SUBMITTED", "COMPLETED", "CANCELLED"}:
            return ErrorResponse(msg="当前任务不可提交")
        details = list(scoped_details(task))

        # 先全量校验、再统一写入。原实现边写边校验，而且在 @transaction.atomic 里
        # 用 return ErrorResponse（不是抛异常）返回——事务照样提交，于是"提交失败"
        # 却已经改了一半数据，且那些刀位此后被算作已保存，不会再提示记录员补录。
        errors = []
        for detail in details:
            if not detail.is_replaced:
                continue
            if not hasattr(detail, "new_tool_record"):
                errors.append(f"刀位 {detail.cutter_position_no} 缺少新刀记录")
            elif not hasattr(detail, "old_tool_record") or not detail.old_tool_record.photos.exists():
                errors.append(f"刀位 {detail.cutter_position_no} 缺少旧刀照片")
        if errors:
            shown = "；".join(errors[:5])
            return ErrorResponse(msg=shown + (f" 等 {len(errors)} 处" if len(errors) > 5 else ""))

        # 没走到的刀位如实标记为"未检查"，不再伪造成"已检查·未更换"。
        # 原实现给它们盖上 is_checked=True/checked_at=now，数据库从此声称这些刀
        # 被人工检查过且正常，检查覆盖率与磨损统计全部建立在伪造记录上。
        uninspected = [d.cutter_position_no for d in details if d.mobile_status == "PENDING"]
        for detail in details:
            fields = ["mobile_status", "update_datetime"]
            if detail.mobile_status == "PENDING":
                detail.mobile_task = task
                detail.is_checked = False
                detail.check_result = "PENDING"
                fields += ["mobile_task", "is_checked", "check_result"]
            detail.mobile_status = "SUBMITTED"
            detail.save(update_fields=fields)
        task.status = "SUBMITTED"
        task.submitted_at = timezone.now()
        task.save(update_fields=["status", "submitted_at", "update_datetime"])
        msg = "任务已提交"
        if uninspected:
            msg += f"（其中 {len(uninspected)} 个刀位未检查，已如实标记为待检查）"
        return SuccessResponse(
            data=MobileTaskSerializer(task, context={"request": request}).data, msg=msg
        )



def _detail_base(detail):
    warehouse = detail.warehouse if detail else None
    return {
        "detail_id": detail.id if detail else None,
        "warehouse_id": warehouse.warehouse_id if warehouse else "",
        "project_name": warehouse.project.project_name if warehouse and warehouse.project else "",
        "ring_no": warehouse.ring_no if warehouse else "",
        "cutter_position_no": detail.cutter_position_no if detail else "",
        "tool_parent_type": detail.tool_parent_type if detail else "",
        "trajectory": get_tool_trajectory(
            detail.cutter_position_no if detail else "",
            detail.tool_parent_type if detail else None,
        ),
    }


def old_tool_inspection_payload(record, request=None):
    if not record:
        return None
    def photo_url(photo):
        if not photo.image:
            return None
        url = photo.image.url
        if request:
            url = request.build_absolute_uri(url)
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}v={photo.id}"

    return {
        "id": record.id,
        "inspection_status": record.inspection_status,
        "inspection_status_display": record.get_inspection_status_display(),
        "old_tool_number": record.old_tool_number or "",
        "ring_wear_amount": record.ring_wear_amount,
        "bias_wear_amount": record.bias_wear_amount,
        "tool_track": record.tool_track or "",
        "ring_damage": record.ring_damage or [],
        "ring_tooth_loss_count": record.ring_tooth_loss_count,
        "ring_other_condition": record.ring_other_condition or "",
        "bearing_failed": record.bearing_failed,
        "bearing_failure_reasons": record.bearing_failure_reasons or [],
        "bearing_other_condition": record.bearing_other_condition or "",
        "hub_damaged": record.hub_damaged,
        "hub_failure_reasons": record.hub_failure_reasons or [],
        "hub_other_condition": record.hub_other_condition or "",
        "disposition": record.disposition,
        "disposition_display": record.get_disposition_display() if record.disposition else "",
        "scraper_wear_amount": record.scraper_wear_amount,
        "scraper_chipped": record.scraper_chipped,
        "scraper_broken": record.scraper_broken,
        "scraper_detached": record.scraper_detached,
        "repair_result": record.repair_result or "",
        "repair_price": record.repair_price,
        "photo_links": [
            {
                "id": photo.id,
                "name": photo.original_filename or f"照片{index + 1}",
                "url": photo_url(photo),
            }
            for index, photo in enumerate(record.photos.all())
        ],
    }


def new_tool_components_payload(record):
    if not record:
        return None
    return {
        "ring_type": record.ring_type,
        "ring_type_display": record.get_ring_type_display() if record.ring_type else "",
        "ring_manufacturer": record.ring_manufacturer or "",
        "shaft_condition": record.shaft_condition,
        "shaft_condition_display": record.get_shaft_condition_display() if record.shaft_condition else "",
        "shaft_manufacturer": record.shaft_manufacturer or "",
        "hub_condition": record.hub_condition,
        "hub_condition_display": record.get_hub_condition_display() if record.hub_condition else "",
        "hub_manufacturer": record.hub_manufacturer or "",
        "scraper_manufacturer": record.scraper_manufacturer or "",
    }



def tool_cost_info(tool_info):
    if not tool_info:
        return {"brand": "", "manufacturer": "", "price": None}
    cost = tool_info.cost_records.filter(cost_type="NEW_TOOL").order_by("-create_datetime").first()
    if not cost:
        cost = tool_info.cost_records.order_by("-create_datetime").first()
    return {
        "brand": cost.brand if cost else "",
        "manufacturer": cost.manufacturer if cost else "",
        "price": cost.unit_price if cost else None,
    }


def ring_int_value(ring_no):
    try:
        return int(ring_no)
    except (TypeError, ValueError):
        return None


def lifecycle_tool_number(detail):
    if not detail:
        return ""
    if detail.tool_number:
        return detail.tool_number
    if not detail.is_replaced:
        return ""
    ring_no = detail.warehouse.ring_no if detail.warehouse else "0000"
    seq = detail.replacement_count or 1
    return f"R{ring_no}-{detail.cutter_position_no}-{seq}"

def tool_life_info(install_detail, remove_detail=None):
    install_ring_no = install_detail.warehouse.ring_no if install_detail and install_detail.warehouse else ""
    remove_ring_no = remove_detail.warehouse.ring_no if remove_detail and remove_detail.warehouse else ""
    install_ring = ring_int_value(install_ring_no)
    remove_ring = ring_int_value(remove_ring_no)
    usage_rings = remove_ring - install_ring if install_ring is not None and remove_ring is not None else None
    return {
        "install_ring_no": install_ring_no,
        "remove_ring_no": remove_ring_no,
        "usage_rings": usage_rings if usage_rings is None or usage_rings >= 0 else None,
    }


def next_replacement_detail(detail):
    if not detail or not detail.warehouse:
        return None
    current_ring = ring_int_value(detail.warehouse.ring_no)
    if current_ring is None:
        return None
    return (
        ToolChangeDetail.objects.filter(
            warehouse__project=detail.warehouse.project,
            warehouse__shield_model=detail.warehouse.shield_model,
            cutter_position_no=detail.cutter_position_no,
            is_replaced=True,
        )
        .exclude(pk=detail.pk)
        .filter(warehouse__ring_no__regex=r"^\d+$")
        .annotate(ring_int=Cast("warehouse__ring_no", output_field=IntegerField()))
        # 同一环号允许开两次仓（编号加 -2 后缀），此时严格用 ring_int > current_ring
        # 会跳过"同环稍后那次"，把早上装的刀当成一直在役、并让晚上那次去配更早的刀。
        # 改成按 (环号, 开仓时间, id) 的字典序取"下一次"。
        .filter(
            Q(ring_int__gt=current_ring)
            | (Q(ring_int=current_ring) & Q(warehouse__open_time__gt=detail.warehouse.open_time))
        )
        .select_related("warehouse", "warehouse__project", "warehouse__shield_model")
        .order_by("ring_int", "warehouse__open_time", "id")
        .first()
    )
class ToolLifecycleViewSet(viewsets.ViewSet):
    """刀具全生命周期卡片。

    本视图集在 2026-07 做过一次口径与性能修正。

    口径修正：
      1. 支持 project / shield_machine 过滤。此前是全库查询，多项目部署会把不同项目
         的刀具混在同一张列表里。
      2. 旧刀配对优先取 OldToolRecord.confirmed_tool_instance；仅当没有已确认记录时
         才回退到 suggested_tool_instance，并通过 pairing_confirmed=false 显式标记。
         此前用 Q(confirmed)|Q(suggested) 一把捞且按时间取第一条，可能拿到"系统猜测"
         的配对甚至错配到另一条记录上，导致服役环数算错、在役刀被标成已拆下。
      3. 状态筛选统一按【派生状态】进行。此前先用 DB 的 instance.status 过滤，再用被
         覆盖过的派生状态二次过滤，两者语义不同：筛 REMOVED 会把 ToolInstance 分支整个
         置空（导致与不筛时 id 不同、卡片重复），筛 REMOVED_PENDING_INSPECTION 则因为
         派生状态已被改写为 REMOVED 而永远返回空。
      4. timeline 排序键由 str(time) 改为 (是否为空, time)，避免 str(None)=="None"
         被排到日期字符串之后。

    性能修正（列表接口）：
      A. 历史分支改为 GROUP BY tool_number 聚合。开仓时 post_save 会给每个刀位建一条
         明细并把 tool_number 逐次继承下去，因此"tool_number 非空"几乎命中全表
         （刀位数 × 开仓次数）。原实现把这些行全部读进 Python 再靠 seen_numbers 去重，
         等于每次请求全表扫描。现在用 values(...).annotate(Min(ring)) 让数据库完成
         折叠，返回行数从"刀位数 × 开仓次数"降到"不同刀具把数"。
      B. 分页改为先算候选再切片，只序列化当前页。
      C. 当前页所需的安装记录、旧刀配对、成本信息全部改为按页批量查询。原实现每张卡片
         各发 1~3 条查询（new_tool_records.first() / OldToolRecord.filter /
         tool_cost_info），48 条/页即 100+ 次查询，现在固定 5~7 条。
    """

    permission_classes = [IsAuthenticated]

    # ------------------------------------------------------------------
    # 批量预计算
    # ------------------------------------------------------------------
    @staticmethod
    def _replacement_ring_map(project=None, shield_machine=None):
        """{(project_id, shield_id, 刀位编号): [已换刀环号升序]}

        只读 is_replaced=True 的行（真正发生过更换的才是拆卸事件），
        与 next_replacement_detail() 的过滤条件保持一致。
        """
        qs = ToolChangeDetail.objects.filter(is_replaced=True)
        if project:
            qs = qs.filter(warehouse__project_id=project)
        if shield_machine:
            qs = qs.filter(warehouse__shield_model_id=shield_machine)
        buckets = {}
        for row in qs.values(
            "warehouse__project_id", "warehouse__shield_model_id",
            "cutter_position_no", "warehouse__ring_no",
        ):
            ring = ring_int_value(row.get("warehouse__ring_no"))
            position = row.get("cutter_position_no")
            if ring is None or not position:
                continue
            key = (row.get("warehouse__project_id"), row.get("warehouse__shield_model_id"), position)
            buckets.setdefault(key, []).append(ring)
        for rings in buckets.values():
            rings.sort()
        return buckets

    @staticmethod
    def _instance_removal_map():
        """{instance_id: {"detail_id","ring_no","confirmed"}}，已确认的配对优先。

        只取列表/详情真正需要的几个标量字段，避免把整表 OldToolRecord 及其关联对象
        实例化出来。
        """
        confirmed, suggested = {}, {}
        rows = (
            OldToolRecord.objects
            .filter(Q(confirmed_tool_instance__isnull=False) | Q(suggested_tool_instance__isnull=False))
            .order_by("vendor_feedback_at", "create_datetime")
            .values(
                "id", "confirmed_tool_instance_id", "suggested_tool_instance_id",
                "tool_change_detail_id", "tool_change_detail__warehouse__ring_no",
            )
        )
        for row in rows:
            payload = {
                "record_id": row["id"],
                "detail_id": row["tool_change_detail_id"],
                "ring_no": row["tool_change_detail__warehouse__ring_no"],
            }
            cid = row["confirmed_tool_instance_id"]
            sid = row["suggested_tool_instance_id"]
            if cid and cid not in confirmed:
                confirmed[cid] = payload
            if sid and sid not in suggested:
                suggested[sid] = payload
        merged = {}
        for instance_id, payload in confirmed.items():
            merged[instance_id] = {**payload, "confirmed": True}
        for instance_id, payload in suggested.items():
            merged.setdefault(instance_id, {**payload, "confirmed": False})
        return merged

    @staticmethod
    def _install_detail_map(instance_ids):
        """{instance_id: {"detail_id","ring_no"}}，取每个实例最早的一次安装。"""
        out = {}
        if not instance_ids:
            return out
        rows = (
            NewToolRecord.objects
            .filter(tool_instance_id__in=instance_ids)
            .order_by("tool_instance_id", "installed_at", "create_datetime")
            .values(
                "tool_instance_id", "tool_change_detail_id",
                "tool_change_detail__warehouse__ring_no",
                "tool_change_detail__cutter_position_no",
                "tool_change_detail__tool_parent_type",
            )
        )
        for row in rows:
            out.setdefault(row["tool_instance_id"], {
                "detail_id": row["tool_change_detail_id"],
                "ring_no": row["tool_change_detail__warehouse__ring_no"],
                "cutter_position_no": row["tool_change_detail__cutter_position_no"],
                "tool_parent_type": row["tool_change_detail__tool_parent_type"],
            })
        return out

    @staticmethod
    def _tool_cost_map(tool_info_ids):
        """{tool_info_id: {"brand","manufacturer","price"}}，一次查询取每个型号最新成本。

        与 tool_cost_info() 口径一致：优先 NEW_TOOL，没有则回退最新一条。
        """
        result = {}
        ids = [i for i in set(tool_info_ids or []) if i]
        if not ids:
            return result
        rows = (
            ToolCost.objects.filter(tool_info_id__in=ids)
            .order_by("tool_info_id", "-create_datetime")
            .values("tool_info_id", "cost_type", "brand", "manufacturer", "unit_price")
        )
        new_tool, fallback = {}, {}
        for row in rows:
            tid = row["tool_info_id"]
            if row.get("cost_type") == "NEW_TOOL" and tid not in new_tool:
                new_tool[tid] = row
            fallback.setdefault(tid, row)
        for tid in ids:
            row = new_tool.get(tid) or fallback.get(tid)
            result[tid] = {
                "brand": (row or {}).get("brand") or "",
                "manufacturer": (row or {}).get("manufacturer") or "",
                "price": (row or {}).get("unit_price"),
            }
        return result

    def _next_replacement_ring(self, ring_map, project_id, shield_id, position, after_ring):
        if after_ring is None or not position:
            return None
        rings = ring_map.get((project_id, shield_id, position)) or []
        return next((r for r in rings if r > after_ring), None)

    @staticmethod
    def _life_payload(install_ring_no, remove_ring_no):
        """与 tool_life_info() 返回结构一致，但直接吃环号标量，不需要 detail 对象。"""
        install_ring = ring_int_value(install_ring_no)
        remove_ring = ring_int_value(remove_ring_no)
        usage = (
            remove_ring - install_ring
            if install_ring is not None and remove_ring is not None
            else None
        )
        return {
            "install_ring_no": install_ring_no or "",
            "remove_ring_no": remove_ring_no or "",
            "usage_rings": usage if usage is None or usage >= 0 else None,
        }

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------
    def list(self, request):
        keyword = (request.query_params.get("search") or "").strip()
        status = (request.query_params.get("status") or "").strip()
        tool_parent_type = (request.query_params.get("tool_parent_type") or "").strip()
        project = (request.query_params.get("project") or "").strip() or None
        shield_machine = (request.query_params.get("shield_machine") or "").strip() or None
        try:
            page = max(int(request.query_params.get("page") or 1), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            limit = min(max(int(request.query_params.get("limit") or 48), 1), 200)
        except (TypeError, ValueError):
            limit = 48

        ring_map = self._replacement_ring_map(project, shield_machine)
        removal_map = self._instance_removal_map()

        candidates = []
        seen_numbers = set()

        # --- ToolInstance 分支 -------------------------------------------------
        instance_query = ToolInstance.objects.all()
        if keyword:
            instance_query = instance_query.filter(
                Q(tool_uid__icontains=keyword)
                | Q(display_tool_no__icontains=keyword)
                | Q(tool_type_name__icontains=keyword)
            )
        if tool_parent_type:
            instance_query = instance_query.filter(tool_parent_type=tool_parent_type)
        if project or shield_machine:
            scoped = NewToolRecord.objects.all()
            if project:
                scoped = scoped.filter(tool_change_detail__warehouse__project_id=project)
            if shield_machine:
                scoped = scoped.filter(tool_change_detail__warehouse__shield_model_id=shield_machine)
            instance_query = instance_query.filter(
                id__in=scoped.values_list("tool_instance_id", flat=True)
            )

        # 这里不按 DB 的 status 过滤，统一在派生状态上过滤（见类注释口径修正第 3 条）
        for row in instance_query.order_by("create_datetime", "id").values(
            "id", "display_tool_no", "status"
        ):
            if row.get("display_tool_no"):
                seen_numbers.add(row["display_tool_no"])
            derived_status = "REMOVED" if removal_map.get(row["id"]) else row["status"]
            if status and derived_status != status:
                continue
            candidates.append({"kind": "instance", "key": row["id"]})

        # --- 历史（legacy）分支 ------------------------------------------------
        # 只保留没有对应 ToolInstance 的刀。用 GROUP BY 让数据库完成按 tool_number 的
        # 折叠，避免把"刀位数 × 开仓次数"量级的明细行读进 Python。
        legacy_base = ToolChangeDetail.objects.exclude(
            tool_number__isnull=True
        ).exclude(tool_number="")
        if project:
            legacy_base = legacy_base.filter(warehouse__project_id=project)
        if shield_machine:
            legacy_base = legacy_base.filter(warehouse__shield_model_id=shield_machine)
        if tool_parent_type:
            legacy_base = legacy_base.filter(tool_parent_type=tool_parent_type)
        if keyword:
            legacy_base = legacy_base.filter(
                Q(tool_number__icontains=keyword)
                | Q(cutter_position_no__icontains=keyword)
                | Q(cutter_position__tool_info__tool_type_name__icontains=keyword)
                | Q(warehouse__ring_no__icontains=keyword)
            )
        # 已有实例卡片的编号在 SQL 层排掉，可显著缩小分组集合；但 IN 列表过长本身也会
        # 拖慢查询，超过阈值时退回 Python 侧去重（下面的 seen_numbers 判断已覆盖）。
        if seen_numbers and len(seen_numbers) <= 500:
            legacy_base = legacy_base.exclude(tool_number__in=seen_numbers)

        grouped = (
            legacy_base
            .annotate(ring_int=Cast("warehouse__ring_no", output_field=IntegerField()))
            .values(
                "tool_number", "cutter_position_no",
                "warehouse__project_id", "warehouse__shield_model_id",
            )
            .annotate(first_ring=Min("ring_int"))
            .order_by("first_ring", "tool_number")
        )
        for row in grouped:
            display_number = row["tool_number"]
            if not display_number or display_number in seen_numbers:
                continue
            seen_numbers.add(display_number)
            removal_ring = self._next_replacement_ring(
                ring_map,
                row.get("warehouse__project_id"),
                row.get("warehouse__shield_model_id"),
                row.get("cutter_position_no"),
                row.get("first_ring"),
            )
            derived_status = "REMOVED" if removal_ring is not None else "INSTALLED"
            if status and derived_status != status:
                continue
            candidates.append({
                "kind": "legacy",
                "key": display_number,
                "first_ring": row.get("first_ring"),
            })

        # 兜底：换过刀但 tool_number 为空的历史行，编号由 lifecycle_tool_number 合成。
        # 这类行数量很少，按行处理即可。
        synth_base = ToolChangeDetail.objects.filter(is_replaced=True).filter(
            Q(tool_number__isnull=True) | Q(tool_number="")
        )
        if project:
            synth_base = synth_base.filter(warehouse__project_id=project)
        if shield_machine:
            synth_base = synth_base.filter(warehouse__shield_model_id=shield_machine)
        if tool_parent_type:
            synth_base = synth_base.filter(tool_parent_type=tool_parent_type)
        for row in synth_base.annotate(
            ring_int=Cast("warehouse__ring_no", output_field=IntegerField())
        ).order_by("ring_int", "id").values(
            "id", "cutter_position_no", "replacement_count", "ring_int",
            "warehouse__ring_no", "warehouse__project_id", "warehouse__shield_model_id",
        ):
            display_number = (
                f"R{row.get('warehouse__ring_no') or '0000'}-"
                f"{row.get('cutter_position_no')}-{row.get('replacement_count') or 1}"
            )
            if display_number in seen_numbers:
                continue
            seen_numbers.add(display_number)
            if keyword and keyword.lower() not in display_number.lower():
                continue
            removal_ring = self._next_replacement_ring(
                ring_map,
                row.get("warehouse__project_id"),
                row.get("warehouse__shield_model_id"),
                row.get("cutter_position_no"),
                row.get("ring_int"),
            )
            derived_status = "REMOVED" if removal_ring is not None else "INSTALLED"
            if status and derived_status != status:
                continue
            candidates.append({"kind": "legacy_id", "key": row["id"]})

        total = len(candidates)
        start = (page - 1) * limit
        page_items = candidates[start:start + limit]

        # --- 只对当前页做批量取数 ----------------------------------------------
        instance_ids = [c["key"] for c in page_items if c["kind"] == "instance"]
        legacy_numbers = [c["key"] for c in page_items if c["kind"] == "legacy"]
        legacy_ids = [c["key"] for c in page_items if c["kind"] == "legacy_id"]

        instances = {
            obj.id: obj
            for obj in ToolInstance.objects.filter(id__in=instance_ids).only(
                "id", "tool_uid", "display_tool_no", "tool_parent_type",
                "tool_type_name", "status", "tool_info_id", "create_datetime",
            )
        }
        install_map = self._install_detail_map(instance_ids)

        legacy_rows = {}
        if legacy_numbers:
            # 同一个 tool_number 会随开仓被继承出很多行，这里用分组阶段已经算出的
            # first_ring 把取数收窄到"首次出现的那一环"，避免又把继承链整段读回来。
            first_rings = {
                c["first_ring"] for c in page_items
                if c["kind"] == "legacy" and c.get("first_ring") is not None
            }
            legacy_detail_qs = (
                ToolChangeDetail.objects
                .filter(tool_number__in=legacy_numbers)
                .select_related("warehouse", "cutter_position", "cutter_position__tool_info")
                .annotate(ring_int=Cast("warehouse__ring_no", output_field=IntegerField()))
            )
            if first_rings:
                legacy_detail_qs = legacy_detail_qs.filter(ring_int__in=first_rings)
            for detail in legacy_detail_qs.order_by("ring_int", "id"):
                legacy_rows.setdefault(detail.tool_number, detail)
        if legacy_ids:
            for detail in (
                ToolChangeDetail.objects
                .filter(id__in=legacy_ids)
                .select_related("warehouse", "cutter_position", "cutter_position__tool_info")
            ):
                legacy_rows[f"__id__{detail.id}"] = detail

        cost_ids = [obj.tool_info_id for obj in instances.values()]
        cost_ids += [
            d.cutter_position.tool_info_id
            for d in legacy_rows.values()
            if d.cutter_position and d.cutter_position.tool_info_id
        ]
        cost_map = self._tool_cost_map(cost_ids)

        data = []
        for item in page_items:
            if item["kind"] == "instance":
                obj = instances.get(item["key"])
                if obj:
                    data.append(self.serialize_instance(
                        obj, include_timeline=False,
                        removal_map=removal_map, install_map=install_map, cost_map=cost_map,
                    ))
            else:
                lookup = item["key"] if item["kind"] == "legacy" else f"__id__{item['key']}"
                obj = legacy_rows.get(lookup)
                if obj:
                    data.append(self.serialize_legacy_detail(
                        obj, include_timeline=False, ring_map=ring_map, cost_map=cost_map,
                    ))

        return SuccessResponse(data=data, page=page, limit=limit, total=total, msg="success")

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def retrieve(self, request, pk=None):
        pk_value = str(pk or "")
        if pk_value.startswith("legacy-"):
            detail_id = pk_value.replace("legacy-", "", 1)
            if not detail_id.isdigit():
                return ErrorResponse(msg="刀具不存在")
            detail = ToolChangeDetail.objects.select_related(
                "warehouse",
                "warehouse__project",
                "warehouse__shield_model",
                "cutter_position",
                "cutter_position__tool_info",
            ).filter(pk=detail_id).first()
            if not detail or not lifecycle_tool_number(detail):
                return ErrorResponse(msg="刀具不存在")
            return SuccessResponse(
                data=self.serialize_legacy_detail(detail, include_timeline=True),
                msg="success",
            )

        if not pk_value.isdigit():
            return ErrorResponse(msg="刀具不存在")
        instance = ToolInstance.objects.select_related("tool_info").filter(pk=pk_value).first()
        if not instance:
            return ErrorResponse(msg="刀具不存在")
        return SuccessResponse(data=self.serialize_instance(instance, include_timeline=True), msg="success")

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def serialize_legacy_detail(self, detail, include_timeline=False, ring_map=None, cost_map=None):
        cutter_position = detail.cutter_position
        tool_info_id = cutter_position.tool_info_id if cutter_position else None
        if cost_map is not None and tool_info_id in cost_map:
            cost_info = cost_map[tool_info_id]
            tool_type_name = (
                cutter_position.tool_info.tool_type_name
                if cutter_position and cutter_position.tool_info else ""
            )
        else:
            tool_info = cutter_position.tool_info if cutter_position else None
            cost_info = tool_cost_info(tool_info)
            tool_type_name = tool_info.tool_type_name if tool_info else ""

        warehouse = detail.warehouse
        install_ring_no = warehouse.ring_no if warehouse else ""
        if ring_map is not None:
            removal_ring = self._next_replacement_ring(
                ring_map,
                warehouse.project_id if warehouse else None,
                warehouse.shield_model_id if warehouse else None,
                detail.cutter_position_no,
                ring_int_value(install_ring_no),
            )
            remove_ring_no = str(removal_ring) if removal_ring is not None else ""
            removed = removal_ring is not None
        else:
            remove_detail = next_replacement_detail(detail)
            remove_ring_no = (
                remove_detail.warehouse.ring_no
                if remove_detail and remove_detail.warehouse else ""
            )
            removed = remove_detail is not None

        data = {
            "id": f"legacy-{detail.id}",
            "tool_uid": lifecycle_tool_number(detail),
            "display_tool_no": lifecycle_tool_number(detail),
            "tool_parent_type": detail.tool_parent_type,
            "tool_type_name": tool_type_name,
            "brand": detail.brand or cost_info.get("brand") or "",
            "manufacturer": detail.manufacturer or cost_info.get("manufacturer") or "",
            "price": detail.price if detail.price is not None else cost_info.get("price"),
            **self._life_payload(install_ring_no, remove_ring_no),
            "status": "REMOVED" if removed else "INSTALLED",
            "pairing_confirmed": None,
            "pairing_source": "ring_sequence",
            "create_datetime": detail.create_datetime,
            "new_tool_components": new_tool_components_payload(getattr(detail, "new_tool_record", None)),
            "trajectory": get_tool_trajectory(detail.cutter_position_no, detail.tool_parent_type),
            "old_tool_inspection": old_tool_inspection_payload(
                getattr(detail, "old_tool_record", None), getattr(self, "request", None)
            ),
            "is_legacy": True,
        }
        if include_timeline:
            remove_detail = next_replacement_detail(detail)
            details = [detail]
            if remove_detail:
                details.append(remove_detail)
            timeline = []
            for index, item in enumerate(details):
                item_tool_info = item.cutter_position.tool_info if item.cutter_position else None
                item_cost_info = tool_cost_info(item_tool_info)
                old_record = getattr(item, "old_tool_record", None)
                timeline.append({
                    "event": "LEGACY_REMOVE" if index == 1 else "LEGACY_INSTALL",
                    "event_name": "换下记录" if index == 1 else ("换刀装上" if item.is_replaced else "开仓检查"),
                    "time": item.checked_at
                            or (item.warehouse.open_time if item.warehouse else None)
                            or item.create_datetime,
                    "brand": item.brand or item_cost_info.get("brand") or "",
                    "manufacturer": item.manufacturer or item_cost_info.get("manufacturer") or "",
                    "price": item.price if item.price is not None else item_cost_info.get("price"),
                    "wear_condition": item.wear_condition or "",
                    "inspection_status": getattr(old_record, "inspection_status", "") if old_record else "",
                    "photo_count": old_record.photos.count() if old_record else 0,
                    "old_tool_inspection": old_tool_inspection_payload(old_record, getattr(self, "request", None)),
                    "remark": item.remark or "",
                    **_detail_base(item),
                })
            data["timeline"] = timeline
        return data

    def serialize_instance(self, instance, include_timeline=False,
                           removal_map=None, install_map=None, cost_map=None):
        detail = None
        if install_map is not None and instance.id in install_map:
            install_info = install_map[instance.id]
            install_ring_no = install_info.get("ring_no") or ""
            trajectory = get_tool_trajectory(
                install_info.get("cutter_position_no"),
                install_info.get("tool_parent_type") or instance.tool_parent_type,
            )
        elif install_map is not None:
            install_ring_no = ""
            trajectory = get_tool_trajectory("", instance.tool_parent_type)
        else:
            install_record = (
                instance.new_tool_records
                .select_related("tool_change_detail__warehouse")
                .order_by("installed_at", "create_datetime")
                .first()
            )
            detail = install_record.tool_change_detail if install_record else None
            install_ring_no = detail.warehouse.ring_no if detail and detail.warehouse else ""
            trajectory = get_tool_trajectory(
                detail.cutter_position_no if detail else "",
                detail.tool_parent_type if detail else instance.tool_parent_type,
            )

        if removal_map is None:
            removal_map = self._instance_removal_map()
        pairing = removal_map.get(instance.id)
        remove_ring_no = (pairing or {}).get("ring_no") or ""
        pairing_confirmed = (pairing or {}).get("confirmed") if pairing else None

        if cost_map is not None and instance.tool_info_id in cost_map:
            cost_info = cost_map[instance.tool_info_id]
        else:
            cost_info = tool_cost_info(instance.tool_info)
        # 优先取装刀那条记录上留痕的厂家/单价，ToolCost 目录价只作兜底：
        # 否则 2025 年换了供应商后，2024 年装的刀会被回溯改写成新供应商与新价格，
        # 同一列表里旧数据行（serialize_legacy_detail）与实例行还会互相打架。
        cost_info = dict(cost_info)
        if detail is not None:
            if getattr(detail, "manufacturer", None):
                cost_info["manufacturer"] = detail.manufacturer
            if getattr(detail, "price", None) is not None:
                cost_info["price"] = detail.price

        data = {
            "id": instance.id,
            "tool_uid": instance.tool_uid,
            "display_tool_no": instance.display_tool_no,
            "tool_parent_type": instance.tool_parent_type,
            "tool_type_name": instance.tool_type_name,
            **cost_info,
            **self._life_payload(install_ring_no, remove_ring_no),
            "status": "REMOVED" if pairing else instance.status,
            # pairing_confirmed=false 表示"已拆下"是由 suggested_tool_instance 推断的，
            # 尚未经人工确认，服役环数据此计算，前端应给出待确认标识。
            "pairing_confirmed": pairing_confirmed,
            "pairing_source": (
                "confirmed" if pairing_confirmed
                else ("suggested" if pairing_confirmed is False else "none")
            ),
            "create_datetime": instance.create_datetime,
            "new_tool_components": new_tool_components_payload(
                getattr(detail, "new_tool_record", None) if detail else None
            ),
            "trajectory": trajectory,
        }
        if include_timeline:
            timeline = []
            for record in instance.new_tool_records.select_related(
                "tool_change_detail__warehouse__project",
                "tool_change_detail__warehouse",
                "installed_by",
            ).order_by("installed_at", "create_datetime"):
                detail = record.tool_change_detail
                timeline.append({
                    "event": "INSTALL",
                    "event_name": "新刀安装",
                    "time": record.installed_at or record.create_datetime,
                    "operator": getattr(record.installed_by, "name", "") or getattr(record.installed_by, "username", ""),
                    "new_tool_components": new_tool_components_payload(record),
                    "remark": record.remark or "",
                    **_detail_base(detail),
                })
            old_records = OldToolRecord.objects.filter(
                Q(confirmed_tool_instance=instance) | Q(suggested_tool_instance=instance)
            ).select_related(
                "tool_change_detail__warehouse__project",
                "tool_change_detail__warehouse",
            ).prefetch_related("photos").order_by("vendor_feedback_at", "create_datetime")
            for record in old_records:
                detail = record.tool_change_detail
                timeline.append({
                    "event": "REMOVE_INSPECT",
                    "event_name": "旧刀拆下/补录",
                    "time": record.vendor_feedback_at or record.create_datetime,
                    "inspection_status": record.inspection_status,
                    "pairing_confirmed": record.confirmed_tool_instance_id == instance.id,
                    "wear_condition": record.wear_condition or "",
                    "repair_result": record.repair_result or "",
                    "repair_parts": record.repair_parts or [],
                    "repair_price": record.repair_price,
                    "photo_count": record.photos.count(),
                    "old_tool_inspection": old_tool_inspection_payload(record, getattr(self, "request", None)),
                    "remark": record.remark or "",
                    **_detail_base(detail),
                })
            # 排序键统一成 (有无时间, 时间)，避免 str(None)=="None" 被排到日期之后
            timeline.sort(key=lambda item: (item.get("time") is None, item.get("time") or ""))
            data["timeline"] = timeline
        return data
