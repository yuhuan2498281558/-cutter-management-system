from django.core.validators import RegexValidator
from django.db import models, transaction
from django.conf import settings
from django.db.models import IntegerField
from django.db.models.functions import Cast
from django.db.models.signals import post_save
from django.dispatch import receiver
from dvadmin.utils.models import CoreModel


TOOL_TYPES = [
    ("DISC", "Disc cutter"),
    ("RIPPER", "Ripper"),
    ("SCRAPER", "Scraper"),
]

TOOL_TYPE_PREFIX = {
    "DISC": "GD",
    "RIPPER": "SLD",
    "SCRAPER": "GGD",
}

NEW_RING_TYPE_CHOICES = [
    ("SMOOTH", "光面"),
    ("INSERTED", "镶齿"),
]

NEW_COMPONENT_CONDITION_CHOICES = [
    ("NEW", "全新"),
    ("REPAIRED", "维修"),
]

BEARING_FAILURE_REASON_CHOICES = [
    ("SEAL_FAILURE", "密封失效"),
    ("LOAD_DEFORMATION", "受力变形"),
    ("FATIGUE_DAMAGE", "疲劳损坏"),
]

HUB_FAILURE_REASON_CHOICES = [
    ("WEAR", "磨损"),
    ("CRACK", "裂纹"),
    ("CHIP", "崩块"),
    ("FRACTURE", "断裂"),
]

RING_DAMAGE_CHOICES = [
    ("FRACTURE", "断裂"),
    ("CHIP", "崩口"),
    ("BOLT_LOSS", "掉螺栓"),
    ("C_BLOCK_LOSS", "C 块掉落"),
]

OLD_TOOL_DISPOSITION_CHOICES = [
    ("SCRAP", "报废"),
    ("REPAIRABLE", "可维修"),
]

# Excel 只规定了“磨损量”字段，没有提供单独的数据验证列表。这里保留
# 现场已经使用的描述，同时允许移动端在同一输入框内手动补充更具体的情况。
BLADE_WEAR_DESCRIPTION_CHOICES = [
    ("正常", "正常"),
    ("轻微磨损", "轻微磨损"),
    ("中度磨损", "中度磨损"),
    ("严重磨损", "严重磨损"),
    ("偏磨", "偏磨"),
    ("崩口", "崩口"),
    ("断裂", "断裂"),
    ("脱落", "脱落"),
    ("其他", "其他"),
]


class WearTypeDict(CoreModel):
    wear_type_name = models.CharField(max_length=50, verbose_name="wear type name")
    wear_type_code = models.CharField(max_length=20, unique=True, verbose_name="wear type code")
    description = models.TextField(blank=True, verbose_name="description")

    class Meta:
        verbose_name = "wear type dict"
        verbose_name_plural = verbose_name
        db_table = "shield_wear_type_dict"


class AbnormalCauseDict(CoreModel):
    cause_name = models.CharField(max_length=100, verbose_name="cause name")
    cause_code = models.CharField(max_length=20, unique=True, verbose_name="cause code")
    description = models.TextField(blank=True, verbose_name="description")

    class Meta:
        verbose_name = "abnormal cause dict"
        verbose_name_plural = verbose_name
        db_table = "shield_abnormal_cause_dict"


class ProjectInfo(CoreModel):
    project_id = models.CharField(max_length=50, unique=True, verbose_name="project id")
    project_name = models.CharField(max_length=100, verbose_name="project name")
    location = models.CharField(max_length=100, blank=True, verbose_name="location")
    start_location = models.CharField(max_length=100, blank=True, verbose_name="start location")
    start_longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, verbose_name="start longitude")
    start_latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, verbose_name="start latitude")
    end_location = models.CharField(max_length=100, blank=True, verbose_name="end location")
    end_longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, verbose_name="end longitude")
    end_latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, verbose_name="end latitude")
    current_location = models.CharField(max_length=100, blank=True, verbose_name="current location")
    current_longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, verbose_name="current longitude")
    current_latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, verbose_name="current latitude")
    excavation_diameter = models.FloatField(verbose_name="excavation diameter", null=True, blank=True)
    tunnel_length = models.FloatField(verbose_name="tunnel length", null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="budget", null=True, blank=True)
    estimated_time = models.DateTimeField(verbose_name="estimated time", null=True, blank=True)
    actual_time = models.DateTimeField(verbose_name="actual time", null=True, blank=True)
    project_introduction = models.TextField(blank=True, verbose_name="project introduction")

    class Meta:
        verbose_name = "project info"
        verbose_name_plural = verbose_name
        db_table = "shield_project_info"

    def __str__(self):
        return self.project_name


class ShieldMachineBasicInfo(CoreModel):
    shield_model_id = models.CharField(max_length=50, verbose_name="shield model id")
    shield_model = models.CharField(max_length=100, verbose_name="shield model")

    class Meta:
        verbose_name = "shield machine basic info"
        verbose_name_plural = verbose_name
        db_table = "shield_machine_basic_info"

    def __str__(self):
        return f"{self.shield_model_id} - {self.shield_model}"


class StratumBasicInfo(CoreModel):
    project = models.ForeignKey(ProjectInfo, on_delete=models.CASCADE, verbose_name="project")
    ring_no = models.CharField(max_length=20, verbose_name="ring no")
    stratum_type_codes = models.CharField(max_length=500, verbose_name="stratum type codes", blank=True)
    stratum_info = models.TextField(verbose_name="stratum info", blank=True)
    burial_depth = models.FloatField(verbose_name="burial depth", null=True, blank=True)

    class Meta:
        verbose_name = "stratum basic info"
        verbose_name_plural = verbose_name
        db_table = "shield_stratum_basic_info"
        unique_together = [["project", "ring_no"]]

    def __str__(self):
        return f"{self.project.project_name} - {self.ring_no}"

    def get_stratum_types(self):
        if not self.stratum_type_codes:
            return []
        from dvadmin.system.models import Dictionary

        result = []
        for code in self.stratum_type_codes.split(","):
            code = code.strip()
            if not code:
                continue
            item = Dictionary.objects.filter(parent__value="stratum_type", value=code, status=True).first()
            if item:
                result.append({"code": item.value, "name": item.label, "description": item.remark or ""})
        return result


class ToolCategory(CoreModel):
    tool_type = models.CharField(max_length=20, choices=TOOL_TYPES, verbose_name="tool type", null=True, blank=True)
    tool_name = models.CharField(max_length=100, verbose_name="tool name", null=True, blank=True)
    tool_number = models.CharField(max_length=50, unique=True, verbose_name="tool number", null=True, blank=True)
    cutter_position_no = models.CharField(max_length=20, verbose_name="cutter position no", null=True, blank=True)
    shield_machine = models.ForeignKey(
        ShieldMachineBasicInfo,
        on_delete=models.PROTECT,
        verbose_name="shield machine",
        null=True,
        blank=True,
        related_name="tool_categories",
    )

    class Meta:
        verbose_name = "tool category"
        verbose_name_plural = verbose_name
        db_table = "shield_tool_category"
        ordering = ["tool_type", "tool_number"]

    def __str__(self):
        return f"{self.get_tool_type_display()} - {self.tool_name} ({self.tool_number})"

    def save(self, *args, **kwargs):
        if not self.tool_number:
            self.tool_number = self.generate_tool_number()
        super().save(*args, **kwargs)

    @transaction.atomic
    def generate_tool_number(self):
        prefix = TOOL_TYPE_PREFIX.get(self.tool_type, "DJ")
        last_tool = (
            ToolCategory.objects.select_for_update()
            .filter(tool_type=self.tool_type, tool_number__startswith=prefix)
            .order_by("-tool_number")
            .first()
        )
        if last_tool and last_tool.tool_number:
            try:
                number = int(last_tool.tool_number.replace(prefix, "").replace("-", "")) + 1
            except ValueError:
                number = 1
        else:
            number = 1
        return f"{prefix}-{number:04d}"


class ToolInfo(CoreModel):
    tool_parent_type = models.CharField(max_length=20, choices=TOOL_TYPES, verbose_name="tool parent type", default="DISC")
    tool_type_name = models.CharField(max_length=100, verbose_name="tool type name", default="")
    tool_type_code = models.CharField(max_length=50, verbose_name="tool type code", blank=True, null=True)
    tool_number = models.CharField(max_length=50, unique=True, verbose_name="tool number", blank=True, null=True)
    shield_machine = models.ForeignKey(
        ShieldMachineBasicInfo,
        on_delete=models.PROTECT,
        verbose_name="shield machine",
        null=True,
        blank=True,
        related_name="tool_infos",
    )
    remark = models.TextField(blank=True, verbose_name="remark")

    class Meta:
        verbose_name = "tool info"
        verbose_name_plural = verbose_name
        db_table = "shield_tool_info"
        ordering = ["-create_datetime"]

    def __str__(self):
        return f"{self.tool_number} - {self.tool_type_name}"

    @property
    def manufacturer(self):
        cost = self.cost_records.order_by("-create_datetime").first()
        return cost.manufacturer if cost else None

    @property
    def unit_price(self):
        cost = self.cost_records.order_by("-create_datetime").first()
        return cost.unit_price if cost else None

    def save(self, *args, **kwargs):
        if not self.tool_type_code:
            self.tool_type_code = self.get_or_create_tool_type_code()
        if not self.tool_number:
            self.tool_number = self.generate_unique_tool_number()
        super().save(*args, **kwargs)

    def get_or_create_tool_type_code(self):
        existing = (
            ToolInfo.objects.filter(tool_parent_type=self.tool_parent_type, tool_type_name=self.tool_type_name)
            .exclude(id=self.id)
            .first()
        )
        if existing and existing.tool_type_code:
            return existing.tool_type_code
        return self.generate_tool_type_code()

    @transaction.atomic
    def generate_tool_type_code(self):
        prefix = TOOL_TYPE_PREFIX.get(self.tool_parent_type, "DJ")
        type_code_prefix = f"{prefix}-TYPE-"
        last_tool = (
            ToolInfo.objects.select_for_update()
            .filter(tool_type_code__startswith=type_code_prefix)
            .order_by("-tool_type_code")
            .first()
        )
        if last_tool and last_tool.tool_type_code:
            try:
                number = int(last_tool.tool_type_code.replace(type_code_prefix, "")) + 1
            except ValueError:
                number = 1
        else:
            number = 1
        return f"{type_code_prefix}{number:04d}"

    @transaction.atomic
    def generate_unique_tool_number(self):
        prefix = TOOL_TYPE_PREFIX.get(self.tool_parent_type, "DJ")
        tool_number_prefix = f"{prefix}-"
        last_tool = (
            ToolInfo.objects.select_for_update()
            .filter(tool_number__startswith=tool_number_prefix)
            .exclude(tool_number__contains="TYPE")
            .order_by("-tool_number")
            .first()
        )
        if last_tool and last_tool.tool_number:
            try:
                number = int(last_tool.tool_number.replace(tool_number_prefix, "")) + 1
            except ValueError:
                number = 1
        else:
            number = 1
        return f"{tool_number_prefix}{number:04d}"


class ToolCost(CoreModel):
    COST_TYPE_CHOICES = [
        ("NEW_TOOL", "New tool"),
        ("REPAIR", "Repair"),
    ]

    tool_info = models.ForeignKey(ToolInfo, on_delete=models.CASCADE, verbose_name="tool info", related_name="cost_records")
    cost_type = models.CharField(max_length=20, choices=COST_TYPE_CHOICES, verbose_name="cost type")
    brand = models.CharField(max_length=100, verbose_name="brand", null=True, blank=True)
    manufacturer = models.CharField(max_length=100, verbose_name="manufacturer", null=True, blank=True)
    inventory = models.IntegerField(default=0, verbose_name="inventory")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="unit price", null=True, blank=True)
    repair_parts = models.JSONField(verbose_name="repair parts", default=list, blank=True)
    remark = models.TextField(verbose_name="remark", blank=True)

    class Meta:
        verbose_name = "tool cost"
        verbose_name_plural = verbose_name
        db_table = "shield_tool_cost"
        ordering = ["-create_datetime"]

    def __str__(self):
        return f"{self.tool_info.tool_type_name} - {self.get_cost_type_display()}"


class ShieldTunnelingData(CoreModel):
    project = models.ForeignKey(ProjectInfo, on_delete=models.CASCADE, verbose_name="project", related_name="tunneling_data")
    shield_machine = models.ForeignKey(
        ShieldMachineBasicInfo,
        on_delete=models.PROTECT,
        verbose_name="shield machine",
        related_name="tunneling_data",
    )
    ring_no = models.CharField(max_length=20, verbose_name="ring no")
    thrust = models.FloatField(verbose_name="thrust", null=True, blank=True)
    torque = models.FloatField(verbose_name="torque", null=True, blank=True)
    cutterhead_speed = models.FloatField(verbose_name="cutterhead speed", null=True, blank=True)
    penetration = models.FloatField(verbose_name="penetration", null=True, blank=True)
    record_time = models.DateTimeField(verbose_name="record time", null=True, blank=True)
    raw_parameters = models.JSONField(verbose_name="raw parameters", default=dict, blank=True)
    point_count = models.IntegerField(verbose_name="point count", default=0)
    import_source = models.CharField(max_length=500, verbose_name="import source", blank=True)
    remark = models.TextField(verbose_name="remark", blank=True)

    class Meta:
        verbose_name = "shield tunneling data"
        verbose_name_plural = verbose_name
        db_table = "shield_tunneling_data"
        ordering = ["project", "ring_no", "-record_time"]

    def __str__(self):
        return f"{self.project.project_name} - {self.ring_no}"


class ToolLifePrediction(CoreModel):
    tool_info = models.ForeignKey(
        ToolInfo,
        on_delete=models.CASCADE,
        verbose_name="tool info",
        related_name="life_predictions",
    )
    tool_number = models.CharField(max_length=50, verbose_name="tool number", blank=True, null=True)
    usage_time = models.FloatField(verbose_name="usage time", null=True, blank=True)
    usage_rings = models.IntegerField(verbose_name="usage rings", null=True, blank=True)
    remaining_life = models.FloatField(verbose_name="remaining life", null=True, blank=True)
    future_stratum_type = models.CharField(max_length=100, verbose_name="future stratum type", blank=True, null=True)
    prediction_time = models.DateTimeField(verbose_name="prediction time", null=True, blank=True)
    remark = models.TextField(verbose_name="remark", blank=True)

    class Meta:
        verbose_name = "tool life prediction"
        verbose_name_plural = verbose_name
        db_table = "shield_tool_life_prediction"
        ordering = ["-prediction_time", "-create_datetime"]

    def __str__(self):
        return f"{self.tool_number or self.tool_info.tool_number} - {self.remaining_life}"

    def save(self, *args, **kwargs):
        if self.tool_info and not self.tool_number:
            self.tool_number = self.tool_info.tool_number
        super().save(*args, **kwargs)


class CutterPositionInfo(CoreModel):
    shield_machine = models.ForeignKey(
        ShieldMachineBasicInfo,
        on_delete=models.CASCADE,
        verbose_name="shield machine",
        related_name="cutter_positions",
    )
    cutter_position_no = models.CharField(max_length=20, verbose_name="cutter position no")
    tool_type = models.CharField(max_length=20, choices=TOOL_TYPES, verbose_name="tool type", null=True, blank=True)
    tool_category = models.ForeignKey(
        ToolCategory,
        on_delete=models.PROTECT,
        verbose_name="tool category",
        related_name="cutter_positions_old",
        null=True,
        blank=True,
    )
    tool_info = models.ForeignKey(
        ToolInfo,
        on_delete=models.PROTECT,
        verbose_name="tool info",
        related_name="cutter_positions",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "cutter position info"
        verbose_name_plural = verbose_name
        db_table = "shield_cutter_position_info"
        unique_together = [["shield_machine", "cutter_position_no"]]
        ordering = ["shield_machine", "cutter_position_no"]

    def __str__(self):
        return f"{self.shield_machine.shield_model_id} - {self.cutter_position_no}"

    def save(self, *args, **kwargs):
        if self.tool_info:
            self.tool_type = self.tool_info.tool_parent_type
        super().save(*args, **kwargs)


class CutterModelMapping(CoreModel):
    model_point_code = models.CharField(max_length=50, unique=True, verbose_name="model point code")
    component_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="BIM component id")
    cutter_position = models.ForeignKey(
        CutterPositionInfo,
        on_delete=models.CASCADE,
        related_name="model_mappings",
        verbose_name="cutter position",
    )
    screen_x = models.FloatField(null=True, blank=True, verbose_name="screen x")
    screen_y = models.FloatField(null=True, blank=True, verbose_name="screen y")
    sort_no = models.IntegerField(default=0, verbose_name="sort no")
    is_active = models.BooleanField(default=True, verbose_name="active")
    remark = models.CharField(max_length=255, blank=True, null=True, verbose_name="remark")

    class Meta:
        verbose_name = "cutter model mapping"
        verbose_name_plural = verbose_name
        db_table = "shield_cutter_model_mapping"
        ordering = ["sort_no", "model_point_code"]

    def __str__(self):
        return f"{self.model_point_code} -> {self.cutter_position.cutter_position_no}"


class CutterImageAnnotation(CoreModel):
    cutter_position = models.ForeignKey(
        CutterPositionInfo,
        on_delete=models.CASCADE,
        related_name="image_annotations",
        verbose_name="cutter position",
    )
    annotation_id = models.CharField(max_length=100, unique=True, verbose_name="annotation id")
    image_key = models.CharField(max_length=100, default="cutterhead-final-v1", verbose_name="image key")
    selector = models.JSONField(default=dict, verbose_name="image selector")
    canvas_width = models.PositiveIntegerField(default=1900, verbose_name="canvas width")
    canvas_height = models.PositiveIntegerField(default=2100, verbose_name="canvas height")
    is_active = models.BooleanField(default=True, verbose_name="active")

    class Meta:
        verbose_name = "cutter image annotation"
        verbose_name_plural = verbose_name
        db_table = "shield_cutter_image_annotation"
        ordering = ["cutter_position__cutter_position_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["cutter_position", "image_key"],
                name="uniq_cutter_image_annotation_position_image",
            )
        ]

    def __str__(self):
        return f"{self.image_key} -> {self.cutter_position.cutter_position_no}"


class WarehouseOpeningBasicInfo(CoreModel):
    warehouse_id = models.CharField(max_length=50, unique=True, verbose_name="warehouse id", blank=True)
    open_time = models.DateTimeField(verbose_name="open time")
    section = models.CharField(max_length=100, verbose_name="section", blank=True, null=True)
    # 环号必须是纯数字：全系统有十余处把它 Cast 成整数排序/比较，
    # 一条 "500环" 这样的脏数据就会让 PostgreSQL 抛 DataError、整页 500。
    ring_no = models.CharField(
        max_length=20, verbose_name="ring no",
        validators=[RegexValidator(r"^\d+$", "环号必须是纯数字")],
    )
    project = models.ForeignKey(ProjectInfo, on_delete=models.CASCADE, verbose_name="project")
    shield_model = models.ForeignKey(
        ShieldMachineBasicInfo,
        on_delete=models.PROTECT,
        verbose_name="shield model",
        null=True,
        blank=True,
    )
    opening_duration = models.FloatField(verbose_name="opening duration", null=True, blank=True)
    checked_tool_count = models.IntegerField(verbose_name="checked tool count", null=True, blank=True)
    replaced_tool_count = models.IntegerField(verbose_name="replaced tool count", null=True, blank=True)
    last_ring_no = models.CharField(max_length=20, verbose_name="last ring no", blank=True, null=True)
    rings_between_openings = models.IntegerField(verbose_name="rings between openings", null=True, blank=True)
    stratum_info_between = models.JSONField(verbose_name="stratum info between", default=dict, blank=True)
    geological_conditions = models.TextField(verbose_name="geological conditions", blank=True, null=True)
    # Excel 中的开仓/换刀公共信息。旧的 opening_duration 等字段继续保留，
    # 新字段允许为空，以兼容已存在的开仓记录。
    blade_track = models.CharField(max_length=255, verbose_name="blade track", blank=True, null=True)
    tool_change_date = models.DateField(verbose_name="tool change date", blank=True, null=True)
    tool_change_duration = models.FloatField(verbose_name="tool change duration", blank=True, null=True)
    usage_distance = models.FloatField(verbose_name="usage distance", blank=True, null=True)

    class Meta:
        verbose_name = "warehouse opening basic info"
        verbose_name_plural = verbose_name
        db_table = "shield_warehouse_opening_basic"
        ordering = ["-open_time"]

    def __str__(self):
        return f"{self.warehouse_id} - {self.ring_no}"

    @transaction.atomic
    def generate_warehouse_id(self):
        if not self.project or not self.ring_no:
            return None
        # 编号后缀取"现有最大后缀 +1"，不能用实时 count：
        # 环 500 建过 CL-500 与 CL-500-2 后删掉 CL-500，count 会退回 1，
        # 再建一条又生成 CL-500-2，撞 unique 约束直接 500，用户根本录不进去。
        prefix = f"{self.project.project_id}-{self.ring_no}"
        existing = list(
            WarehouseOpeningBasicInfo.objects.select_for_update()
            .filter(project=self.project, ring_no=self.ring_no)
            .exclude(id=self.id)
            .values_list("warehouse_id", flat=True)
        )
        if not existing:
            return prefix
        max_suffix = 1
        for wid in existing:
            if not wid:
                continue
            if wid == prefix:
                max_suffix = max(max_suffix, 1)
            elif wid.startswith(prefix + "-"):
                tail = wid[len(prefix) + 1:]
                if tail.isdigit():
                    max_suffix = max(max_suffix, int(tail))
        return f"{prefix}-{max_suffix + 1}"

    def save(self, *args, **kwargs):
        if not self.warehouse_id:
            self.warehouse_id = self.generate_warehouse_id()
        self._fill_ring_gap()
        super().save(*args, **kwargs)
        self._refresh_next_opening_gap()

    def _refresh_next_opening_gap(self):
        """补录中间环号后，回溯重算"下一条开仓"的间隔。

        原实现只在保存自身时算一次快照，之后永不更新：已有环 100、200 时
        再补录环 150，环 200 仍写着"距上次 100 环"，平均开仓间隔与自动地层
        区间都会长期偏大。
        """
        if not self.project_id or not self.ring_no:
            return
        try:
            current_ring = int(self.ring_no)
        except (ValueError, TypeError):
            return
        siblings = WarehouseOpeningBasicInfo.objects.filter(project_id=self.project_id)
        if self.shield_model_id:
            siblings = siblings.filter(shield_model_id=self.shield_model_id)
        nxt, nxt_ring = None, None
        for opening in siblings.exclude(id=self.id).only("id", "ring_no"):
            try:
                ring = int(opening.ring_no)
            except (ValueError, TypeError):
                continue
            if ring > current_ring and (nxt_ring is None or ring < nxt_ring):
                nxt, nxt_ring = opening, ring
        if nxt is None:
            return
        if nxt.last_ring_no == self.ring_no and nxt.rings_between_openings == nxt_ring - current_ring:
            return
        nxt.last_ring_no = self.ring_no
        nxt.rings_between_openings = nxt_ring - current_ring
        # 只更新这两个字段，避免递归触发本方法
        super(WarehouseOpeningBasicInfo, nxt).save(
            update_fields=["last_ring_no", "rings_between_openings"]
        )

    def _fill_ring_gap(self):
        if not self.project or not self.ring_no:
            return
        try:
            current_ring = int(self.ring_no)
        except (ValueError, TypeError):
            self.last_ring_no = None
            self.rings_between_openings = None
            return

        last_opening = None
        valid = []
        # 必须同时限定盾构机：一个项目跑两台机时，只按 project 找会把另一台机的
        # 开仓当成"上一次"，导致开仓间隔与刀具编号继承全部串号。
        siblings = WarehouseOpeningBasicInfo.objects.filter(project=self.project)
        if self.shield_model_id:
            siblings = siblings.filter(shield_model_id=self.shield_model_id)
        for opening in siblings.exclude(id=self.id).values("id", "ring_no"):
            try:
                ring = int(opening["ring_no"])
            except (ValueError, TypeError):
                continue
            if ring < current_ring:
                valid.append((ring, opening["id"]))
        if valid:
            valid.sort(reverse=True)
            last_ring, last_id = valid[0]
            last_opening = WarehouseOpeningBasicInfo.objects.get(id=last_id)
            self.last_ring_no = last_opening.ring_no
            self.rings_between_openings = current_ring - last_ring
        else:
            self.last_ring_no = None
            self.rings_between_openings = current_ring


class ToolChangeDetail(CoreModel):
    REPLACEMENT_TYPE_CHOICES = [
        ("COMPLETE", "Complete"),
        ("REPAIR", "Repair"),
    ]
    WEAR_CONDITION_CHOICES = [
        ("GOOD", "Good"),
        ("NORMAL", "Normal"),
        ("MODERATE", "Moderate"),
        ("SEVERE", "Severe"),
        ("ABNORMAL", "Abnormal"),
    ]

    warehouse = models.ForeignKey(
        WarehouseOpeningBasicInfo,
        on_delete=models.CASCADE,
        verbose_name="warehouse",
        related_name="tool_change_details",
    )
    cutter_position = models.ForeignKey(
        CutterPositionInfo,
        on_delete=models.PROTECT,
        verbose_name="cutter position",
        null=True,
        blank=True,
    )
    cutter_position_no = models.CharField(max_length=50, verbose_name="cutter position no", null=True, blank=True)
    tool_parent_type = models.CharField(max_length=20, verbose_name="tool parent type", null=True, blank=True)
    tool_number = models.CharField(max_length=50, verbose_name="tool number", null=True, blank=True)
    wear_condition = models.CharField(max_length=50, verbose_name="wear condition", null=True, blank=True)
    blade_wear_amount = models.FloatField(verbose_name="blade wear amount", null=True, blank=True)
    is_replaced = models.BooleanField(default=False, verbose_name="is replaced")
    replacement_count = models.IntegerField(verbose_name="replacement count", default=0)
    manufacturer = models.CharField(max_length=100, verbose_name="manufacturer", null=True, blank=True)
    replacement_type = models.CharField(max_length=20, choices=REPLACEMENT_TYPE_CHOICES, verbose_name="replacement type", null=True, blank=True)
    repair_parts = models.JSONField(verbose_name="repair parts", default=list, blank=True)
    brand = models.CharField(max_length=100, verbose_name="brand", null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="price", null=True, blank=True)
    wear_image = models.ImageField(upload_to="tool_wear_images/%Y/%m/", verbose_name="wear image", null=True, blank=True)
    remark = models.TextField(verbose_name="remark", blank=True, null=True)
    CHECK_RESULT_CHOICES = [
        ("PENDING", "Pending"),
        ("NOT_REPLACED", "Not replaced"),
        ("NORMAL", "Normal"),
        ("ATTENTION", "Attention"),
        ("ABNORMAL_NOT_REPLACED", "Abnormal not replaced"),
    ]
    MOBILE_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("SAVED", "Saved"),
        ("SUBMITTED", "Submitted"),
    ]
    is_checked = models.BooleanField(default=False, verbose_name="is checked")
    check_result = models.CharField(max_length=30, choices=CHECK_RESULT_CHOICES, default="PENDING", verbose_name="check result")
    mobile_status = models.CharField(max_length=20, choices=MOBILE_STATUS_CHOICES, default="PENDING", verbose_name="mobile status")
    checked_at = models.DateTimeField(verbose_name="checked at", null=True, blank=True)
    mobile_task = models.ForeignKey(
        "MobileToolChangeTask",
        on_delete=models.SET_NULL,
        verbose_name="mobile task",
        related_name="details",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "tool change detail"
        verbose_name_plural = verbose_name
        db_table = "shield_tool_change_detail"
        ordering = ["cutter_position_no"]
        unique_together = [["warehouse", "cutter_position_no"]]

    def __str__(self):
        return f"{self.warehouse.warehouse_id} - {self.cutter_position_no}"

    def save(self, *args, **kwargs):
        if self.cutter_position:
            self.cutter_position_no = self.cutter_position.cutter_position_no
            self.tool_parent_type = self.cutter_position.tool_type

        if self.warehouse_id and self.cutter_position_no:
            try:
                current_ring = int(self.warehouse.ring_no)
            except (ValueError, TypeError):
                current_ring = None

            if current_ring is not None:
                query = (
                    ToolChangeDetail.objects.filter(
                        warehouse__project=self.warehouse.project,
                        cutter_position_no=self.cutter_position_no,
                        is_replaced=True,
                    )
                    # 同刀位编号在两台盾构机上都存在，不限定机器会把别的机器的
                    # 更换次数也算进来
                    .filter(warehouse__shield_model_id=self.warehouse.shield_model_id)
                    # 非数字环号会让 CAST 抛错，先滤掉
                    .filter(warehouse__ring_no__regex=r"^\d+$")
                    .annotate(ring_int=Cast("warehouse__ring_no", output_field=IntegerField()))
                    .filter(ring_int__lt=current_ring)
                )
                if self.pk:
                    query = query.exclude(pk=self.pk)
                previous_replacements = query.count()
            else:
                previous_replacements = 0
            self.replacement_count = previous_replacements + 1 if self.is_replaced else previous_replacements

        super().save(*args, **kwargs)


@receiver(post_save, sender=WarehouseOpeningBasicInfo)
def create_tool_change_details(sender, instance, created, **kwargs):
    # 原实现要求 created=True：建开仓时漏选盾构机 → 一条明细都不生成，
    # 事后补选盾构机时 created=False 直接返回，该环号永久无法录入换刀，
    # 移动端也建不出任务。改为只要还没有明细就补建（下面 get_or_create 幂等）。
    if not instance.shield_model:
        return
    if not created and ToolChangeDetail.objects.filter(warehouse=instance).exists():
        return

    cutter_positions = CutterPositionInfo.objects.filter(shield_machine=instance.shield_model).order_by("id")
    last_opening = None
    if instance.project:
        try:
            current_ring = int(instance.ring_no)
        except (ValueError, TypeError):
            current_ring = None
        if current_ring is not None:
            valid = []
            _siblings = WarehouseOpeningBasicInfo.objects.filter(project=instance.project)
            if instance.shield_model_id:
                _siblings = _siblings.filter(shield_model_id=instance.shield_model_id)
            for opening in _siblings.exclude(id=instance.id).values("id", "ring_no"):
                try:
                    ring = int(opening["ring_no"])
                except (ValueError, TypeError):
                    continue
                if ring < current_ring:
                    valid.append((ring, opening["id"]))
            if valid:
                valid.sort(reverse=True)
                last_opening = WarehouseOpeningBasicInfo.objects.get(id=valid[0][1])

    last_details = {}
    if last_opening:
        for detail in ToolChangeDetail.objects.filter(warehouse=last_opening):
            last_details[detail.cutter_position_no] = {"tool_number": detail.tool_number}

    for pos in cutter_positions:
        last_detail = last_details.get(pos.cutter_position_no, {})
        # get_or_create：补选盾构机时重跑本信号不会产生重复明细
        ToolChangeDetail.objects.get_or_create(
            warehouse=instance,
            cutter_position_no=pos.cutter_position_no,
            defaults=dict(
                cutter_position=pos,
                tool_parent_type=pos.tool_type,
                tool_number=last_detail.get("tool_number", ""),
                # 自动生成的检查行代表"尚未记录"，不是"正常"。
                # 原来写死英文 "NORMAL"：既与现场录入的中文词表对不上，又会被
                # 分析侧的 !='正常' 判定当成异常磨损，把未填写的行算进异常率。
                wear_condition="",
                is_replaced=False,
            ),
        )


    MobileToolChangeTask.objects.get_or_create(
        warehouse=instance,
        scope_type="ALL",
        defaults={"status": "UNASSIGNED"},
    )

class MobileToolChangeTask(CoreModel):
    STATUS_CHOICES = [
        ("UNASSIGNED", "Unassigned"),
        ("PENDING", "Pending"),
        ("IN_PROGRESS", "In progress"),
        ("SUBMITTED", "Submitted"),
        ("RETURNED", "Returned"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    ]
    SCOPE_TYPE_CHOICES = [
        ("ALL", "All"),
        ("TOOL_TYPE", "Tool type"),
        ("POSITION_LIST", "Position list"),
    ]

    warehouse = models.ForeignKey(
        WarehouseOpeningBasicInfo,
        on_delete=models.CASCADE,
        verbose_name="warehouse",
        related_name="mobile_tasks",
    )
    recorder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="recorder",
        related_name="mobile_tool_change_tasks",
        null=True,
        blank=True,
        db_constraint=False,
    )
    scope_type = models.CharField(max_length=20, choices=SCOPE_TYPE_CHOICES, default="ALL", verbose_name="scope type")
    tool_types = models.JSONField(default=list, blank=True, verbose_name="tool types")
    position_nos = models.JSONField(default=list, blank=True, verbose_name="position nos")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="UNASSIGNED", verbose_name="status")
    submitted_at = models.DateTimeField(verbose_name="submitted at", null=True, blank=True)
    returned_reason = models.TextField(verbose_name="returned reason", blank=True, null=True)

    class Meta:
        verbose_name = "mobile tool change task"
        verbose_name_plural = verbose_name
        db_table = "shield_mobile_tool_change_task"
        ordering = ["-create_datetime"]

    def __str__(self):
        return f"{self.warehouse_id}-{self.recorder_id or 'unassigned'}-{self.scope_type}"


class ToolInstance(CoreModel):
    STATUS_CHOICES = [
        ("PENDING_VERIFY", "Pending verify"),
        ("INSTALLED", "Installed"),
        ("REMOVED_PENDING_INSPECTION", "Removed pending inspection"),
        ("INSPECTED", "Inspected"),
        ("REPAIRED_CLOSED", "Repaired closed"),
        ("SCRAPPED", "Scrapped"),
    ]

    tool_uid = models.CharField(max_length=120, unique=True, verbose_name="tool uid")
    display_tool_no = models.CharField(max_length=80, verbose_name="display tool no")
    tool_info = models.ForeignKey(ToolInfo, on_delete=models.PROTECT, verbose_name="tool info", null=True, blank=True)
    tool_parent_type = models.CharField(max_length=20, verbose_name="tool parent type", null=True, blank=True)
    tool_type_name = models.CharField(max_length=100, verbose_name="tool type name", null=True, blank=True)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default="PENDING_VERIFY", verbose_name="status")

    class Meta:
        verbose_name = "tool instance"
        verbose_name_plural = verbose_name
        db_table = "shield_tool_instance"
        ordering = ["-create_datetime"]

    def __str__(self):
        return self.tool_uid


class NewToolRecord(CoreModel):
    tool_change_detail = models.OneToOneField(
        ToolChangeDetail,
        on_delete=models.CASCADE,
        verbose_name="tool change detail",
        related_name="new_tool_record",
    )
    tool_instance = models.ForeignKey(ToolInstance, on_delete=models.PROTECT, verbose_name="tool instance", related_name="new_tool_records")
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        verbose_name="installed by",
        related_name="installed_new_tools",
        null=True,
        blank=True,
        db_constraint=False,
    )
    installed_at = models.DateTimeField(verbose_name="installed at", null=True, blank=True)
    ring_type = models.CharField(
        max_length=20,
        choices=NEW_RING_TYPE_CHOICES,
        verbose_name="cutter ring type",
        null=True,
        blank=True,
    )
    ring_manufacturer = models.CharField(max_length=100, verbose_name="cutter ring manufacturer", null=True, blank=True)
    shaft_condition = models.CharField(
        max_length=20,
        choices=NEW_COMPONENT_CONDITION_CHOICES,
        verbose_name="cutter shaft condition",
        null=True,
        blank=True,
    )
    shaft_manufacturer = models.CharField(max_length=100, verbose_name="cutter shaft manufacturer", null=True, blank=True)
    hub_condition = models.CharField(
        max_length=20,
        choices=NEW_COMPONENT_CONDITION_CHOICES,
        verbose_name="cutter hub condition",
        null=True,
        blank=True,
    )
    hub_manufacturer = models.CharField(max_length=100, verbose_name="cutter hub manufacturer", null=True, blank=True)
    scraper_manufacturer = models.CharField(max_length=100, verbose_name="new scraper manufacturer", null=True, blank=True)
    remark = models.TextField(verbose_name="remark", blank=True, null=True)

    class Meta:
        verbose_name = "new tool record"
        verbose_name_plural = verbose_name
        db_table = "shield_new_tool_record"

    def __str__(self):
        return self.tool_instance.tool_uid


class OldToolRecord(CoreModel):
    INSPECTION_STATUS_CHOICES = [
        ("PENDING_VENDOR_FEEDBACK", "Pending vendor feedback"),
        ("CONFIRMED", "Confirmed"),
        ("CLOSED", "Closed"),
    ]

    tool_change_detail = models.OneToOneField(
        ToolChangeDetail,
        on_delete=models.CASCADE,
        verbose_name="tool change detail",
        related_name="old_tool_record",
    )
    suggested_tool_instance = models.ForeignKey(
        ToolInstance,
        on_delete=models.SET_NULL,
        verbose_name="suggested tool instance",
        related_name="suggested_old_records",
        null=True,
        blank=True,
    )
    confirmed_tool_instance = models.ForeignKey(
        ToolInstance,
        on_delete=models.SET_NULL,
        verbose_name="confirmed tool instance",
        related_name="confirmed_old_records",
        null=True,
        blank=True,
    )
    old_tool_number = models.CharField(max_length=120, verbose_name="old tool number", null=True, blank=True)
    wear_condition = models.CharField(max_length=50, verbose_name="wear condition", null=True, blank=True)
    repair_parts = models.JSONField(verbose_name="repair parts", default=list, blank=True)
    repair_result = models.CharField(max_length=100, verbose_name="repair result", null=True, blank=True)
    repair_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="repair price", null=True, blank=True)
    ring_wear_amount = models.FloatField(verbose_name="cutter ring wear amount", null=True, blank=True)
    bias_wear_amount = models.FloatField(verbose_name="bias wear amount", null=True, blank=True)
    tool_track = models.CharField(max_length=255, verbose_name="tool track", null=True, blank=True)
    ring_damage = models.JSONField(verbose_name="cutter ring damage", default=list, blank=True)
    ring_tooth_loss_count = models.IntegerField(verbose_name="cutter ring tooth loss count", null=True, blank=True)
    ring_other_condition = models.TextField(verbose_name="cutter ring other condition", null=True, blank=True)
    bearing_failed = models.BooleanField(verbose_name="bearing failed", null=True, blank=True)
    bearing_failure_reasons = models.JSONField(verbose_name="bearing failure reasons", default=list, blank=True)
    bearing_other_condition = models.TextField(verbose_name="bearing other condition", null=True, blank=True)
    hub_damaged = models.BooleanField(verbose_name="cutter hub damaged", null=True, blank=True)
    hub_failure_reasons = models.JSONField(verbose_name="cutter hub failure reasons", default=list, blank=True)
    hub_other_condition = models.TextField(verbose_name="cutter hub other condition", null=True, blank=True)
    disposition = models.CharField(
        max_length=20,
        choices=OLD_TOOL_DISPOSITION_CHOICES,
        verbose_name="old tool disposition",
        null=True,
        blank=True,
    )
    scraper_wear_amount = models.FloatField(verbose_name="scraper wear amount", null=True, blank=True)
    scraper_chipped = models.BooleanField(verbose_name="scraper chipped", null=True, blank=True)
    scraper_broken = models.BooleanField(verbose_name="scraper broken", null=True, blank=True)
    scraper_detached = models.BooleanField(verbose_name="scraper detached", null=True, blank=True)
    inspection_status = models.CharField(
        max_length=40,
        choices=INSPECTION_STATUS_CHOICES,
        default="PENDING_VENDOR_FEEDBACK",
        verbose_name="inspection status",
    )
    vendor_feedback_at = models.DateTimeField(verbose_name="vendor feedback at", null=True, blank=True)
    remark = models.TextField(verbose_name="remark", blank=True, null=True)

    class Meta:
        verbose_name = "old tool record"
        verbose_name_plural = verbose_name
        db_table = "shield_old_tool_record"

    def __str__(self):
        return f"old-{self.tool_change_detail_id}"


class OldToolPhoto(CoreModel):
    old_tool_record = models.ForeignKey(
        OldToolRecord,
        on_delete=models.CASCADE,
        verbose_name="old tool record",
        related_name="photos",
    )
    image = models.ImageField(upload_to="old_tool_photos/%Y/%m/", verbose_name="image")
    original_filename = models.CharField(max_length=255, verbose_name="original filename", blank=True, null=True)
    file_size = models.BigIntegerField(verbose_name="file size", null=True, blank=True)
    mime_type = models.CharField(max_length=100, verbose_name="mime type", blank=True, null=True)
    remark = models.TextField(verbose_name="remark", blank=True, null=True)

    class Meta:
        verbose_name = "old tool photo"
        verbose_name_plural = verbose_name
        db_table = "shield_old_tool_photo"
        ordering = ["create_datetime"]

    def __str__(self):
        return self.original_filename or str(self.image)


class ToolPerformanceIndicator(models.Model):
    tool_id = models.CharField(max_length=50, verbose_name="tool id")
    tool_name = models.CharField(max_length=50, verbose_name="tool name")
    project_id = models.CharField(max_length=50, verbose_name="project id")
    project_name = models.CharField(max_length=100, verbose_name="project name")
    usage_time = models.FloatField(verbose_name="usage time", null=True, blank=True)
    tunnel_distance = models.FloatField(verbose_name="tunnel distance", null=True, blank=True)
    tunnel_rings = models.IntegerField(verbose_name="tunnel rings", null=True, blank=True)
    wear_amount = models.FloatField(verbose_name="wear amount", null=True, blank=True)
    tunnel_speed = models.FloatField(verbose_name="tunnel speed", null=True, blank=True)
    efficiency_score = models.FloatField(verbose_name="efficiency score", null=True, blank=True)
    tool_cost = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="tool cost", null=True, blank=True)
    record_time = models.DateTimeField(verbose_name="record time", null=True, blank=True)

    class Meta:
        managed = False
        verbose_name = "tool performance indicator"
        verbose_name_plural = verbose_name


class ToolPerformanceEvaluation(models.Model):
    tool_id = models.CharField(max_length=50, verbose_name="tool id")
    tool_name = models.CharField(max_length=50, verbose_name="tool name")
    tool_category = models.CharField(max_length=50, verbose_name="tool category")
    comprehensive_performance = models.CharField(max_length=20, verbose_name="comprehensive performance", null=True, blank=True)
    cost_efficiency_ratio = models.FloatField(verbose_name="cost efficiency ratio", null=True, blank=True)
    durability_index = models.FloatField(verbose_name="durability index", null=True, blank=True)
    replacement_frequency = models.FloatField(verbose_name="replacement frequency", null=True, blank=True)
    avg_tunnel_distance = models.FloatField(verbose_name="avg tunnel distance", null=True, blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="total cost", null=True, blank=True)
    record_time = models.DateTimeField(verbose_name="record time", null=True, blank=True)

    class Meta:
        managed = False
        verbose_name = "tool performance evaluation"
        verbose_name_plural = verbose_name
