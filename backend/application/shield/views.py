# -*- coding: utf-8 -*-
import csv
import io
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime

"""
@Remark: 盾构项目管理和刀具管理
"""
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.db import transaction
from django.db.models import IntegerField
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from dvadmin.utils.json_response import DetailResponse, ErrorResponse, SuccessResponse
from dvadmin.utils.permission import AnonymousUserPermission
from dvadmin.utils.serializers import CustomModelSerializer
from dvadmin.utils.viewset import CustomModelViewSet
from dvadmin.utils.import_export_mixin import ImportSerializerMixin, ExportSerializerMixin
from .models import (
    ProjectInfo,
    ToolCategory,
    ToolCost,
    ToolInfo,
    WarehouseOpeningBasicInfo,
    ToolChangeDetail,
    NewToolRecord,
    OldToolRecord,
    OldToolPhoto,
    WearTypeDict,
    AbnormalCauseDict,
    ShieldMachineBasicInfo,
    CutterPositionInfo,
    CutterModelMapping,
    CutterImageAnnotation,
    StratumBasicInfo,
    ShieldTunnelingData,
    ToolLifePrediction,
    TOOL_TYPES,
    NEW_RING_TYPE_CHOICES,
    NEW_COMPONENT_CONDITION_CHOICES,
    BEARING_FAILURE_REASON_CHOICES,
    HUB_FAILURE_REASON_CHOICES,
    RING_DAMAGE_CHOICES,
    OLD_TOOL_DISPOSITION_CHOICES,
    BLADE_WEAR_DESCRIPTION_CHOICES,
)
from .cutter_position_scope import is_active_cutter_position, sort_cutter_position_items
from .trajectory import get_tool_trajectory
from .wear import wear_display


TUNNELING_SEGMENT_COUNT = 10


# ==================== 项目基本信息 ====================

def _ring_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_datetime(value):
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else None


def _decimal_to_float(value):
    return float(value) if value is not None else 0


def _join_repair_parts(value):
    if not value:
        return None
    if isinstance(value, list):
        return ', '.join([str(item) for item in value if item])
    return str(value)


def _normalize_wear_condition(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    upper = raw.upper()
    if upper in {'GOOD', 'NORMAL', 'MODERATE', 'SEVERE', 'ABNORMAL'}:
        return upper

    severe_words = [
        '\u4e25\u91cd', '\u5d29\u5203', '\u8131\u843d', '\u6f0f\u6cb9',
        '\u8f74\u627f\u635f\u574f', '\u65ad\u88c2',
    ]
    if any(word in raw for word in severe_words):
        return 'SEVERE'
    if any(word in raw for word in ['\u4e2d\u5ea6', '\u4e2d\u7b49']):
        return 'MODERATE'
    if any(word in raw for word in ['\u504f\u78e8', '\u5f02\u5e38']):
        return 'ABNORMAL'
    if '\u826f\u597d' in raw:
        return 'GOOD'
    if '\u6b63\u5e38' in raw:
        return 'NORMAL'
    return 'UNKNOWN'


def _wear_condition_label(value):
    normalized = _normalize_wear_condition(value)
    label_map = {
        'GOOD': '\u826f\u597d',
        'NORMAL': '\u6b63\u5e38\u78e8\u635f',
        'MODERATE': '\u4e2d\u5ea6\u78e8\u635f',
        'SEVERE': '\u4e25\u91cd\u78e8\u635f',
        'ABNORMAL': '\u5f02\u5e38\u78e8\u635f',
        'UNKNOWN': '\u672a\u77e5',
    }
    return label_map.get(normalized, value or '-')


def _replacement_type_label(value):
    label_map = {
        'COMPLETE': '\u6574\u5200\u66f4\u6362',
        'REPAIR': '\u7ef4\u4fee',
    }
    return label_map.get(value, value or '-')


def _tool_name_from_record(record, cutter_position=None):
    if cutter_position and cutter_position.tool_info and cutter_position.tool_info.tool_type_name:
        return cutter_position.tool_info.tool_type_name
    return record.tool_parent_type if record and record.tool_parent_type else ''


def _tool_info_from_position(cutter_position):
    if cutter_position and cutter_position.tool_info:
        return cutter_position.tool_info
    return None


def _normalize_cutter_no(value):
    raw = str(value or '').strip()
    if not raw:
        return ''
    upper = raw.upper()
    return str(int(upper)) if upper.isdigit() else upper


def _parse_xml_record_time(value):
    if not value:
        return None
    text = str(value).strip().replace('/', '-')
    parsed = parse_datetime(text)
    if parsed is None:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y%m%d %H:%M:%S', '%Y%m%d %H:%M'):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _read_tunneling_xml(path):
    tree = ET.parse(path)
    params = {}
    record_time = None
    for item in tree.getroot():
        key = str(item.tag or '').strip()
        text = str(item.text or '').strip()
        if not key or text == '':
            continue
        if key.lower() == 'time':
            record_time = _parse_xml_record_time(text)
            continue
        value = _parse_float(text)
        if value is not None:
            params[key] = value
    return params, record_time


# XML 里可能承载环号的标签名（归一化后比较：去下划线/连字符/空格、转小写）
_RING_TAG_CANDIDATES = {
    'ringno', 'ring', 'ringnumber', 'ringnum', 'ringindex',
    'currentring', 'nowring', 'segmentring',
    '环号', '管片环号', '当前环号', '环', '掘进环号',
}


def _detect_ring_from_params(params):
    """从 XML 解析结果里识别真实环号；识别不到返回 None。"""
    for key, value in (params or {}).items():
        norm = str(key).strip().lower().replace('-', '').replace('_', '').replace(' ', '')
        if norm in _RING_TAG_CANDIDATES:
            ring = _ring_int(value)
            if ring is not None and ring > 0:
                return ring
    return None


def _xml_files(folder_path):
    files = []
    for root, _, names in os.walk(folder_path):
        for name in names:
            if name.lower().endswith('.xml'):
                path = os.path.join(root, name)
                files.append((os.path.getmtime(path), path))
    return [path for _, path in sorted(files, key=lambda item: (item[0], item[1]))]


def _average_xml_records(records):
    totals = {}
    counts = {}
    for params, _record_time, _path in records:
        for key, value in params.items():
            totals[key] = totals.get(key, 0) + value
            counts[key] = counts.get(key, 0) + 1
    return {key: round(totals[key] / counts[key], 6) for key in totals if counts.get(key)}


def _xml_record_time(record):
    params, record_time, path = record
    if record_time:
        return record_time
    return timezone.make_aware(
        datetime.fromtimestamp(os.path.getmtime(path)),
        timezone.get_current_timezone(),
    )


def _safe_segment_count(value, default=TUNNELING_SEGMENT_COUNT):
    try:
        count = int(value or default)
    except (TypeError, ValueError):
        count = default
    return max(1, min(count, 100))


def _split_records_into_time_segments(records, segment_count, time_getter):
    if not records:
        return []

    segment_count = _safe_segment_count(segment_count)
    ordered = list(records)
    timed = [(record, time_getter(record)) for record in ordered if time_getter(record)]
    if timed:
        ordered = [record for record, _time in sorted(timed, key=lambda item: item[1])]
    else:
        ordered = list(records)

    total = len(ordered)
    actual_segments = min(segment_count, total)
    segments = []
    for index in range(actual_segments):
        start = round(index * total / actual_segments)
        end = round((index + 1) * total / actual_segments)
        bucket = ordered[start:end]
        if bucket:
            segments.append((index + 1, bucket))
    return segments


def _segment_metadata(records, segment_index, segment_count, time_getter):
    times = [time_getter(record) for record in records if time_getter(record)]
    start_time = min(times) if times else None
    end_time = max(times) if times else None
    duration_seconds = None
    if start_time and end_time:
        duration_seconds = round((end_time - start_time).total_seconds(), 3)
    return {
        "segment_index": segment_index,
        "segment_count": segment_count,
        "point_count": len(records),
        "start_time": _format_datetime(start_time),
        "end_time": _format_datetime(end_time),
        "duration_seconds": duration_seconds,
    }


def _next_tunneling_ring_no(project):
    max_ring = 0
    for row in ShieldTunnelingData.objects.filter(project=project).values('ring_no'):
        ring = _ring_int(row.get('ring_no'))
        if ring is not None and ring > max_ring:
            max_ring = ring
    return max_ring + 1


class ProjectInfoSerializer(CustomModelSerializer):
    """
    项目基本信息-序列化器
    """
    class Meta:
        model = ProjectInfo
        fields = '__all__'
        read_only_fields = ["id"]


class ProjectInfoCreateUpdateSerializer(CustomModelSerializer):
    """
    项目基本信息 创建/更新时的序列化器
    """
    class Meta:
        model = ProjectInfo
        fields = '__all__'


class ProjectInfoViewSet(CustomModelViewSet):
    """
    项目基本信息接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = ProjectInfo.objects.all()
    serializer_class = ProjectInfoSerializer
    create_serializer_class = ProjectInfoCreateUpdateSerializer
    update_serializer_class = ProjectInfoCreateUpdateSerializer
    filter_fields = ['project_id', 'project_name', 'location']
    search_fields = ['project_id', 'project_name', 'location']

    @action(detail=True, methods=['post'])
    def import_tunneling_xml(self, request, pk=None):
        project = self.get_object()
        folder_path = str(request.data.get('folder_path') or '').strip()
        shield_machine_id = request.data.get('shield_machine')
        try:
            files_per_ring = int(request.data.get('files_per_ring') or 10)
        except (TypeError, ValueError):
            return ErrorResponse(msg='每环采样点数必须是数字')
        segment_count = _safe_segment_count(request.data.get('segment_count'))
        start_ring_no = request.data.get('start_ring_no')
        overwrite = str(request.data.get('overwrite', 'true')).lower() in {'true', '1', 'yes'}
        import_incomplete = str(request.data.get('import_incomplete', 'false')).lower() in {'true', '1', 'yes'}

        if not folder_path:
            return ErrorResponse(msg='请填写共享文件夹路径')
        if not os.path.isdir(folder_path):
            return ErrorResponse(msg='共享文件夹不存在或服务器无权访问')
        if not shield_machine_id:
            return ErrorResponse(msg='请选择盾构机')
        if files_per_ring <= 0:
            return ErrorResponse(msg='每环采样点数必须大于0')

        shield_machine = ShieldMachineBasicInfo.objects.filter(id=shield_machine_id).first()
        if not shield_machine:
            return ErrorResponse(msg='盾构机不存在')

        if start_ring_no in (None, ''):
            ring_no = _next_tunneling_ring_no(project)
        else:
            ring_no = _ring_int(start_ring_no)
            if ring_no is None:
                return ErrorResponse(msg='起始环号必须是数字')

        parsed_records = []
        skipped_files = 0
        ring_by_path = {}
        for path in _xml_files(folder_path):
            try:
                params, record_time = _read_tunneling_xml(path)
            except (ET.ParseError, OSError, UnicodeDecodeError, ValueError):
                skipped_files += 1
                continue
            if not params:
                skipped_files += 1
                continue
            # 优先读 XML 内部的环号，其次从文件名解析
            detected = _detect_ring_from_params(params)
            if detected is None:
                name_ring = _extract_ring_no_from_filename(path)
                detected = _ring_int(name_ring) if name_ring else None
            if detected is not None:
                ring_by_path[path] = detected
            parsed_records.append((params, record_time, path))

        if not parsed_records:
            return ErrorResponse(msg='未读取到有效XML工程数据')
        parsed_records.sort(key=lambda item: (
            item[1] or timezone.make_aware(
                datetime.fromtimestamp(os.path.getmtime(item[2])),
                timezone.get_current_timezone(),
            ),
            item[2],
        ))

        created = 0
        deleted = 0
        skipped_rings = 0
        # 环号来源：只要所有文件都能读出真实环号，就按真实环号分组。
        # 旧实现一律"按文件顺序每 N 个一环、ring_no += 1"，从不读 XML 里的环号——
        # 中间只要跳过一个损坏文件，之后每一组都整体前移一环，而且默认 overwrite
        # 会先把本该正确的旧数据删掉再写错的，错误一路累积到最后一环。
        use_detected = bool(ring_by_path) and len(ring_by_path) == len(parsed_records)
        if use_detected:
            grouped = {}
            for record in parsed_records:
                grouped.setdefault(ring_by_path[record[2]], []).append(record)
            groups = [(detected, grouped[detected]) for detected in sorted(grouped)]
        else:
            groups = [
                (None, parsed_records[index:index + files_per_ring])
                for index in range(0, len(parsed_records), files_per_ring)
            ]
        # 整批导入放进事务：原实现无事务，中途失败会留下 旧数据已删除、新数据没写全 的半截状态。
        with transaction.atomic():
            for detected_ring, group in groups:
                if len(group) < files_per_ring and not import_incomplete:
                    skipped_rings += 1
                    continue

                current_ring = detected_ring if detected_ring is not None else ring_no
                existing = ShieldTunnelingData.objects.filter(
                    project=project,
                    shield_machine=shield_machine,
                    ring_no=str(current_ring),
                )
                if existing:
                    if overwrite:
                        removed, _ = existing.delete()
                        deleted += removed
                    else:
                        skipped_rings += 1
                        if detected_ring is None:
                            ring_no += 1
                        continue

                records = []
                segments = _split_records_into_time_segments(group, segment_count, _xml_record_time)
                for segment_index, segment in segments:
                    averaged = _average_xml_records(segment)
                    record_times = [_xml_record_time(item) for item in segment]
                    record_time = max(record_times) if record_times else None
                    averaged.update(_segment_metadata(segment, segment_index, segment_count, _xml_record_time))
                    records.append(ShieldTunnelingData(
                        project=project,
                        shield_machine=shield_machine,
                        ring_no=str(current_ring),
                        thrust=None,
                        torque=None,
                        cutterhead_speed=None,
                        penetration=None,
                        record_time=record_time,
                        raw_parameters=averaged,
                        point_count=len(segment),
                        import_source=folder_path,
                        remark=f'XML共享文件夹按时间分段导入：第{segment_index}/{segment_count}段',
                    ))
                if records:
                    ShieldTunnelingData.objects.bulk_create(records, batch_size=1000)
                    created += len(records)
                else:
                    skipped_rings += 1
                if detected_ring is None:
                    ring_no += 1

        return SuccessResponse(
            data={
                'created': created,
                'deleted': deleted,
                'skipped_files': skipped_files,
                'skipped_rings': skipped_rings,
                # 告诉调用方环号是"读出来的"还是"按文件顺序推算的"
                'ring_source': 'detected' if use_detected else 'positional',
                'ring_detected_files': len(ring_by_path),
                'parsed_points': len(parsed_records),
                'files_per_ring': files_per_ring,
                'segment_count': segment_count,
            },
            msg=f'导入完成，新增{created}条分段掘进记录，覆盖{len(groups) - skipped_rings}个环号',
        )


# ==================== 刀具基本信息 ====================

class ToolCategorySerializer(CustomModelSerializer):
    """
    刀具基本信息-序列化器
    """
    tool_type_display = serializers.CharField(read_only=True, source='get_tool_type_display')
    shield_machine_model = serializers.CharField(read_only=True, source='shield_machine.shield_model')

    class Meta:
        model = ToolCategory
        fields = '__all__'
        read_only_fields = ["id", "tool_number"]  # tool_number 自动生成，但可修改

class ToolCategoryCreateUpdateSerializer(CustomModelSerializer):
    """
    刀具基本信息 创建/更新时的序列化器
    """
    class Meta:
        model = ToolCategory
        fields = '__all__'


class ToolCategoryViewSet(CustomModelViewSet):
    """
    刀具基本信息接口
    list:查询
    create:新增（自动生成编号）
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = ToolCategory.objects.all()
    serializer_class = ToolCategorySerializer
    create_serializer_class = ToolCategoryCreateUpdateSerializer
    update_serializer_class = ToolCategoryCreateUpdateSerializer
    filter_fields = ['tool_type']
    search_fields = ['tool_name', 'tool_number', 'cutter_position_no']

    def filter_queryset(self, queryset):
        """自定义过滤，支持按字段名模糊搜索。"""
        queryset = super().filter_queryset(queryset)

        # 支持按字段名进行模糊搜索
        tool_name = self.request.query_params.get('tool_name', None)
        tool_number = self.request.query_params.get('tool_number', None)
        cutter_position_no = self.request.query_params.get('cutter_position_no', None)

        if tool_name:
            queryset = queryset.filter(tool_name__icontains=tool_name)
        if tool_number:
            queryset = queryset.filter(tool_number__icontains=tool_number)
        if cutter_position_no:
            queryset = queryset.filter(cutter_position_no__icontains=cutter_position_no)

        return queryset

    @action(detail=False, methods=['post'])
    def generate_number(self, request):
        """生成刀具编号预览"""
        tool_type = request.data.get('tool_type')
        if not tool_type:
            return DetailResponse(msg="请提供刀具类型", success=False)

        temp_tool = ToolCategory(tool_type=tool_type)
        number = temp_tool.generate_tool_number()
        return SuccessResponse(data={'tool_number': number})

    @action(detail=False, methods=['get'])
    def get_cutter_positions(self, request):
        """获取所有已录入的刀位号列表"""
        # 修正：刀位号在 CutterPositionInfo 上，ShieldMachineBasicInfo 只有 shield_model(_id)。
        # 原写法必然抛 FieldError，该接口从未可用。
        positions = CutterPositionInfo.objects.values_list('cutter_position_no', flat=True).distinct()
        positions = [
            pos for pos in positions
            if pos and is_active_cutter_position(pos)
        ]
        result = [{'value': pos, 'label': pos} for pos in positions]
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def get_tool_numbers(self, request):
        """获取所有已录入的刀具编号列表"""
        tool_numbers = ToolCategory.objects.filter(
            tool_number__isnull=False
        ).exclude(
            tool_number=''
        ).values('tool_number').distinct()

        # 转换为刀具编号列表（value 和 label 都使用刀具编号）
        result = [
            {
                'value': tool['tool_number'],
                'label': tool['tool_number']
            }
            for tool in tool_numbers
        ]
        return SuccessResponse(data=result)


# ==================== 刀具成本信息 ====================

class ToolCostSerializer(CustomModelSerializer):
    """
    刀具成本信息-序列化器
    """
    cost_type_display = serializers.CharField(read_only=True, source='get_cost_type_display')
    tool_info_name = serializers.CharField(read_only=True, source='tool_info.tool_type_name')
    tool_info_number = serializers.CharField(read_only=True, source='tool_info.tool_number')

    class Meta:
        model = ToolCost
        fields = '__all__'
        read_only_fields = ["id"]


class ToolCostCreateUpdateSerializer(CustomModelSerializer):
    """
    刀具成本信息 创建/更新时的序列化器
    """
    class Meta:
        model = ToolCost
        fields = '__all__'

    def validate(self, attrs):
        cost_type = attrs.get('cost_type')
        repair_parts = attrs.get('repair_parts', [])

        if cost_type == 'REPAIR' and not repair_parts:
            raise serializers.ValidationError({
                'repair_parts': '维修类型必须选择维修部位'
            })

        return attrs


class ToolCostViewSet(CustomModelViewSet):
    """
    刀具成本信息接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = ToolCost.objects.all()
    serializer_class = ToolCostSerializer
    create_serializer_class = ToolCostCreateUpdateSerializer
    update_serializer_class = ToolCostCreateUpdateSerializer
    filter_fields = ['tool_info', 'cost_type']
    search_fields = ['brand', 'manufacturer']

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)

        tool_info_id = self.request.query_params.get('tool_info', None)
        if tool_info_id:
            queryset = queryset.filter(tool_info_id=tool_info_id)

        return queryset


# ==================== 刀具明细 ====================

class ShieldTunnelingDataSerializer(CustomModelSerializer):
    project_name = serializers.CharField(read_only=True, source='project.project_name')
    shield_machine_name = serializers.CharField(read_only=True, source='shield_machine.shield_model')

    class Meta:
        model = ShieldTunnelingData
        fields = '__all__'
        read_only_fields = ["id"]


class ShieldTunnelingDataCreateUpdateSerializer(CustomModelSerializer):
    class Meta:
        model = ShieldTunnelingData
        fields = '__all__'


def _normalize_csv_header(value):
    text = str(value or '').strip().replace('\ufeff', '')
    text = re.sub(r'^\[\d+\]', '', text).strip()
    return (
        text.replace('（', '(')
        .replace('）', ')')
        .replace(' ', '')
        .replace('\u3000', '')
        .lower()
    )


def _get_csv_value(row, aliases):
    normalized = {_normalize_csv_header(key): value for key, value in row.items()}
    normalized_aliases = [_normalize_csv_header(alias) for alias in aliases]
    for alias in aliases:
        if alias in row and str(row.get(alias, '')).strip() != '':
            return row.get(alias)
    for alias in normalized_aliases:
        if alias in normalized and str(normalized.get(alias, '')).strip() != '':
            return normalized.get(alias)
    for key, value in normalized.items():
        if any(alias and alias in key for alias in normalized_aliases) and str(value or '').strip() != '':
            return value
    return None


def _parse_float(value):
    if value is None:
        return None
    text = str(value).strip().replace(',', '')
    if not text or text in {'-', '--'}:
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group()) if match else None


def _parse_record_time(row):
    value = _get_csv_value(row, ['采集时间', '记录时间', 'record_time'])
    if not value:
        date_value = _get_csv_value(row, ['记录日期'])
        time_value = _get_csv_value(row, ['记录时刻'])
        value = f'{date_value or ""} {time_value or ""}'.strip()
    if not value:
        return None

    text = str(value).strip()
    normalized = (
        text.replace('年', '-')
        .replace('月', '-')
        .replace('日', ' ')
        .replace('时', ':')
        .replace('分', ':')
        .replace('秒', '')
        .replace('/', '-')
    )
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    parsed = parse_datetime(normalized)
    if parsed is None:
        parsed_date = parse_date(normalized)
        parsed = datetime.combine(parsed_date, datetime.min.time()) if parsed_date else None
    if parsed is None:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y%m%d %H:%M:%S', '%Y%m%d %H:%M'):
            try:
                parsed = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue
    if parsed and timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _extract_ring_no_from_filename(filename):
    stem = os.path.splitext(os.path.basename(str(filename or '')))[0]
    # 这四条原本写成 \\d / \\s（原始串里是"反斜杠+字母"），恒不匹配，
    # 导致带多个数字的文件名（如 TBM2_第100环.csv）一律取不到环号。
    for pattern in (
        r'0*(\d{1,6})\s*环',
        r'(?:第|^|[_\-\s])0*(\d{1,6})\s*环',
        r'环\s*号?\s*0*(\d{1,6})',
        r'(?i)(?:ring|r)\s*[_\-\s]*0*(\d{1,6})',
    ):
        match = re.search(pattern, stem)
        if match:
            return str(int(match.group(1)))

    numbers = re.findall(r'\d+', stem)
    candidates = [item for item in numbers if 1 <= len(item) <= 6]
    return str(int(candidates[-1])) if len(candidates) == 1 else None


def _build_tunneling_record(row, project_id, shield_machine_id, ring_no=None):
    ring_no = ring_no or _get_csv_value(row, ['环的编号(当前环)', '环的编号', '当前环', '环片号码', 'ring_no'])
    if ring_no is None or str(ring_no).strip() == '':
        return None

    return ShieldTunnelingData(
        project_id=project_id,
        shield_machine_id=shield_machine_id,
        ring_no=str(ring_no).strip(),
        thrust=_parse_float(_get_csv_value(row, ['推进油缸总推力(kN)', '推进油缸总推力', '总推力', '推力', 'thrust'])),
        torque=_parse_float(_get_csv_value(row, ['刀盘扭矩(kNm)', '刀盘扭矩', '总扭矩', '扭矩', 'torque'])),
        cutterhead_speed=_parse_float(_get_csv_value(row, ['刀盘转速(r/min)', '刀盘转速', '转速', 'cutterhead_speed'])),
        penetration=_parse_float(_get_csv_value(row, ['贯入度(mm)', '贯入度', '贯入力', 'penetration'])),
        record_time=_parse_record_time(row),
    )


def _average_tunneling_records(records, import_source='', segment_index=None, segment_count=None):
    base = records[0]
    metadata = {}
    if segment_index and segment_count:
        metadata = _segment_metadata(records, segment_index, segment_count, lambda item: item.record_time)
    averaged = ShieldTunnelingData(
        project_id=base.project_id,
        shield_machine_id=base.shield_machine_id,
        ring_no=base.ring_no,
        point_count=len(records),
        import_source=import_source,
        raw_parameters=metadata,
        remark=(
            f'CSV按时间分段导入：第{segment_index}/{segment_count}段'
            if segment_index and segment_count else 'CSV按环平均导入'
        ),
    )
    for field in ('thrust', 'torque', 'cutterhead_speed', 'penetration'):
        values = [getattr(record, field) for record in records if getattr(record, field) is not None]
        setattr(averaged, field, round(sum(values) / len(values), 4) if values else None)

    times = [record.record_time for record in records if record.record_time]
    averaged.record_time = max(times) if times else None
    return averaged


class ShieldTunnelingDataViewSet(CustomModelViewSet):
    queryset = ShieldTunnelingData.objects.select_related('project', 'shield_machine').all()
    serializer_class = ShieldTunnelingDataSerializer
    create_serializer_class = ShieldTunnelingDataCreateUpdateSerializer
    update_serializer_class = ShieldTunnelingDataCreateUpdateSerializer
    filter_fields = ['project', 'shield_machine', 'ring_no']
    search_fields = ['ring_no', 'remark']

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        upload_file = request.FILES.get('file')
        project_id = request.data.get('project')
        shield_machine_id = request.data.get('shield_machine')
        segment_count = _safe_segment_count(request.data.get('segment_count'))
        if not upload_file:
            return ErrorResponse(msg='请上传CSV文件')
        if not project_id or not shield_machine_id:
            return ErrorResponse(msg='请选择项目和盾构机')

        raw = upload_file.read()
        text = None
        for encoding in ('utf-8-sig', 'gbk', 'gb18030'):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return ErrorResponse(msg='CSV编码无法识别，请使用UTF-8或GBK编码')

        reader = csv.DictReader(io.StringIO(text))
        filename_ring_no = _extract_ring_no_from_filename(upload_file.name)
        grouped_records = {}
        skipped = 0
        for row in reader:
            record = _build_tunneling_record(row, project_id, shield_machine_id, ring_no=filename_ring_no)
            if record is None:
                skipped += 1
                continue
            grouped_records.setdefault(record.ring_no, []).append(record)

        if not grouped_records:
            return ErrorResponse(msg='未读取到有效掘进动态数据，请检查CSV表头和内容')

        records = []
        for group in grouped_records.values():
            segments = _split_records_into_time_segments(group, segment_count, lambda item: item.record_time)
            records.extend([
                _average_tunneling_records(
                    segment,
                    import_source=upload_file.name,
                    segment_index=segment_index,
                    segment_count=segment_count,
                )
                for segment_index, segment in segments
            ])
        # 重复导入保护：同一(项目,盾构机,环号)已有数据时，按 overwrite 决定
        # 覆盖还是跳过。原实现直接 bulk_create，重点一次导入就让该环数据翻倍，
        # 平均推力/扭矩被重复点稀释。与 XML 导入保持同一套语义。
        overwrite = str(request.data.get('overwrite', 'true')).lower() not in ('false', '0', 'no')
        ring_nos = {record.ring_no for record in records if record.ring_no}
        existing_scope = ShieldTunnelingData.objects.filter(
            project_id=project_id, shield_machine_id=shield_machine_id, ring_no__in=ring_nos
        )
        existing_rings = set(existing_scope.values_list('ring_no', flat=True))
        skipped_rings = []
        with transaction.atomic():
            if existing_rings:
                if overwrite:
                    existing_scope.delete()
                else:
                    skipped_rings = sorted(existing_rings)
                    records = [r for r in records if r.ring_no not in existing_rings]
            ShieldTunnelingData.objects.bulk_create(records, batch_size=1000)
        return SuccessResponse(
            data={
                'created': len(records),
                'overwrite': overwrite,
                'skipped_rings': skipped_rings,
                'source_rows': sum(len(group) for group in grouped_records.values()),
                'ring_count': len(grouped_records),
                'segment_count': segment_count,
                'skipped': skipped,
            },
            msg=f'导入成功，新增{len(records)}条分段掘进记录，覆盖{len(grouped_records)}个环号，跳过{skipped}行',
        )


class ToolLifePredictionSerializer(CustomModelSerializer):
    tool_type_name = serializers.CharField(read_only=True, source='tool_info.tool_type_name')
    tool_type_code = serializers.CharField(read_only=True, source='tool_info.tool_type_code')

    class Meta:
        model = ToolLifePrediction
        fields = '__all__'
        read_only_fields = ["id", "tool_number"]


class ToolLifePredictionCreateUpdateSerializer(CustomModelSerializer):
    class Meta:
        model = ToolLifePrediction
        fields = '__all__'
        read_only_fields = ["tool_number"]


class ToolLifePredictionViewSet(CustomModelViewSet):
    queryset = ToolLifePrediction.objects.select_related('tool_info').all()
    serializer_class = ToolLifePredictionSerializer
    create_serializer_class = ToolLifePredictionCreateUpdateSerializer
    update_serializer_class = ToolLifePredictionCreateUpdateSerializer
    filter_fields = ['tool_info', 'tool_number', 'future_stratum_type']
    search_fields = ['tool_number', 'future_stratum_type', 'remark']


class ToolInfoSerializer(CustomModelSerializer):
    """
    刀具明细-序列化器
    """
    tool_parent_type_display = serializers.CharField(read_only=True, source='get_tool_parent_type_display')
    shield_machine_model = serializers.CharField(read_only=True, source='shield_machine.shield_model')

    class Meta:
        model = ToolInfo
        fields = '__all__'
        read_only_fields = ["id", "tool_type_code", "tool_number"]


class ToolInfoCreateUpdateSerializer(CustomModelSerializer):
    """
    刀具明细 创建/更新时的序列化器
    """
    class Meta:
        model = ToolInfo
        fields = '__all__'
        read_only_fields = ["tool_type_code", "tool_number"]


class ToolInfoViewSet(CustomModelViewSet):
    """
    刀具明细接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = ToolInfo.objects.all()
    serializer_class = ToolInfoSerializer
    create_serializer_class = ToolInfoCreateUpdateSerializer
    update_serializer_class = ToolInfoCreateUpdateSerializer
    filter_fields = ['tool_parent_type', 'shield_machine']
    search_fields = ['tool_type_name', 'tool_type_code', 'tool_number']

    def filter_queryset(self, queryset):
        """自定义过滤，支持按字段名模糊搜索。"""
        queryset = super().filter_queryset(queryset)

        # 支持按字段名进行模糊搜索
        tool_type_name = self.request.query_params.get('tool_type_name', None)
        tool_type_code = self.request.query_params.get('tool_type_code', None)

        if tool_type_name:
            queryset = queryset.filter(tool_type_name__icontains=tool_type_name)
        if tool_type_code:
            queryset = queryset.filter(tool_type_code__icontains=tool_type_code)

        return queryset


# ==================== 换刀基本信息管理 ====================

def _stratum_name_map(codes):
    """批量解析地层编码；字典未配置时回退显示编码，避免数据被静默丢弃。"""
    from dvadmin.system.models import Dictionary

    unique_codes = list(dict.fromkeys(code for code in codes if code))
    items = Dictionary.objects.filter(
        parent__value='stratum_type',
        value__in=unique_codes,
        status=True,
    ).values('value', 'label')
    labels = {item['value']: item['label'] for item in items}
    return {code: labels.get(code, code) for code in unique_codes}


def _build_opening_stratum_context(project_id, ring_no, shield_model_id=None, opening_id=None):
    """根据项目、盾构机和环号生成开仓间隔及地层只读快照。"""
    current_ring = _ring_int(ring_no)
    empty_result = {
        'last_ring_no': None,
        'rings_between_openings': None,
        'stratum_info_between': {},
        'stratum_info_between_list': [],
        'geological_conditions': '',
    }
    if not project_id or current_ring is None:
        return empty_result

    openings = WarehouseOpeningBasicInfo.objects.filter(project_id=project_id)
    if shield_model_id:
        openings = openings.filter(shield_model_id=shield_model_id)
    if opening_id:
        openings = openings.exclude(id=opening_id)
    previous = (
        openings.annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
        .filter(ring_int__lt=current_ring)
        .order_by('-ring_int')
        .values('ring_no', 'ring_int')
        .first()
    )

    last_ring = previous['ring_int'] if previous else None
    stratum_counts = {}
    current_stratum = None
    stratum_rows = StratumBasicInfo.objects.filter(project_id=project_id).values(
        'ring_no', 'stratum_type_codes', 'stratum_info', 'burial_depth'
    )
    for row in stratum_rows:
        row_ring = _ring_int(row['ring_no'])
        if row_ring is None:
            continue
        codes = [code.strip() for code in (row['stratum_type_codes'] or '').split(',') if code.strip()]
        if last_ring is not None and last_ring < row_ring <= current_ring:
            for code in codes:
                stratum_counts[code] = stratum_counts.get(code, 0) + 1
        if row_ring == current_ring:
            current_stratum = {**row, 'codes': codes}

    all_codes = list(stratum_counts)
    if current_stratum:
        all_codes.extend(current_stratum['codes'])
    name_map = _stratum_name_map(all_codes)
    between_list = [
        {
            'stratum_type_code': code,
            'stratum_type_name': name_map.get(code, code),
            'ring_count': count,
        }
        for code, count in stratum_counts.items()
    ]

    geological_parts = []
    if current_stratum:
        type_names = [name_map.get(code, code) for code in current_stratum['codes']]
        if type_names:
            geological_parts.append('、'.join(type_names))
        stratum_info = (current_stratum['stratum_info'] or '').strip()
        if stratum_info and stratum_info not in geological_parts:
            geological_parts.append(stratum_info)
        if current_stratum['burial_depth'] is not None:
            geological_parts.append(f"埋深 {current_stratum['burial_depth']:g} m")

    return {
        'last_ring_no': previous['ring_no'] if previous else None,
        'rings_between_openings': current_ring - last_ring if last_ring is not None else current_ring,
        'stratum_info_between': stratum_counts,
        'stratum_info_between_list': between_list,
        'geological_conditions': '；'.join(geological_parts),
    }


class WarehouseOpeningBasicInfoSerializer(CustomModelSerializer):
    """
    换刀基本信息-序列化器
    """
    project_name = serializers.CharField(read_only=True, source='project.project_name')
    shield_model_name = serializers.CharField(read_only=True, source='shield_model.shield_model')
    stratum_info_between_list = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WarehouseOpeningBasicInfo
        fields = '__all__'
        read_only_fields = ["id", "warehouse_id", "last_ring_no", "rings_between_openings"]

    def get_stratum_info_between_list(self, obj):
        """获取两次开仓间地层信息的详细列表。"""
        if not obj.stratum_info_between:
            return []

        name_map = _stratum_name_map(obj.stratum_info_between.keys())
        return [
            {
                'stratum_type_code': code,
                'stratum_type_name': name_map.get(code, code),
                'ring_count': ring_count,
            }
            for code, ring_count in obj.stratum_info_between.items()
        ]


class WarehouseOpeningBasicInfoCreateUpdateSerializer(CustomModelSerializer):
    """换刀基本信息创建/更新序列化器"""
    stratum_info_between_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text="兼容旧客户端保留；服务端会忽略该字段并自动生成地层信息"
    )

    class Meta:
        model = WarehouseOpeningBasicInfo
        fields = '__all__'
        read_only_fields = [
            "id", "warehouse_id", "last_ring_no", "rings_between_openings",
            "stratum_info_between", "geological_conditions",
        ]

    @staticmethod
    def _apply_auto_stratum_info(instance):
        auto_data = _build_opening_stratum_context(
            instance.project_id,
            instance.ring_no,
            instance.shield_model_id,
            instance.id,
        )
        update_fields = []
        for field in ('stratum_info_between', 'geological_conditions'):
            if getattr(instance, field) != auto_data[field]:
                setattr(instance, field, auto_data[field])
                update_fields.append(field)
        if update_fields:
            instance.save(update_fields=update_fields)
        return instance

    def create(self, validated_data):
        validated_data.pop('stratum_info_between_data', None)
        instance = super().create(validated_data)
        return self._apply_auto_stratum_info(instance)

    def update(self, instance, validated_data):
        validated_data.pop('stratum_info_between_data', None)
        instance = super().update(instance, validated_data)
        return self._apply_auto_stratum_info(instance)


class WarehouseOpeningBasicInfoViewSet(CustomModelViewSet):
    """换刀基本信息管理接口"""
    queryset = WarehouseOpeningBasicInfo.objects.annotate(
        ring_int=Cast('ring_no', output_field=IntegerField())
    ).order_by('ring_int')
    serializer_class = WarehouseOpeningBasicInfoSerializer
    create_serializer_class = WarehouseOpeningBasicInfoCreateUpdateSerializer
    update_serializer_class = WarehouseOpeningBasicInfoCreateUpdateSerializer
    filter_fields = ['warehouse_id', 'project', 'ring_no', 'shield_model']
    search_fields = ['warehouse_id', 'ring_no']

    @action(methods=['get'], detail=False, url_path='auto_stratum_preview',
            permission_classes=[AnonymousUserPermission])
    def auto_stratum_preview(self, request):
        """录入表单联动预览：只读取地层基础信息，不接受手工地层值。"""
        project_id = request.query_params.get('project')
        ring_no = request.query_params.get('ring_no')
        shield_model_id = request.query_params.get('shield_model') or None
        opening_id = request.query_params.get('opening_id') or None
        try:
            project_id = int(project_id)
            shield_model_id = int(shield_model_id) if shield_model_id else None
            opening_id = int(opening_id) if opening_id else None
        except (TypeError, ValueError):
            return ErrorResponse(msg='请选择项目并输入有效的换刀环号')
        if _ring_int(ring_no) is None or not ProjectInfo.objects.filter(id=project_id).exists():
            return ErrorResponse(msg='请选择项目并输入有效的换刀环号')
        data = _build_opening_stratum_context(
            project_id,
            ring_no,
            shield_model_id,
            opening_id,
        )
        return SuccessResponse(data=data)

    @action(methods=['get'], detail=False, url_path='stratum_type_options',
            permission_classes=[AnonymousUserPermission])  # 任何登录用户可用，绕过按钮级权限
    def stratum_type_options(self, request):
        """获取最近两次开仓的地层类型选项。"""
        from dvadmin.system.models import Dictionary

        all_openings = list(
            WarehouseOpeningBasicInfo.objects.values('ring_no', 'stratum_info_between')
        )

        # 按 ring_no 数值排序，取最近两条
        valid_openings = []
        for opening in all_openings:
            try:
                ring = int(opening['ring_no'])
                valid_openings.append((ring, opening.get('stratum_info_between') or {}))
            except (ValueError, TypeError):
                continue
        valid_openings.sort(key=lambda x: x[0], reverse=True)
        recent_two = valid_openings[:2]

        # 收集地层类型编码（保持顺序去重）
        seen = set()
        stratum_codes = []
        for _, stratum_info in recent_two:
            for code in stratum_info.keys():
                if code not in seen:
                    seen.add(code)
                    stratum_codes.append(code)

        # 从字典获取名称
        options = []
        for code in stratum_codes:
            try:
                dict_item = Dictionary.objects.filter(
                    parent__value='stratum_type',
                    value=code,
                    status=True
                ).first()
                if dict_item:
                    options.append({'label': dict_item.label, 'value': dict_item.label})
            except Exception:
                pass

        return SuccessResponse(options)


# ==================== 磨损类型字典管理 ====================

class WearTypeDictSerializer(CustomModelSerializer):
    """
    磨损类型字典-序列化器
    """
    class Meta:
        model = WearTypeDict
        fields = '__all__'
        read_only_fields = ["id"]


class WearTypeDictCreateUpdateSerializer(CustomModelSerializer):
    """
    磨损类型字典管理 创建/更新时的序列化器
    """
    class Meta:
        model = WearTypeDict
        fields = '__all__'


class WearTypeDictViewSet(CustomModelViewSet):
    """
    磨损类型字典管理接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = WearTypeDict.objects.all()
    serializer_class = WearTypeDictSerializer
    create_serializer_class = WearTypeDictCreateUpdateSerializer
    update_serializer_class = WearTypeDictCreateUpdateSerializer
    filter_fields = ['wear_type_name', 'wear_type_code']
    search_fields = ['wear_type_name', 'wear_type_code']


# ==================== 异常原因字典管理 ====================

class AbnormalCauseDictSerializer(CustomModelSerializer):
    """
    异常原因字典-序列化器
    """
    class Meta:
        model = AbnormalCauseDict
        fields = '__all__'
        read_only_fields = ["id"]


class AbnormalCauseDictCreateUpdateSerializer(CustomModelSerializer):
    """
    异常原因字典管理 创建/更新时的序列化器
    """
    class Meta:
        model = AbnormalCauseDict
        fields = '__all__'


class AbnormalCauseDictViewSet(CustomModelViewSet):
    """
    异常原因字典管理接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = AbnormalCauseDict.objects.all()
    serializer_class = AbnormalCauseDictSerializer
    create_serializer_class = AbnormalCauseDictCreateUpdateSerializer
    update_serializer_class = AbnormalCauseDictCreateUpdateSerializer
    filter_fields = ['cause_name', 'cause_code']
    search_fields = ['cause_name', 'cause_code']


# ==================== 盾构机基本信息管理 ====================

class ShieldMachineBasicInfoSerializer(CustomModelSerializer):
    """
    盾构机基本信息-序列化器
    """
    class Meta:
        model = ShieldMachineBasicInfo
        fields = '__all__'
        read_only_fields = ["id"]


class ShieldMachineBasicInfoCreateUpdateSerializer(CustomModelSerializer):
    """
    盾构机基本信息管理 创建/更新时的序列化器
    """
    class Meta:
        model = ShieldMachineBasicInfo
        fields = '__all__'


class ShieldMachineBasicInfoViewSet(CustomModelViewSet):
    """
    盾构机基本信息管理接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = ShieldMachineBasicInfo.objects.all()
    serializer_class = ShieldMachineBasicInfoSerializer
    create_serializer_class = ShieldMachineBasicInfoCreateUpdateSerializer
    update_serializer_class = ShieldMachineBasicInfoCreateUpdateSerializer
    filter_fields = ['shield_model_id', 'shield_model']
    search_fields = ['shield_model_id', 'shield_model']


# ==================== 刀位信息管理 ====================

class CutterPositionInfoSerializer(CustomModelSerializer):
    """
    刀位信息-序列化器
    """
    tool_type_display = serializers.CharField(read_only=True, source='get_tool_type_display')
    shield_model_id = serializers.CharField(read_only=True, source='shield_machine.shield_model_id')
    shield_model = serializers.CharField(read_only=True, source='shield_machine.shield_model')

    # 刀具类型相关字段（从 tool_info 获取）
    tool_parent_type = serializers.CharField(read_only=True, source='tool_info.tool_parent_type')
    tool_type_name = serializers.CharField(read_only=True, source='tool_info.tool_type_name')
    tool_type_code = serializers.CharField(read_only=True, source='tool_info.tool_type_code')

    class Meta:
        model = CutterPositionInfo
        fields = '__all__'
        read_only_fields = ["id", "tool_type"]  # tool_type 自动从 tool_info 同步


class CutterPositionInfoCreateUpdateSerializer(CustomModelSerializer):
    """
    刀位信息 创建/更新时的序列化器
    """
    class Meta:
        model = CutterPositionInfo
        fields = '__all__'


class CutterPositionInfoViewSet(CustomModelViewSet):
    """
    刀位信息管理接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    """
    queryset = CutterPositionInfo.objects.select_related('shield_machine', 'tool_info').all()
    serializer_class = CutterPositionInfoSerializer
    create_serializer_class = CutterPositionInfoCreateUpdateSerializer
    update_serializer_class = CutterPositionInfoCreateUpdateSerializer
    filter_fields = ['shield_machine', 'tool_type', 'cutter_position_no']
    search_fields = ['cutter_position_no']

    def list(self, request, *args, **kwargs):
        """重写 list 方法，在分页前进行智能排序。"""
        import re

        # 获取查询集
        queryset = self.filter_queryset(self.get_queryset())

        # 将查询集转换为列表并排序
        items = [
            item for item in queryset
            if is_active_cutter_position(item.cutter_position_no)
        ]

        def sort_key(item):
            """生成排序键。"""
            cutter_no = item.cutter_position_no or ''
            tool_type = item.tool_type or ''

            # 提取刀位号的前缀、数字和后缀
            match = re.match(r'^([a-zA-Z]*)(\d+)([a-zA-Z]*)$', cutter_no)
            if match:
                prefix = match.group(1).lower()
                number = int(match.group(2))
                suffix = match.group(3).lower()
                return (tool_type, prefix, number, suffix)
            else:
                return (tool_type, cutter_no.lower(), 0, '')

        items.sort(key=sort_key)

        # 手动分页
        page = self.paginate_queryset(items)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(items, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def get_all_status(self, request):
        """获取所有刀位的最新磨损状态。"""
        from django.db.models import Max, OuterRef, Subquery

        # 每个刀位最新一条换刀明细的 wear_condition + is_replaced
        latest_warehouse = ToolChangeDetail.objects.filter(
            cutter_position_no=OuterRef('cutter_position_no')
        ).order_by('-warehouse__open_time').values('wear_condition', 'is_replaced')[:1]

        positions = CutterPositionInfo.objects.annotate(
            latest_wear=Subquery(latest_warehouse.values('wear_condition')),
            latest_replaced=Subquery(latest_warehouse.values('is_replaced')),
        ).values('cutter_position_no', 'tool_type', 'latest_wear', 'latest_replaced')

        result = {}
        for p in positions:
            if not is_active_cutter_position(p['cutter_position_no']):
                continue
            result[p['cutter_position_no']] = {
                'tool_type': p['tool_type'],
                'wear_condition': _normalize_wear_condition(p['latest_wear']),
                'wear_label': p['latest_wear'],
                'is_replaced': p['latest_replaced'],
            }
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def model_mapping(self, request):
        raw_codes = request.query_params.get('codes') or ''
        requested_codes = [item.strip() for item in raw_codes.split(',') if item.strip()]

        positions = [
            pos for pos in CutterPositionInfo.objects.select_related('shield_machine', 'tool_info').all()
            if is_active_cutter_position(pos.cutter_position_no)
        ]
        db_map = {_normalize_cutter_no(pos.cutter_position_no): pos for pos in positions}
        db_codes = set(db_map.keys())
        model_codes = set(_normalize_cutter_no(code) for code in requested_codes)

        target_codes = requested_codes or [pos.cutter_position_no for pos in positions]
        matched = []
        unmatched_model_codes = []
        for code in target_codes:
            key = _normalize_cutter_no(code)
            pos = db_map.get(key)
            if not pos:
                unmatched_model_codes.append(code)
                continue
            matched.append({
                'model_code': code,
                'cutter_position_no': pos.cutter_position_no,
                'tool_type': pos.tool_type,
                'tool_type_display': pos.get_tool_type_display(),
                'tool_name': pos.tool_info.tool_type_name if pos.tool_info else '',
                'shield_machine': pos.shield_machine.shield_model if pos.shield_machine else '',
            })

        unmatched_database_codes = []
        if requested_codes:
            for pos in positions:
                if _normalize_cutter_no(pos.cutter_position_no) not in model_codes:
                    unmatched_database_codes.append(pos.cutter_position_no)

        return SuccessResponse(data={
            'matched': matched,
            'unmatched_model_codes': unmatched_model_codes,
            'unmatched_database_codes': unmatched_database_codes,
            'matched_count': len(matched),
            'model_count': len(requested_codes),
            'database_count': len(db_codes),
        })


# ==================== 地层基本信息管理 ====================

# 地层类型字典接口已废弃，改为使用系统字典 /api/system/dictionary/?parent=stratum_type
class CutterModelMappingSerializer(CustomModelSerializer):
    cutter_position_no = serializers.CharField(read_only=True, source='cutter_position.cutter_position_no')
    tool_type = serializers.CharField(read_only=True, source='cutter_position.tool_type')
    tool_type_display = serializers.CharField(read_only=True, source='cutter_position.get_tool_type_display')
    tool_name = serializers.CharField(read_only=True, source='cutter_position.tool_info.tool_type_name')

    class Meta:
        model = CutterModelMapping
        fields = '__all__'
        read_only_fields = ["id"]


class CutterModelMappingViewSet(CustomModelViewSet):
    queryset = CutterModelMapping.objects.select_related(
        'cutter_position', 'cutter_position__tool_info'
    ).all()
    serializer_class = CutterModelMappingSerializer
    create_serializer_class = CutterModelMappingSerializer
    update_serializer_class = CutterModelMappingSerializer
    filter_fields = ['model_point_code', 'component_id', 'cutter_position', 'is_active']
    search_fields = ['model_point_code', 'component_id', 'cutter_position__cutter_position_no']

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def active_map(self, request):
        mappings = self.get_queryset().filter(is_active=True)
        data = []
        for item in mappings:
            pos = item.cutter_position
            if not is_active_cutter_position(pos.cutter_position_no):
                continue
            data.append({
                'id': item.id,
                'model_point_code': item.model_point_code,
                'component_id': item.component_id,
                'cutter_position_no': pos.cutter_position_no,
                'tool_type': pos.tool_type,
                'tool_type_display': pos.get_tool_type_display(),
                'tool_name': pos.tool_info.tool_type_name if pos.tool_info else '',
                'screen_x': item.screen_x,
                'screen_y': item.screen_y,
                'sort_no': item.sort_no,
            })
        return SuccessResponse(data=data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path='active_ma')
    def active_ma(self, request):
        return self.active_map(request)

    @action(detail=False, methods=['post'], permission_classes=[AnonymousUserPermission])
    def bulk_upsert(self, request):
        items = request.data.get('items', [])
        if not isinstance(items, list):
            return ErrorResponse(msg='items must be a list')

        position_map = {
            str(pos.cutter_position_no): pos
            for pos in CutterPositionInfo.objects.all()
            if pos.cutter_position_no
        }
        saved = []
        missing = []

        for index, item in enumerate(items):
            cutter_position_no = str(item.get('cutter_position_no') or item.get('code') or '').strip()
            pos = position_map.get(cutter_position_no)
            if not pos:
                missing.append(cutter_position_no)
                continue

            model_point_code = str(item.get('model_point_code') or cutter_position_no).strip()
            if not model_point_code:
                model_point_code = cutter_position_no

            mapping, _ = CutterModelMapping.objects.update_or_create(
                model_point_code=model_point_code,
                defaults={
                    'component_id': item.get('component_id') or '',
                    'cutter_position': pos,
                    'screen_x': item.get('screen_x'),
                    'screen_y': item.get('screen_y'),
                    'sort_no': item.get('sort_no', index),
                    'is_active': item.get('is_active', True),
                    'remark': item.get('remark') or '',
                }
            )
            saved.append(mapping.id)

        return SuccessResponse(data={
            'saved_count': len(saved),
            'missing_count': len(missing),
            'missing': missing,
            'ids': saved,
        })


class CutterImageAnnotationSerializer(CustomModelSerializer):
    cutter_position_no = serializers.CharField(read_only=True, source='cutter_position.cutter_position_no')
    tool_parent_type = serializers.CharField(read_only=True, source='cutter_position.tool_info.tool_parent_type')
    tool_type_name = serializers.CharField(read_only=True, source='cutter_position.tool_info.tool_type_name')

    class Meta:
        model = CutterImageAnnotation
        fields = '__all__'
        read_only_fields = ['id']


def _clean_polygon_selector(selector, canvas_width, canvas_height):
    if not isinstance(selector, dict) or str(selector.get('type') or '').upper() != 'POLYGON':
        raise serializers.ValidationError('仅支持多边形轮廓')

    geometry = selector.get('geometry')
    points = geometry.get('points') if isinstance(geometry, dict) else None
    if not isinstance(points, list) or not 3 <= len(points) <= 300:
        raise serializers.ValidationError('多边形轮廓需要 3 至 300 个顶点')

    cleaned_points = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise serializers.ValidationError('轮廓顶点格式无效')
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            raise serializers.ValidationError('轮廓坐标必须是数字')
        if not math.isfinite(x) or not math.isfinite(y):
            raise serializers.ValidationError('轮廓坐标必须是有限数值')
        if x < 0 or y < 0 or x > canvas_width or y > canvas_height:
            raise serializers.ValidationError('轮廓坐标超出底图范围')
        cleaned_points.append([round(x, 2), round(y, 2)])

    xs = [point[0] for point in cleaned_points]
    ys = [point[1] for point in cleaned_points]
    return {
        'type': 'POLYGON',
        'geometry': {
            'points': cleaned_points,
            'bounds': {
                'minX': min(xs),
                'minY': min(ys),
                'maxX': max(xs),
                'maxY': max(ys),
            },
        },
    }


class CutterImageAnnotationViewSet(CustomModelViewSet):
    queryset = CutterImageAnnotation.objects.select_related(
        'cutter_position',
        'cutter_position__tool_info',
        'cutter_position__shield_machine',
    ).all()
    serializer_class = CutterImageAnnotationSerializer
    create_serializer_class = CutterImageAnnotationSerializer
    update_serializer_class = CutterImageAnnotationSerializer
    filter_fields = ['cutter_position', 'image_key', 'is_active']
    search_fields = ['annotation_id', 'cutter_position__cutter_position_no']

    def get_queryset(self):
        queryset = super().get_queryset()
        shield_machine_id = self.request.query_params.get('shield_machine')
        if shield_machine_id:
            queryset = queryset.filter(cutter_position__shield_machine_id=shield_machine_id)
        return queryset

    @action(detail=False, methods=['get'])
    def workspace(self, request):
        shield_machine_id = request.query_params.get('shield_machine')
        image_key = str(request.query_params.get('image_key') or 'cutterhead-final-v1').strip()
        if not shield_machine_id:
            return ErrorResponse(msg='缺少盾构机编号')

        positions = list(
            CutterPositionInfo.objects.filter(shield_machine_id=shield_machine_id)
            .select_related('tool_info', 'shield_machine')
        )
        positions = sort_cutter_position_items(positions, key=lambda item: item.cutter_position_no)
        position_data = [
            {
                'id': item.id,
                'cutter_position_no': item.cutter_position_no,
                'tool_parent_type': item.tool_info.tool_parent_type if item.tool_info else item.tool_type,
                'tool_type_name': item.tool_info.tool_type_name if item.tool_info else '',
            }
            for item in positions
        ]

        annotations = self.get_queryset().filter(
            cutter_position__shield_machine_id=shield_machine_id,
            image_key=image_key,
            is_active=True,
        )
        return SuccessResponse(data={
            'positions': position_data,
            'annotations': self.get_serializer(annotations, many=True).data,
            'image_key': image_key,
        })

    @action(detail=False, methods=['post'])
    def bulk_replace(self, request):
        shield_machine_id = request.data.get('shield_machine')
        image_key = str(request.data.get('image_key') or 'cutterhead-final-v1').strip()
        items = request.data.get('annotations', [])
        try:
            canvas_width = int(request.data.get('canvas_width') or 1900)
            canvas_height = int(request.data.get('canvas_height') or 2100)
        except (TypeError, ValueError):
            return ErrorResponse(msg='底图尺寸无效')

        if not shield_machine_id:
            return ErrorResponse(msg='缺少盾构机编号')
        if not image_key or len(image_key) > 100:
            return ErrorResponse(msg='底图版本标识无效')
        if not isinstance(items, list) or len(items) > 1000:
            return ErrorResponse(msg='轮廓数据格式无效')
        if not 1 <= canvas_width <= 20000 or not 1 <= canvas_height <= 20000:
            return ErrorResponse(msg='底图尺寸超出允许范围')

        position_map = {
            str(item.id): item
            for item in CutterPositionInfo.objects.filter(shield_machine_id=shield_machine_id)
        }
        cleaned_items = []
        seen_positions = set()
        seen_annotation_ids = set()
        try:
            for item in items:
                if not isinstance(item, dict):
                    raise serializers.ValidationError('轮廓数据项格式无效')
                position_id = str(item.get('cutter_position') or '')
                position = position_map.get(position_id)
                if not position:
                    raise serializers.ValidationError('轮廓包含不属于当前盾构机的刀位')
                if position_id in seen_positions:
                    raise serializers.ValidationError(f'刀位 {position.cutter_position_no} 存在重复轮廓')

                annotation_id = str(item.get('annotation_id') or '').strip()
                if not annotation_id or len(annotation_id) > 100:
                    raise serializers.ValidationError('轮廓标识无效')
                if annotation_id in seen_annotation_ids:
                    raise serializers.ValidationError('轮廓标识重复')

                cleaned_items.append({
                    'position': position,
                    'annotation_id': annotation_id,
                    'selector': _clean_polygon_selector(item.get('selector'), canvas_width, canvas_height),
                })
                seen_positions.add(position_id)
                seen_annotation_ids.add(annotation_id)
        except serializers.ValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) else exc.detail
            return ErrorResponse(msg=str(detail))

        for item in cleaned_items:
            if CutterImageAnnotation.objects.filter(annotation_id=item['annotation_id']).exclude(
                cutter_position=item['position'],
                image_key=image_key,
            ).exists():
                return ErrorResponse(msg='轮廓标识已被其他刀位使用')

        with transaction.atomic():
            existing = CutterImageAnnotation.objects.filter(
                cutter_position__shield_machine_id=shield_machine_id,
                image_key=image_key,
            )
            existing.exclude(cutter_position_id__in=[item['position'].id for item in cleaned_items]).delete()

            for item in cleaned_items:
                CutterImageAnnotation.objects.update_or_create(
                    cutter_position=item['position'],
                    image_key=image_key,
                    defaults={
                        'annotation_id': item['annotation_id'],
                        'selector': item['selector'],
                        'canvas_width': canvas_width,
                        'canvas_height': canvas_height,
                        'is_active': True,
                    },
                )

        saved = self.get_queryset().filter(
            cutter_position__shield_machine_id=shield_machine_id,
            image_key=image_key,
            is_active=True,
        )
        return SuccessResponse(data={
            'saved_count': saved.count(),
            'annotations': self.get_serializer(saved, many=True).data,
        })


# class StratumTypeDictSerializer(CustomModelSerializer):
#     """
#     地层类型字典-序列化器
#     """
#     class Meta:
#         model = StratumTypeDict
#         fields = '__all__'
#         read_only_fields = ["id"]
#
#
# class StratumTypeDictCreateUpdateSerializer(CustomModelSerializer):
#     """
#     地层类型字典 创建/更新时的序列化器
#     """
#     class Meta:
#         model = StratumTypeDict
#         fields = '__all__'
#
#
# class StratumTypeDictViewSet(CustomModelViewSet):
#     """
#     地层类型字典接口
#     list:查询
#     create:新增
#     update:修改
#     retrieve:单例
#     destroy:删除
#     """
#     queryset = StratumTypeDict.objects.all()
#     serializer_class = StratumTypeDictSerializer
#     create_serializer_class = StratumTypeDictCreateUpdateSerializer
#     update_serializer_class = StratumTypeDictCreateUpdateSerializer
#     filter_fields = ['stratum_name', 'stratum_code']
#     search_fields = ['stratum_name', 'stratum_code', 'description']


# 地层环号关联序列化器已废弃，改为直接在 StratumBasicInfo 中存储。
# class StratumRingRelationSerializer(CustomModelSerializer):
#     """
#     地层环号关联-序列化器
#     """
#     stratum_name = serializers.CharField(read_only=True, source='stratum_type.stratum_name')
#     ring_no = serializers.CharField(read_only=True, source='stratum_basic_info.ring_no')
#
#     class Meta:
#         model = StratumRingRelation
#         fields = '__all__'
#         read_only_fields = ["id"]


class StratumBasicInfoSerializer(CustomModelSerializer):
    """
    地层基本信息-序列化器
    """
    project_name = serializers.CharField(read_only=True, source='project.project_name')
    stratum_types_list = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = StratumBasicInfo
        fields = '__all__'
        read_only_fields = ["id"]

    def get_stratum_types_list(self, obj):
        """获取该环号关联的所有地层类型（从系统字典）。"""
        return obj.get_stratum_types()


class StratumBasicInfoCreateUpdateSerializer(CustomModelSerializer):
    """
    地层基本信息管理 创建/更新时的序列化器
    """
    stratum_types_data = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="地层信息列表，格式：[{'stratum_type_code': 'xxx', 'ring_count': 10}]"
    )

    class Meta:
        model = StratumBasicInfo
        fields = '__all__'

    def create(self, validated_data):
        stratum_types_data = validated_data.pop('stratum_types_data', [])

        # 将地层类型编码列表转换为逗号分隔的字符串
        if stratum_types_data:
            validated_data['stratum_type_codes'] = ','.join(stratum_types_data)

        instance = super().create(validated_data)
        return instance

    def update(self, instance, validated_data):
        stratum_types_data = validated_data.pop('stratum_types_data', None)

        # 如果提供了地层类型数据，则更新
        if stratum_types_data is not None:
            validated_data['stratum_type_codes'] = ','.join(stratum_types_data)

        instance = super().update(instance, validated_data)
        return instance


class StratumBasicInfoViewSet(CustomModelViewSet, ImportSerializerMixin, ExportSerializerMixin):
    """
    地层基本信息管理接口
    list:查询
    create:新增
    update:修改
    retrieve:单例
    destroy:删除
    import_data:导入
    export_data:导出
    """
    queryset = StratumBasicInfo.objects.annotate(
        ring_int=Cast('ring_no', output_field=IntegerField())
    ).order_by('ring_int')
    serializer_class = StratumBasicInfoSerializer
    create_serializer_class = StratumBasicInfoCreateUpdateSerializer
    update_serializer_class = StratumBasicInfoCreateUpdateSerializer
    import_serializer_class = StratumBasicInfoCreateUpdateSerializer
    filter_fields = ['project', 'ring_no']
    search_fields = ['ring_no', 'stratum_info']

    # 导入字段配置
    import_field_dict = {
        'project': {
            'title': '项目编号',
            'display': 'project',
            'choices': {
                'queryset': ProjectInfo.objects.all(),
                'values_name': 'project_id'
            }
        },
        'ring_no': '环号',
        'stratum_info': '地层信息（备注）',
        'burial_depth': '埋深(m)',
    }

    # 导出字段配置
    export_field_label = {
        'project_name': '项目名称',
        'ring_no': '环号',
        'stratum_info': '地层信息（备注）',
        'burial_depth': '埋深(m)',
        'create_datetime': '创建时间',
    }
    export_serializer_class = StratumBasicInfoSerializer

    @action(methods=['post'], detail=False, url_path='import_from_pdf')
    def import_from_pdf(self, request):
        import os
        from pathlib import Path
        from django.conf import settings
        from application.shield.management.commands.import_stratum_pdf import (
            extract_page_words, find_ring_labels, find_stratum_legend, assign_stratums_to_rings
        )

        project_id = request.data.get('project')
        dry_run = bool(request.data.get('dry_run', False))
        pdf_path = request.data.get('pdf_path') or os.environ.get('STRATUM_IMPORT_PDF_PATH', '')

        if not Path(pdf_path).exists():
            return ErrorResponse(msg=f'PDF 文件不存在: {pdf_path}')

        if not project_id:
            return ErrorResponse(msg='缺少 project 参数')
        try:
            project = ProjectInfo.objects.get(pk=project_id)
        except ProjectInfo.DoesNotExist:
            return ErrorResponse(msg=f'项目 id={project_id} 不存在')

        try:
            words, page_width, page_height = extract_page_words(pdf_path)
        except Exception as e:
            return ErrorResponse(msg=f'PDF 读取失败: {e}')

        ring_labels = find_ring_labels(words, page_height)
        legend_items = find_stratum_legend(words, page_height)

        if not ring_labels:
            return ErrorResponse(msg='未识别到环号，请检查 PDF 文件')

        ring_stratum_map = assign_stratums_to_rings(ring_labels, legend_items, page_width)

        if dry_run:
            preview = [
                {'ring_no': k, 'codes': v}
                for k, v in sorted(ring_stratum_map.items(), key=lambda x: int(x[0]))
            ]
            return SuccessResponse(data={
                'preview': preview[:50],
                'total': len(ring_stratum_map),
                'ring_count': len(ring_labels),
                'legend_count': len(legend_items),
            })

        created = updated = 0
        # 只更新地层编码，不再把 stratum_info 置空——那是工程师手写的备注，
        # 重新导入 PDF 不应该把它清掉。整批放进事务，避免解析中途失败留下半张表。
        with transaction.atomic():
            for ring_no, codes in ring_stratum_map.items():
                _, is_created = StratumBasicInfo.objects.update_or_create(
                    project=project,
                    ring_no=ring_no,
                    defaults={'stratum_type_codes': ','.join(codes)},
                )
                if is_created:
                    created += 1
                else:
                    updated += 1

        return SuccessResponse(data={
            'created': created,
            'updated': updated,
            'total': created + updated,
            'ring_count': len(ring_labels),
            'legend_count': len(legend_items),
        })


# ==================== 换刀明细管理（整合版） ====================

class ToolChangeDetailSerializer(CustomModelSerializer):
    """
    换刀明细-序列化器（表格式）
    """
    warehouse_id_name = serializers.CharField(read_only=True, source='warehouse.warehouse_id')
    warehouse_ring_no = serializers.CharField(read_only=True, source='warehouse.ring_no')
    warehouse_open_time = serializers.DateTimeField(read_only=True, source='warehouse.open_time')
    # 字段未绑定 choices，Django 不会生成 get_wear_condition_display()，
    # DRF 会静默 SkipField 把这个键整个丢掉（前端"磨损情况"列因此长期空白）。
    # 改为方法字段，中英文都能给出可读文案。
    wear_condition_display = serializers.SerializerMethodField()

    def get_wear_condition_display(self, obj):
        return wear_display(obj.wear_condition)
    replacement_type_display = serializers.CharField(read_only=True, source='get_replacement_type_display')
    wear_image = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    wear_image_url = serializers.SerializerMethodField(read_only=True)
    cutter_position_info = serializers.SerializerMethodField(read_only=True)
    new_tool_record_data = serializers.SerializerMethodField(read_only=True)
    old_tool_record_data = serializers.SerializerMethodField(read_only=True)
    old_photo_links = serializers.SerializerMethodField(read_only=True)
    trajectory = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ToolChangeDetail
        fields = '__all__'
        read_only_fields = ["id", "replacement_count"]

    def get_wear_image_url(self, obj):
        """获取图片 URL（兼容绝对 URL 和相对路径）。"""
        if not obj.wear_image:
            return None
        value = str(obj.wear_image)
        if not value:
            return None
        if value.startswith('http://') or value.startswith('https://'):
            return value
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri('/' + value.lstrip('/'))
        return value

    def get_cutter_position_info(self, obj):
        """获取刀位信息，包含刀具类型名称。"""
        if obj.cutter_position:
            tool_type_name = '-'
            if obj.cutter_position.tool_info:
                tool_type_name = obj.cutter_position.tool_info.tool_type_name
            return {
                'tool_type_name': tool_type_name,
            }
        return None

    @staticmethod
    def _media_url(request, image):
        if not image:
            return None
        value = str(image)
        if value.startswith('http://') or value.startswith('https://'):
            return value
        if request:
            return request.build_absolute_uri('/' + value.lstrip('/'))
        return value

    @staticmethod
    def _photo_media_url(request, photo):
        value = ToolChangeDetailSerializer._media_url(request, photo.image.url if photo.image else None)
        if not value:
            return None
        separator = '&' if '?' in value else '?'
        return f'{value}{separator}v={photo.id}'

    def get_new_tool_record_data(self, obj):
        record = getattr(obj, 'new_tool_record', None)
        if not record:
            return None
        return {
            'id': record.id,
            'tool_uid': record.tool_instance.tool_uid if record.tool_instance else None,
            'display_tool_no': record.tool_instance.display_tool_no if record.tool_instance else None,
            'ring_type': record.ring_type,
            'ring_type_display': record.get_ring_type_display() if record.ring_type else '',
            'ring_manufacturer': record.ring_manufacturer,
            'shaft_condition': record.shaft_condition,
            'shaft_condition_display': record.get_shaft_condition_display() if record.shaft_condition else '',
            'shaft_manufacturer': record.shaft_manufacturer,
            'hub_condition': record.hub_condition,
            'hub_condition_display': record.get_hub_condition_display() if record.hub_condition else '',
            'hub_manufacturer': record.hub_manufacturer,
            'scraper_manufacturer': record.scraper_manufacturer,
            'remark': record.remark,
        }

    def get_old_tool_record_data(self, obj):
        record = getattr(obj, 'old_tool_record', None)
        if not record:
            return None
        request = self.context.get('request')
        return {
            'id': record.id,
            'old_tool_number': record.old_tool_number,
            'wear_condition': record.wear_condition,
            'repair_parts': record.repair_parts or [],
            'repair_result': record.repair_result,
            'repair_price': record.repair_price,
            'inspection_status': record.inspection_status,
            'inspection_status_display': record.get_inspection_status_display(),
            'ring_wear_amount': record.ring_wear_amount,
            'bias_wear_amount': record.bias_wear_amount,
            'tool_track': record.tool_track,
            'ring_damage': record.ring_damage or [],
            'ring_tooth_loss_count': record.ring_tooth_loss_count,
            'ring_other_condition': record.ring_other_condition,
            'bearing_failed': record.bearing_failed,
            'bearing_failure_reasons': record.bearing_failure_reasons or [],
            'bearing_other_condition': record.bearing_other_condition,
            'hub_damaged': record.hub_damaged,
            'hub_failure_reasons': record.hub_failure_reasons or [],
            'hub_other_condition': record.hub_other_condition,
            'disposition': record.disposition,
            'disposition_display': record.get_disposition_display() if record.disposition else '',
            'scraper_wear_amount': record.scraper_wear_amount,
            'scraper_chipped': record.scraper_chipped,
            'scraper_broken': record.scraper_broken,
            'scraper_detached': record.scraper_detached,
            'photos': [
                {
                    'id': photo.id,
                    'name': photo.original_filename or str(photo.image),
                    'url': self._photo_media_url(request, photo),
                }
                for photo in record.photos.all()
            ],
        }

    def get_old_photo_links(self, obj):
        record = getattr(obj, 'old_tool_record', None)
        if not record:
            return []
        request = self.context.get('request')
        return [
            {
                'id': photo.id,
                'name': photo.original_filename or f'照片{index + 1}',
                'url': self._photo_media_url(request, photo),
            }
            for index, photo in enumerate(record.photos.all())
        ]

    def get_trajectory(self, obj):
        return get_tool_trajectory(obj.cutter_position_no, obj.tool_parent_type)


class ToolChangeDetailCreateUpdateSerializer(CustomModelSerializer):
    """换刀明细创建/更新序列化器。"""
    wear_image = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    class Meta:
        model = ToolChangeDetail
        fields = '__all__'
        read_only_fields = ["id", "replacement_count"]


class ToolChangeDetailViewSet(CustomModelViewSet):
    """换刀明细管理接口。"""
    queryset = ToolChangeDetail.objects.select_related(
        'warehouse', 'warehouse__project', 'cutter_position', 'cutter_position__tool_info'
    ).prefetch_related(
        'new_tool_record', 'old_tool_record__photos'
    ).order_by('cutter_position_no', 'warehouse__open_time', 'id')
    serializer_class = ToolChangeDetailSerializer
    create_serializer_class = ToolChangeDetailCreateUpdateSerializer
    update_serializer_class = ToolChangeDetailCreateUpdateSerializer
    filter_fields = ['warehouse', 'cutter_position', 'is_replaced', 'tool_parent_type', 'wear_condition']
    search_fields = ['cutter_position_no', 'tool_number', 'manufacturer']

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def field_options(self, request):
        """统一提供滚刀/刮刀记录所需的枚举，避免页面各自维护词条。"""
        as_options = lambda choices: [
            {'value': value, 'label': label} for value, label in choices
        ]
        return SuccessResponse(data={
            'tool_types': [
                {'value': value, 'label': label}
                for value, label in TOOL_TYPES
            ],
            'ring_types': as_options(NEW_RING_TYPE_CHOICES),
            'component_conditions': as_options(NEW_COMPONENT_CONDITION_CHOICES),
            'bearing_failure_reasons': as_options(BEARING_FAILURE_REASON_CHOICES),
            'hub_failure_reasons': as_options(HUB_FAILURE_REASON_CHOICES),
            'ring_damage': as_options(RING_DAMAGE_CHOICES),
            'old_tool_dispositions': as_options(OLD_TOOL_DISPOSITION_CHOICES),
            'wear_descriptions': as_options(BLADE_WEAR_DESCRIPTION_CHOICES),
            'check_results': [
                {'value': value, 'label': label}
                for value, label in ToolChangeDetail.CHECK_RESULT_CHOICES
            ],
        })

    @staticmethod
    def _parse_list(value):
        if value in (None, ''):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        try:
            parsed = json.loads(str(value))
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return [item.strip() for item in str(value).replace('，', ',').split(',') if item.strip()]

    @staticmethod
    def _parse_bool(value):
        if value in (None, ''):
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on', '是'}

    @staticmethod
    def _parse_float(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError('数值字段格式不正确')

    @action(detail=True, methods=['get', 'post', 'put'], url_path='old_tool_record')
    def old_tool_record(self, request, pk=None):
        detail = self.get_object()
        if request.method == 'GET':
            return SuccessResponse(data=ToolChangeDetailSerializer(detail, context={'request': request}).data)
        if not detail.is_replaced:
            return ErrorResponse(msg='未更换刀具不能录入旧刀返修信息')

        record, _ = OldToolRecord.objects.get_or_create(
            tool_change_detail=detail,
            defaults={
                'old_tool_number': detail.tool_number or '',
                'creator': request.user if request.user.is_authenticated else None,
                'dept_belong_id': getattr(request.user, 'dept_id', None),
            },
        )
        scalar_fields = {
            'old_tool_number': str,
            'wear_condition': str,
            'repair_result': str,
            'repair_price': self._parse_float,
            'ring_wear_amount': self._parse_float,
            'bias_wear_amount': self._parse_float,
            'ring_tooth_loss_count': lambda value: int(float(value)) if value not in (None, '') else None,
            'tool_track': str,
            'ring_other_condition': str,
            'bearing_other_condition': str,
            'hub_other_condition': str,
            'disposition': str,
            'scraper_wear_amount': self._parse_float,
        }
        list_fields = {'repair_parts', 'ring_damage', 'bearing_failure_reasons', 'hub_failure_reasons'}
        bool_fields = {'bearing_failed', 'hub_damaged', 'scraper_chipped', 'scraper_broken', 'scraper_detached'}
        for field, converter in scalar_fields.items():
            if field in request.data:
                value = request.data.get(field)
                setattr(record, field, None if value in (None, '') and converter is not str else converter(value))
        for field in list_fields:
            if field in request.data:
                setattr(record, field, self._parse_list(request.data.get(field)))
        for field in bool_fields:
            if field in request.data:
                setattr(record, field, self._parse_bool(request.data.get(field)))
        if 'inspection_status' in request.data:
            record.inspection_status = request.data.get('inspection_status') or record.inspection_status
        elif any(field in request.data for field in set(scalar_fields) | list_fields | bool_fields):
            record.inspection_status = 'CONFIRMED'
        record.vendor_feedback_at = timezone.now()
        record.modifier = str(getattr(request.user, 'id', '') or '')
        record.save()

        photos = request.FILES.getlist('photos') or request.FILES.getlist('old_photos')
        if len(photos) + record.photos.count() > 5:
            return ErrorResponse(msg='旧刀照片最多上传 5 张')
        for photo in photos:
            mime_type = getattr(photo, 'content_type', '') or ''
            if mime_type not in {'image/jpeg', 'image/jpg', 'image/png'}:
                return ErrorResponse(msg='旧刀照片仅支持 JPG/JPEG/PNG')
            if getattr(photo, 'size', 0) > 30 * 1024 * 1024:
                return ErrorResponse(msg='单张旧刀照片不能超过 30MB')
            OldToolPhoto.objects.create(
                old_tool_record=record,
                image=photo,
                original_filename=getattr(photo, 'name', ''),
                file_size=getattr(photo, 'size', None),
                mime_type=mime_type,
                creator=request.user if request.user.is_authenticated else None,
                dept_belong_id=getattr(request.user, 'dept_id', None),
            )
        detail.save(update_fields=['update_datetime'])
        detail = self.get_queryset().get(pk=detail.pk)
        return SuccessResponse(data=ToolChangeDetailSerializer(detail, context={'request': request}).data, msg='旧刀返修信息已保存')

    def _normalize_tool_parent_type(self, value):
        type_map = {
            '滚刀': 'DISC',
            '撕裂刀': 'RIPPER',
            '刮刀': 'SCRAPER',
            'DISC': 'DISC',
            'RIPPER': 'RIPPER',
            'SCRAPER': 'SCRAPER',
        }
        raw = str(value or '').strip()
        return type_map.get(raw, raw)

    def _parse_repair_parts(self, value):
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(',') if item.strip()]

    @action(detail=False, methods=['get'])
    def cost_options(self, request):
        """按刀位、厂家和更换类型匹配成本库价格。"""
        replacement_type = request.query_params.get('replacement_type')
        manufacturer = request.query_params.get('manufacturer')
        brand = request.query_params.get('brand')
        cutter_position_no = request.query_params.get('cutter_position_no')
        shield_machine_id = request.query_params.get('shield_machine')
        tool_parent_type = self._normalize_tool_parent_type(request.query_params.get('tool_parent_type'))
        repair_parts = self._parse_repair_parts(request.query_params.get('repair_parts'))

        cost_type = None
        if replacement_type == 'COMPLETE':
            cost_type = 'NEW_TOOL'
        elif replacement_type == 'REPAIR':
            cost_type = 'REPAIR'

        position = None
        if cutter_position_no:
            position_query = CutterPositionInfo.objects.select_related('tool_info').filter(
                cutter_position_no=cutter_position_no
            )
            if shield_machine_id:
                position_query = position_query.filter(shield_machine_id=shield_machine_id)
            position = position_query.first()

        costs = ToolCost.objects.select_related('tool_info').all()
        if position and position.tool_info_id:
            costs = costs.filter(tool_info_id=position.tool_info_id)
        elif tool_parent_type:
            costs = costs.filter(tool_info__tool_parent_type=tool_parent_type)

        if cost_type:
            costs = costs.filter(cost_type=cost_type)
        if manufacturer:
            costs = costs.filter(manufacturer=manufacturer)
        if brand:
            costs = costs.filter(brand=brand)

        result = []
        seen = set()
        for cost in costs.order_by('manufacturer', 'brand', '-create_datetime'):
            if cost.cost_type == 'REPAIR' and repair_parts:
                cost_parts = [str(item).strip() for item in (cost.repair_parts or [])]
                if not all(part in cost_parts for part in repair_parts):
                    continue

            item = {
                'id': cost.id,
                'value': cost.manufacturer or '',
                'label': f"{cost.manufacturer or '-'} / {cost.brand or '-'} / {cost.unit_price or 0}元",
                'manufacturer': cost.manufacturer,
                'brand': cost.brand,
                'unit_price': str(cost.unit_price) if cost.unit_price is not None else None,
                'price': str(cost.unit_price) if cost.unit_price is not None else None,
                'cost_type': cost.cost_type,
                'repair_parts': cost.repair_parts or [],
                'tool_info': cost.tool_info_id,
                'tool_info_name': cost.tool_info.tool_type_name if cost.tool_info else None,
            }
            key = (item['manufacturer'], item['brand'], item['unit_price'], item['cost_type'], tuple(item['repair_parts']))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)

        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def overview(self, request):
        """Return only the fields needed by the home change-tool overview."""
        replacement_labels = dict(ToolChangeDetail.REPLACEMENT_TYPE_CHOICES)
        queryset = (
            ToolChangeDetail.objects
            .select_related('warehouse')
            .exclude(cutter_position_no__isnull=True)
            .exclude(cutter_position_no='')
            .values(
                'cutter_position_no',
                'tool_parent_type',
                'warehouse__ring_no',
                'warehouse__open_time',
                'wear_condition',
                'replacement_type',
                'replacement_count',
                'is_replaced',
                'manufacturer',
            )
        )
        rows = []
        for item in queryset.iterator():
            position = item['cutter_position_no']
            if not is_active_cutter_position(position):
                continue
            replacement_type = item['replacement_type'] or ''
            rows.append({
                'cutter_position_no': position,
                'tool_parent_type': item['tool_parent_type'] or '',
                'warehouse_ring_no': item['warehouse__ring_no'],
                'warehouse_open_time': _format_datetime(item['warehouse__open_time']),
                'wear_condition': item['wear_condition'] or '',
                'wear_condition_display': wear_display(item['wear_condition']),
                'replacement_type': replacement_type,
                'replacement_type_display': replacement_labels.get(replacement_type, replacement_type),
                'replacement_count': item['replacement_count'] or 0,
                'is_replaced': bool(item['is_replaced']),
                'manufacturer': item['manufacturer'] or '',
            })
        return SuccessResponse(data=rows)

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def home_warnings(self, request):
        """Return top cutter positions by rings since last replacement for the home page."""
        limit = request.query_params.get('limit') or 5
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5

        # 预警必须限定在单个项目/盾构机内，否则会用别的项目的最大环号来算本项目的磨损
        project_id = request.query_params.get('project')
        machine_id = request.query_params.get('shield_machine')
        opening_scope = WarehouseOpeningBasicInfo.objects.all()
        detail_scope = ToolChangeDetail.objects.all()
        if project_id:
            opening_scope = opening_scope.filter(project_id=project_id)
            detail_scope = detail_scope.filter(warehouse__project_id=project_id)
        if machine_id:
            opening_scope = opening_scope.filter(shield_model_id=machine_id)
            detail_scope = detail_scope.filter(warehouse__shield_model_id=machine_id)

        latest_opening = (
            opening_scope
            .filter(ring_no__regex=r'^\d+$')
            .annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .exclude(ring_int__isnull=True)
            .order_by('-ring_int', '-open_time')
            .first()
        )
        current_ring = latest_opening.ring_int if latest_opening else 0
        if not current_ring:
            return SuccessResponse(data={'current_ring': None, 'warnings': []})

        latest_replacements = (
            detail_scope
            .filter(is_replaced=True)
            .exclude(cutter_position_no__isnull=True)
            .exclude(cutter_position_no='')
            .select_related('warehouse')
            .filter(warehouse__ring_no__regex=r'^\d+$')
            .annotate(ring_int=Cast('warehouse__ring_no', output_field=IntegerField()))
            .exclude(ring_int__isnull=True)
            .order_by('cutter_position_no', '-ring_int', '-warehouse__open_time')
            .distinct('cutter_position_no')
            .values('cutter_position_no', 'tool_parent_type', 'ring_int')
        )

        warnings = []
        for item in latest_replacements:
            position = item['cutter_position_no']
            if not is_active_cutter_position(position):
                continue
            last_ring = item['ring_int']
            rings_since = current_ring - last_ring
            if rings_since <= 0:
                continue
            warnings.append({
                'position': position,
                'type': item['tool_parent_type'] or '',
                'lastRing': last_ring,
                'ringsSince': rings_since,
            })

        warnings.sort(key=lambda row: row['ringsSince'], reverse=True)
        return SuccessResponse(data={'current_ring': current_ring, 'warnings': warnings[:limit]})

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def batch_update(self, request):
        """批量更新换刀明细记录（整批成功或整批回滚）。"""
        updates = request.data.get('updates', [])

        if not updates:
            return ErrorResponse(msg="请提供更新数据")

        updated_records = []
        missing_ids = []
        for update_data in updates:
            record_id = update_data.pop('id', None)
            if not record_id:
                continue

            try:
                instance = ToolChangeDetail.objects.get(id=record_id)
                serializer = self.update_serializer_class(instance, data=update_data, partial=True, request=request)
                serializer.is_valid(raise_exception=True)
                instance = serializer.save()
                updated_records.append(instance)
            except ToolChangeDetail.DoesNotExist:
                # 不再静默跳过：一并回报，避免"成功更新 N 条"掩盖丢失的行
                missing_ids.append(record_id)

        result_serializer = self.serializer_class(updated_records, many=True, request=request)
        msg = f"成功更新{len(updated_records)}条记录"
        if missing_ids:
            msg += f"；{len(missing_ids)} 条记录不存在（id={missing_ids}）"
        return SuccessResponse(data=result_serializer.data, msg=msg)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def batch_create(self, request):
        """批量创建换刀明细记录（整批成功或整批回滚）。"""
        warehouse_id = request.data.get('warehouse_id')
        details = request.data.get('details', [])

        if not warehouse_id:
            return ErrorResponse(msg="请提供开仓记录ID")

        if not details:
            return ErrorResponse(msg="请提供换刀明细数据")

        created_records = []
        for detail in details:
            detail['warehouse'] = warehouse_id
            serializer = self.create_serializer_class(data=detail, request=request)
            serializer.is_valid(raise_exception=True)
            instance = serializer.save()
            created_records.append(instance)

        result_serializer = self.serializer_class(created_records, many=True, request=request)
        return SuccessResponse(data=result_serializer.data, msg=f"成功创建{len(created_records)}条记录")

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def get_cutter_positions(self, request):
        """获取指定盾构机的刀位列表。"""
        shield_machine_id = request.query_params.get('shield_machine')
        if not shield_machine_id:
            return SuccessResponse(data=[])

        positions = CutterPositionInfo.objects.filter(
            shield_machine_id=shield_machine_id
        ).values('id', 'cutter_position_no', 'tool_type')
        positions = [
            pos for pos in positions
            if is_active_cutter_position(pos['cutter_position_no'])
        ]

        # 刀具类型映射字典
        # 修正：TOOL_TYPES 是 models 的模块级常量，不是 CutterPositionInfo 的类属性
        tool_type_map = dict(TOOL_TYPES)

        result = [
            {
                'value': pos['id'],
                'label': "{} ({})".format(
                    pos['cutter_position_no'],
                    tool_type_map.get(pos['tool_type'], pos['tool_type'])  # 显示中文名称
                ),
                'cutter_position_no': pos['cutter_position_no'],
                'tool_type': pos['tool_type'],
                'tool_type_display': tool_type_map.get(pos['tool_type'], pos['tool_type'])
            }
            for pos in positions
        ]
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def get_tool_type_codes(self, request):
        """获取所有刀具类型编号列表。"""
        tool_type_codes = ToolInfo.objects.filter(
            tool_type_code__isnull=False,
            tool_type_code__contains='TYPE'
        ).exclude(
            tool_type_code=''
        ).values('tool_type_code').distinct()

        result = []
        seen_codes = set()
        for item in tool_type_codes:
            code = item['tool_type_code']
            if code in seen_codes:
                continue
            seen_codes.add(code)
            tool = ToolInfo.objects.filter(tool_type_code=code).first()
            if tool:
                result.append({
                    'value': code,
                    'label': code,
                    'tool_type_name': tool.tool_type_name,
                })

        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def get_tool_type_names_by_parent(self, request):
        """根据刀具父类型获取刀具类型名称列表。"""
        tool_parent_type = request.query_params.get('tool_parent_type')
        if not tool_parent_type:
            return SuccessResponse(data=[])

        tool_type_names = ToolInfo.objects.filter(
            tool_parent_type=tool_parent_type,
            tool_type_name__isnull=False
        ).exclude(tool_type_name='').values_list('tool_type_name', flat=True).distinct()
        unique_names = sorted(set(tool_type_names))
        result = [{'value': name, 'label': name} for name in unique_names]
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def get_tools_by_type_name(self, request):
        """根据刀具类型名称获取刀具列表。"""
        tool_type_name = request.query_params.get('tool_type_name')
        if not tool_type_name:
            return SuccessResponse(data=[])

        tools = ToolInfo.objects.filter(tool_type_name=tool_type_name).values(
            'id', 'tool_type_name', 'tool_number', 'manufacturer', 'unit_price', 'tool_parent_type'
        )
        result = [
            {
                'value': tool['id'],
                'label': '{}-{}-{}元'.format(tool['tool_type_name'], tool['manufacturer'], tool['unit_price']),
                'tool_type_name': tool['tool_type_name'],
                'tool_number': tool['tool_number'],
                'manufacturer': tool['manufacturer'],
                'unit_price': tool['unit_price'],
                'tool_parent_type': tool['tool_parent_type'],
            }
            for tool in tools
        ]
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def check_is_first_warehouse(self, request):
        """检查当前开仓是否是第一个开仓。"""
        warehouse_id = request.query_params.get('warehouse_id')

        if not warehouse_id:
            return SuccessResponse(data={'is_first': True})

        try:
            current_warehouse = WarehouseOpeningBasicInfo.objects.get(id=warehouse_id)
            # 查询同一项目下是否有更早的开仓记录
            earlier_warehouse = WarehouseOpeningBasicInfo.objects.filter(
                project=current_warehouse.project,
                open_time__lt=current_warehouse.open_time
            ).exists()

            return SuccessResponse(data={'is_first': not earlier_warehouse})
        except WarehouseOpeningBasicInfo.DoesNotExist:
            return SuccessResponse(data={'is_first': True})

    @action(detail=False, methods=['get'], permission_classes=[AnonymousUserPermission])
    def get_cutter_position_history(self, request):
        """获取指定刀位的使用历史。"""
        cutter_position_no = request.query_params.get('cutter_position_no')

        if not cutter_position_no:
            return SuccessResponse(data={
                'cutter_position_no': None,
                'tool_parent_type': None,
                'tool_parent_type_display': None,
                'history': []
            })

        # 获取刀位信息
        cutter_position = CutterPositionInfo.objects.select_related('tool_info').filter(
            cutter_position_no=cutter_position_no
        ).first()

        tool_parent_type = None
        tool_parent_type_display = None
        position_tool_info = _tool_info_from_position(cutter_position)
        if cutter_position:
            tool_parent_type = cutter_position.tool_type
            tool_parent_type_display = cutter_position.get_tool_type_display()

        # 获取该刀位的所有换刀记录，按时间倒序
        change_records = ToolChangeDetail.objects.filter(
            cutter_position_no=cutter_position_no,
            is_replaced=True
        ).select_related(
            'warehouse',
            'cutter_position',
            'cutter_position__tool_info',
        ).order_by('-warehouse__open_time')

        history = []
        for record in change_records:
            # 获取开仓信息
            warehouse = record.warehouse

            # 计算使用时间（从当前开仓到下一次换刀的时间）
            next_change = ToolChangeDetail.objects.filter(
                cutter_position_no=cutter_position_no,
                warehouse__open_time__gt=warehouse.open_time,
                is_replaced=True
            ).order_by('warehouse__open_time').first()

            start_ring = warehouse.ring_no
            end_ring = next_change.warehouse.ring_no if next_change else '使用中'

            # 计算使用环数
            if next_change:
                try:
                    rings_used = int(next_change.warehouse.ring_no) - int(warehouse.ring_no)
                except:
                    rings_used = None
            else:
                rings_used = None

            record_tool_info = _tool_info_from_position(record.cutter_position) or position_tool_info
            tool_type_name = (
                record_tool_info.tool_type_name
                if record_tool_info and record_tool_info.tool_type_name
                else _tool_name_from_record(record, record.cutter_position)
            )
            tool_number = record.tool_number or (record_tool_info.tool_number if record_tool_info else None)
            manufacturer = record.manufacturer or (record_tool_info.manufacturer if record_tool_info else None)
            replacement_type = record.replacement_type

            history.append({
                'warehouse_id': warehouse.warehouse_id,
                'open_time': warehouse.open_time.strftime('%Y-%m-%d %H:%M:%S') if warehouse.open_time else None,
                'start_ring': start_ring,
                'end_ring': end_ring,
                'rings_used': rings_used,
                'tool_type_name': record.tool_parent_type,
                'tool_number': tool_number,
                'replace_part': '、'.join(record.repair_parts) if record.repair_parts else None,
                'wear_type': record.wear_condition,
                'wear_degree': record.replacement_type,
                'tool_parent_type': record.tool_parent_type,
                'tool_parent_type_display': tool_type_name,
                'tool_type_name': tool_type_name,
                'manufacturer': manufacturer,
                'brand': record.brand,
                'price': _decimal_to_float(record.price),
                'replace_part': _join_repair_parts(record.repair_parts),
                'wear_type_display': _wear_condition_label(record.wear_condition),
                'wear_degree': replacement_type,
                'wear_degree_display': _replacement_type_label(replacement_type),
                'replacement_type': replacement_type,
                'replacement_type_display': _replacement_type_label(replacement_type),
                'remark': record.remark,
            })

        return SuccessResponse(data={
            'cutter_position_no': cutter_position_no,
            'tool_parent_type': tool_parent_type,
            'tool_parent_type_display': tool_parent_type_display,
            'history': history
        })

    @action(detail=False, methods=['get'])
    def get_last_new_tool(self, request):
        """根据刀位号和开仓 ID 获取上一次换刀的新刀具。"""
        cutter_position_no = request.query_params.get('cutter_position_no')
        warehouse_id = request.query_params.get('warehouse_id')

        if not cutter_position_no:
            return SuccessResponse(data=None)

        # 查询该刀位上一次换刀记录（排除当前开仓）
        # 修正：ToolChangeDetail 没有 new_tool 字段，新刀经反向关系
        # new_tool_record -> tool_instance -> tool_info 取得；原写法必然抛 FieldError。
        last_change = ToolChangeDetail.objects.filter(
            cutter_position_no=cutter_position_no,
            new_tool_record__isnull=False,
        ).select_related('new_tool_record__tool_instance__tool_info')

        # 如果提供了 warehouse_id，则排除当前开仓
        if warehouse_id:
            last_change = last_change.exclude(warehouse_id=warehouse_id)

        last_change = last_change.order_by('-create_datetime').first()

        instance = getattr(getattr(last_change, 'new_tool_record', None), 'tool_instance', None)
        if instance is not None:
            tool_info = instance.tool_info
            manufacturer = getattr(tool_info, 'manufacturer', '') or ''
            unit_price = getattr(tool_info, 'unit_price', None)
            return SuccessResponse(data={
                'id': instance.id,
                'tool_info_id': getattr(tool_info, 'id', None),
                'tool_type_name': instance.tool_type_name,
                'tool_number': instance.display_tool_no,
                'manufacturer': manufacturer,
                'unit_price': str(unit_price) if unit_price else '0',
                'tool_parent_type': instance.tool_parent_type,
                'label': f"{instance.tool_type_name}-{manufacturer}-{unit_price or 0}元",
            })

        return SuccessResponse(data=None)

    @action(detail=False, methods=['get'])
    def get_tools_by_type_code(self, request):
        """根据刀具类型编号获取刀具列表。"""
        tool_type_code = request.query_params.get('tool_type_code')
        if not tool_type_code:
            return SuccessResponse(data=[])

        tools = ToolInfo.objects.filter(tool_type_code=tool_type_code).values(
            'id', 'tool_type_name', 'tool_number', 'manufacturer', 'unit_price'
        )

        result = [
            {
                'value': tool['id'],
                'label': f"{tool['tool_type_name']} - {tool['manufacturer']} - {tool['unit_price']}元",
                'tool_type_name': tool['tool_type_name'],
                'tool_number': tool['tool_number'],
                'manufacturer': tool['manufacturer'],
                'unit_price': tool['unit_price']
            }
            for tool in tools
        ]
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def get_tools_by_type(self, request):
        """根据刀具类型获取刀具列表（兼容旧接口）。"""
        tool_type = request.query_params.get('tool_type')
        if not tool_type:
            return SuccessResponse(data=[])

        tools = ToolInfo.objects.filter(tool_parent_type=tool_type).values(
            'id', 'tool_type_name', 'tool_number'
        )

        result = [
            {
                'value': tool['id'],
                'label': f"{tool['tool_type_name']} ({tool['tool_number']})",
                'tool_type_name': tool['tool_type_name'],
                'tool_number': tool['tool_number']
            }
            for tool in tools
        ]
        return SuccessResponse(data=result)

    @action(detail=False, methods=['get'])
    def get_tool_number_counters(self, request):
        """获取指定项目下每个刀位已使用的最大刀具编号序号，供前端生成新编号使用。"""
        project_id = request.query_params.get('project_id')
        if not project_id:
            return SuccessResponse(data={})

        from django.db.models import Max
        import re

        records = ToolChangeDetail.objects.filter(
            warehouse__project_id=project_id,
            tool_number__isnull=False
        ).exclude(tool_number='').values('cutter_position_no', 'tool_number')

        counters = {}
        pattern = re.compile(r'R\d+-(.+)-(\d+)$')
        for r in records:
            m = pattern.match(r['tool_number'])
            if m:
                pos_no = m.group(1)
                seq = int(m.group(2))
                if counters.get(pos_no, 0) < seq:
                    counters[pos_no] = seq

        return SuccessResponse(data=counters)
