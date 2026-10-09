"""Import reviewed longitudinal areas without replacing original rock measurements."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from application.shield.longitudinal_ratios import (
    CLASSIFICATION_SCHEME, validate_longitudinal_ratios, validate_condition_alignment,
)


class Command(BaseCommand):
    help = '导入每环纵断面地层面积占比；默认仅预览'

    def add_arguments(self, parser):
        parser.add_argument('--json', required=True)
        parser.add_argument('--project', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        from application.shield.models import ProjectInfo, StratumBasicInfo
        try:
            payload = json.loads(Path(options['json']).read_text(encoding='utf-8-sig'))
            if payload.get('measurement_kind') != 'longitudinal_section_area_percent':
                raise ValueError('必须使用每环纵断面面积百分数，不能导入圆形断面比例')
            if payload.get('classification_scheme') != CLASSIFICATION_SCHEME:
                raise ValueError('必须使用图注子地层归并的六类面积版本，拒绝旧工程分区归属比例')
            if not all(payload.get(key) for key in ('source', 'source_sha256', 'method')):
                raise ValueError('缺少来源、指纹或提取方法')
            if payload.get('estimated') is not True:
                raise ValueError('必须注明图示估算')
            rings = payload['rings']
            if not isinstance(rings, dict) or not rings:
                raise ValueError('rings 必须为非空对象')
            validated = {}
            for ring, ratios in rings.items():
                if str(int(ring)) != ring or int(ring) < 1:
                    raise ValueError('环号必须为正整数字符串')
                validated[ring] = validate_longitudinal_ratios(ratios)
            project = ProjectInfo.objects.get(project_id=options['project'])
        except (OSError, ValueError, KeyError, TypeError, ProjectInfo.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        with transaction.atomic():
            rows = list(StratumBasicInfo.objects.select_for_update().filter(
                project=project, ring_no__in=validated).values_list('ring_no', 'pk', 'stratum_type_codes'))
            existing = {ring: pk for ring, pk, _ in rows}
            if len(existing) != len(rows):
                raise CommandError('存在重复环号，拒绝导入')
            missing = sorted(set(validated) - set(existing), key=int)
            if missing:
                raise CommandError(f'以下环号无记录，拒绝部分导入：{missing[:20]}')
            for ring, _, codes in rows:
                try:
                    validate_condition_alignment(validated[ring], [c.strip() for c in codes.split(',') if c.strip()])
                except ValueError as exc:
                    raise CommandError(f'环{ring}：{exc}') from exc
            self.stdout.write(f'共 {len(validated)} 环，仅更新纵断面占比；保留原岩性占比和工程条件。')
            if not options['apply']:
                self.stdout.write('DRY RUN，未写入。')
                return
            for ring, ratios in validated.items():
                StratumBasicInfo.objects.filter(pk=existing[ring]).update(longitudinal_type_ratios=ratios)
        self.stdout.write(self.style.SUCCESS('纵断面占比已导入。'))
