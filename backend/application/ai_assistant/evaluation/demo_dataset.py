"""建立公开、确定性的测试项目；换刀和报价来自现有 seed，逐环数据为合成值。"""
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from application.shield.models import (
    CutterPositionInfo, ProjectInfo, ShieldMachineBasicInfo, ShieldTunnelingData,
    StratumBasicInfo, ToolInfo, WarehouseOpeningBasicInfo,
)


def build_demo_dataset() -> str:
    positions = ([str(n) for n in range(1, 80)] + ["80A", "80B", "Y1", "Y3", "Y5"]
                 + [f"S{n}{side}" for n in range(1, 20) for side in "LR"])
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 固定自动时间戳；图片只存内存，避免 seed 向真实 MEDIA_ROOT 写文件。
    with patch("django.utils.timezone.now", return_value=fixed_time), override_settings(
            DEFAULT_FILE_STORAGE="django.core.files.storage.InMemoryStorage"):
        project, _ = ProjectInfo.objects.get_or_create(
            project_id="FIXED-QA-DEMO", defaults={"project_name": "固定题单合成演示项目"})
        if WarehouseOpeningBasicInfo.objects.filter(project=project).exists():
            return project.project_id
        shield, _ = ShieldMachineBasicInfo.objects.get_or_create(
            shield_model_id="FIXED-QA-SHIELD", defaults={"shield_model": "合成盾构机"})
        models = {}
        for kind in ("DISC", "SCRAPER"):
            for index in range(2):
                models[kind, index] = ToolInfo.objects.create(
                    tool_parent_type=kind, tool_type_name=f"DEMO-{kind}-{index + 1}",
                    tool_type_code=f"FIXED-{kind}-{index + 1}",
                    tool_number=f"FIXED-{kind}-{index + 1}", shield_machine=shield)
        CutterPositionInfo.objects.bulk_create([
            CutterPositionInfo(shield_machine=shield, cutter_position_no=position,
                               tool_type=(kind := "SCRAPER" if position.startswith("S") else "DISC"),
                               tool_info=models[kind, index % 2])
            for index, position in enumerate(positions)
        ])
        call_command("seed_tool_cost_demo", stdout=StringIO())
        call_command("seed_tool_change_demo", project_id=project.project_id,
                     shield_id=shield.shield_model_id, stdout=StringIO())
        # seed 默认留在草稿；确认合成开仓，使闭合服役段和里程得到实际覆盖。
        WarehouseOpeningBasicInfo.objects.filter(project=project).update(
            summary_status="CONFIRMED", summary_confirmed_at=fixed_time)
        StratumBasicInfo.objects.bulk_create([
            StratumBasicInfo(project=project, ring_no=str(ring),
                stratum_type_codes=("CLAY_SAND", "SOFT_HARD", "WEAK_GRANITE")[ring % 3],
                longitudinal_type_ratios={"AREA_CLAY_SAND": 20 + ring % 11,
                    "AREA_SOFT_SOIL": 10, "AREA_SOFT_HARD": 10, "AREA_WEAK_GRANITE": 20,
                    "AREA_BEDROCK_PROTRUSION": 35 - ring % 11, "AREA_BOULDER": 5})
            for ring in range(1, 488)
        ])
        ShieldTunnelingData.objects.bulk_create([
            ShieldTunnelingData(project=project, shield_machine=shield, ring_no=str(ring),
                record_time=fixed_time + timedelta(hours=ring), point_count=60,
                thrust=1000 + ring % 17 * 20 + (2000 if ring % 71 == 0 else 0),
                torque=200 + ring % 13 * 5, cutterhead_speed=1 + ring % 5 / 10,
                penetration=15 + ring % 7, advance_speed=20 + ring % 9,
                import_source="fixed-suite-synthetic")
            for ring in range(1, 488)
        ])
    return project.project_id
