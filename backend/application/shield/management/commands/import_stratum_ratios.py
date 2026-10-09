"""Import reviewed cross-section percentages. Default execution only previews."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from application.shield.stratum_ratios import validate_stratum_ratios


class Command(BaseCommand):
    help = '导入经核验的横断面岩层面积占比；默认仅预览'

    def add_arguments(self, parser):
        parser.add_argument('--json', required=True)
        parser.add_argument('--project', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        from application.shield.models import ProjectInfo, StratumBasicInfo
        try:
            payload = json.loads(Path(options['json']).read_text(encoding='utf-8-sig'))
            if payload.get('measurement_kind') != 'cross_section_area_percent':
                raise ValueError('缺少横断面面积百分数类型声明')
            if not payload.get('source') or not payload.get('method'):
                raise ValueError('缺少来源或提取方法')
            rings = payload['rings']
            if not isinstance(rings, dict) or not rings:
                raise ValueError('rings 必须为非空对象')
            validated = {}
            for ring, ratios in rings.items():
                if str(int(ring)) != ring or int(ring) < 0:
                    raise ValueError('环号必须为非负整数字符串')
                validated[ring] = validate_stratum_ratios(ratios)
            project = ProjectInfo.objects.get(project_id=options['project'])
        except (OSError, ValueError, KeyError, TypeError, ProjectInfo.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        # Use only fields existing before migration, so preview is available pre-deploy.
        existing = dict(StratumBasicInfo.objects.filter(project=project, ring_no__in=validated).values_list('ring_no', 'pk'))
        missing = sorted(set(validated) - set(existing), key=int)
        if missing:
            raise CommandError(f'以下环号无地层记录，拒绝部分导入：{missing[:20]}')
        known = sum(bool(ratios) and not ratios.get('UNRESOLVED', 0) for ratios in validated.values())
        self.stdout.write(f'共 {len(validated)} 环，完整占比 {known} 环，不完整或未知 {len(validated)-known} 环')
        if not options['apply']:
            self.stdout.write('DRY RUN，未写入；核验来源和占比后使用 --apply。')
            return
        with transaction.atomic():
            locked = list(StratumBasicInfo.objects.select_for_update().filter(pk__in=existing.values(), project=project).values_list('pk', flat=True))
            if len(locked) != len(existing):
                raise CommandError('记录在预览后发生变化，导入已取消')
            for ring, ratios in validated.items():
                StratumBasicInfo.objects.filter(pk=existing[ring], project=project).update(stratum_type_ratios=ratios)
        self.stdout.write(self.style.SUCCESS('岩层占比已导入。'))
