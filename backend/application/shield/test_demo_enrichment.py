"""Demo-enrichment safety checks; Django uses only its isolated test database."""
from datetime import datetime, time
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .analysis_metrics import confirmed_service_segments
from .cutter_position_scope import sort_cutter_position_items
from .demo_profiles import PROFILES, installation_price, profile_for, repair_price, wear_values
from .management.commands.enrich_analysis_demo import (
    ALLOWED, CHECKED_MARKER, MODELS, NEW_MARKER, OLD_MARKER, REPLACED_MARKER, encoded,
)
from .management.commands.seed_tool_change_demo import Command as SeedCommand, OPENINGS, WEAR_CONDITIONS
from .models import (
    CutterPositionInfo, NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo,
    ToolChangeDetail, ToolInfo, ToolInstance, WarehouseOpeningBasicInfo,
)


class DemoProfileTests(SimpleTestCase):
    def test_profiles_are_deterministic_varied_and_explicitly_simulated(self):
        self.assertEqual(len({p['name'] for p in PROFILES}), 8)
        for profile in PROFILES:
            self.assertIn('模拟', profile['name'])
            self.assertIn('模拟', profile['brand'])
            self.assertTrue(5600 <= profile['disc_price'] <= 8500)
            self.assertTrue(1600 <= profile['scraper_price'] <= 3300)
            self.assertTrue(0.45 <= profile['normal_probability'] <= 0.8)
        samples = [profile_for(f'instance-{i}') for i in range(200)]
        self.assertEqual(len({p['name'] for p in samples}), 8)
        self.assertEqual(samples, [profile_for(f'instance-{i}') for i in range(200)])
        fresh = profile_for('copy'); fresh['name'] = 'edited'
        self.assertNotEqual(profile_for('copy')['name'], 'edited')

    def test_prices_vary_across_instances_and_periods_without_changing_inputs(self):
        for profile in PROFILES:
            for parent in ('DISC', 'SCRAPER'):
                prices = [installation_price(profile, parent, str(i), 100) for i in range(30)]
                self.assertGreater(len(set(prices)), 25)
                self.assertTrue(all(isinstance(p, Decimal) and p > 0 and p.as_tuple().exponent == -2 for p in prices))
                self.assertEqual(prices[0], installation_price(profile, parent, '0', 100))
                self.assertNotEqual(prices[0], installation_price(profile, parent, '0', 400))

    def test_wear_sampling_has_both_states_and_consistent_damage_and_repair_fields(self):
        for profile in PROFILES:
            normal = checked_normal = 0
            for index in range(300):
                for parent in ('DISC', 'SCRAPER'):
                    values = wear_values(profile, parent, index, 100 + index)
                    self.assertEqual(values, wear_values(profile, parent, index, 100 + index))
                    self.assertNotIn('disposition', values)
                    self.assertNotIn('inspection_status', values)
                    if values['wear_condition'] == '正常':
                        normal += 1
                        self.assertFalse(values['ring_damage'])
                        self.assertFalse(values['bearing_failure_reasons'])
                        self.assertFalse(values['hub_failure_reasons'])
                        self.assertFalse(values['scraper_broken'])
                        self.assertFalse(values['scraper_chipped'])
                        self.assertFalse(values['scraper_detached'])
                        self.assertEqual(repair_price(profile, parent, index, 100 + index), 0)
                    if values['bearing_failed']:
                        self.assertEqual(values['wear_condition'], '轴承损坏')
                    if values['scraper_broken']:
                        self.assertEqual(values['wear_condition'], '断裂')
                    checked = wear_values(profile, parent, index, 100 + index, checked_only=True)
                    checked_normal += checked['wear_condition'] == '正常'
                    self.assertIn(checked['wear_condition'], ('正常', '偏磨', '中度磨损'))
            self.assertTrue(0.35 < normal / 600 < 0.9)
            self.assertGreater(checked_normal, normal)


class DemoEnrichmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='ENRICH-TEST', project_name='模拟测试工程')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='ENRICH-TEST', shield_model='测试盾构机')
        tool_infos = {}
        for parent in ('DISC', 'SCRAPER'):
            row = ToolInfo(tool_parent_type=parent, tool_type_name=f'{parent}测试型', tool_number=f'ENRICH-{parent}')
            ToolInfo.objects.bulk_create([row]); tool_infos[parent] = row
        positions = []
        for code in ('1', '2', '3', '4', 'S1L', 'S1R', 'S2L', 'S2R'):
            parent = 'SCRAPER' if code.startswith('S') else 'DISC'
            positions.append(CutterPositionInfo(shield_machine=cls.machine, cutter_position_no=code,
                                                tool_type=parent, tool_info=tool_infos[parent]))
        CutterPositionInfo.objects.bulk_create(positions)
        positions = sort_cutter_position_items(positions, key=lambda p: p.cutter_position_no)
        state = {}; cls.replacement_ids = []; cls.checked_ids = []; cls.pending_ids = []
        for index, (ring, day) in enumerate(OPENINGS[:3]):
            opening = WarehouseOpeningBasicInfo(project=cls.project, shield_model=cls.machine, ring_no=str(ring),
                warehouse_id=f'ENRICH-{ring}', open_time=timezone.make_aware(datetime.combine(day, time(8, 30))),
                summary_status='CONFIRMED')
            WarehouseOpeningBasicInfo.objects.bulk_create([opening])
            replaced, checked = SeedCommand()._inspection_plan(positions, index)
            selected = replaced + checked
            for position in positions:
                active = position in selected
                slot = selected.index(position) if active else None
                replacement = position in replaced
                wear = WEAR_CONDITIONS[(index + slot + (4 if replacement else 0)) % len(WEAR_CONDITIONS)] if active else ''
                detail = ToolChangeDetail(warehouse=opening, cutter_position=position, cutter_position_no=position.cutter_position_no,
                    tool_parent_type=position.tool_type, is_checked=active, is_replaced=replacement,
                    checked_at=opening.open_time if active else None, mobile_status='SAVED' if active else 'PENDING',
                    wear_condition=wear, blade_wear_amount=4.5 if active else None, price=Decimal('6200') if replacement else None,
                    manufacturer='Original maker' if replacement else '', brand='Original brand' if replacement else '',
                    replacement_type='COMPLETE' if replacement else None, check_result='NORMAL' if replacement else 'NOT_REPLACED' if active else 'PENDING',
                    remark='已完成现场检查并更换' if replacement else '已检查，本次无需更换' if active else '')
                ToolChangeDetail.objects.bulk_create([detail])
                if replacement:
                    serial = index * 100 + slot + 1
                    instance = ToolInstance.objects.create(tool_uid=f'DEMO-{ring}-{position.cutter_position_no}-{serial:03d}',
                        display_tool_no=f'DEMO-TOOL-{ring}-{slot}', tool_info=position.tool_info,
                        tool_parent_type=position.tool_type, status='INSTALLED')
                    ToolChangeDetail.objects.filter(pk=detail.pk).update(tool_number=instance.display_tool_no)
                    NewToolRecord.objects.create(tool_change_detail=detail, tool_instance=instance, installed_at=opening.open_time,
                                                remark='结构化新刀字段测试记录', ring_manufacturer='Original maker')
                    OldToolRecord.objects.create(tool_change_detail=detail, confirmed_tool_instance=state.get(position.cutter_position_no),
                        suggested_tool_instance=state.get(position.cutter_position_no), inspection_status='CONFIRMED', disposition='REPAIRABLE',
                        wear_condition=wear, repair_price=Decimal('1200'), ring_damage=['FRACTURE'], bearing_failed=True,
                        bearing_failure_reasons=['SEAL_FAILURE'], remark='旧刀厂家返修结构化字段测试记录')
                    state[position.cutter_position_no] = instance
                    cls.replacement_ids.append(detail.pk)
                elif active:
                    cls.checked_ids.append(detail.pk)
                else:
                    cls.pending_ids.append(detail.pk)

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backup = Path(self.directory.name) / 'original.json'

    def command(self, **options):
        if options.get('apply') and not options.get('restore') and 'expected_digest' not in options:
            options['expected_digest'] = self.command()['plan_digest']
        out = StringIO()
        call_command('enrich_analysis_demo', project_pk=self.project.pk, shield_pk=self.machine.pk, stdout=out, **options)
        return json.loads(out.getvalue())

    def snapshot(self):
        models = (*ALLOWED, ToolInstance, WarehouseOpeningBasicInfo, CutterPositionInfo, ToolInfo)
        return {model._meta.label: {row['id']: encoded(row) for row in model.objects.order_by('pk').values()}
                for model in models}

    def test_default_preview_never_writes_or_creates_backup(self):
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            report = self.command()
        self.assertGreater(report['changed_rows'], 0)
        self.assertFalse(report['applied'])
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('UPDATE ', 'INSERT ', 'DELETE ')) for q in queries))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.backup.exists())

    def test_apply_requires_new_backup_and_never_overwrites_one(self):
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.command(apply=True)
        self.assertEqual(before, self.snapshot())

    def test_apply_rejects_missing_or_outdated_review_digest(self):
        before = self.snapshot()
        for digest in (None, '0' * 64):
            with self.subTest(digest=digest), self.assertRaisesMessage(CommandError, 'expected-digest'):
                self.command(apply=True, backup=str(self.backup), expected_digest=digest)
        self.assertFalse(self.backup.exists()); self.assertEqual(before, self.snapshot())

    def test_backup_file_is_never_overwritten(self):
        before = self.snapshot()
        self.backup.write_text('preserve existing backup', encoding='utf-8')
        with self.assertRaises((FileExistsError, CommandError)):
            self.command(apply=True, backup=str(self.backup))
        self.assertEqual(self.backup.read_text(encoding='utf-8'), 'preserve existing backup')
        self.assertEqual(before, self.snapshot())

    def test_apply_synchronizes_suppliers_wear_and_preserves_all_identity_and_state_fields(self):
        before = self.snapshot()
        report = self.command(apply=True, backup=str(self.backup))
        self.assertTrue(report['applied']); self.assertTrue(self.backup.exists())
        after = self.snapshot()
        for label, rows in before.items():
            model = next((model for model in ALLOWED if model._meta.label == label), None)
            allowed = ALLOWED.get(model, set())
            for pk, old in rows.items():
                self.assertEqual({k: v for k, v in old.items() if k not in allowed},
                                 {k: v for k, v in after[label][pk].items() if k not in allowed})
        for detail in ToolChangeDetail.objects.filter(pk__in=self.replacement_ids).select_related('new_tool_record', 'old_tool_record'):
            self.assertIn('模拟', detail.manufacturer)
            self.assertEqual(detail.remark, REPLACED_MARKER)
            self.assertEqual(detail.old_tool_record.remark, OLD_MARKER)
            self.assertEqual(detail.new_tool_record.remark, NEW_MARKER)
            self.assertEqual(detail.wear_condition, detail.old_tool_record.wear_condition)
            field = 'ring_manufacturer' if detail.tool_parent_type == 'DISC' else 'scraper_manufacturer'
            self.assertEqual(getattr(detail.new_tool_record, field), detail.manufacturer)
            self.assertGreater(detail.price, 0)
        for pk in self.pending_ids:
            self.assertEqual(before[ToolChangeDetail._meta.label][pk], after[ToolChangeDetail._meta.label][pk])
        self.assertTrue(all(r.remark == CHECKED_MARKER for r in ToolChangeDetail.objects.filter(pk__in=self.checked_ids)))

    def test_existing_old_install_profile_drives_removal_wear_and_price(self):
        originals = list(ToolChangeDetail.objects.filter(pk__in=self.replacement_ids).select_related('warehouse'))
        spans = {r['installation_detail_id']: r['service_rings'] for r in confirmed_service_segments(originals) if r['paired']}
        linked = OldToolRecord.objects.exclude(confirmed_tool_instance=None).select_related('tool_change_detail__warehouse').first()
        self.assertIsNotNone(linked)
        previous = NewToolRecord.objects.get(tool_instance_id=linked.confirmed_tool_instance_id)
        profile = profile_for(previous.tool_instance.tool_uid, spans.get(previous.tool_change_detail_id))
        detail = linked.tool_change_detail
        key = detail.new_tool_record.tool_instance.tool_uid
        expected = wear_values(profile, detail.tool_parent_type, key, int(detail.warehouse.ring_no))
        self.command(apply=True, backup=str(self.backup))
        linked.refresh_from_db(); detail.refresh_from_db()
        self.assertEqual(detail.wear_condition, expected['wear_condition'])
        self.assertEqual(linked.wear_condition, expected['wear_condition'])
        self.assertEqual(linked.repair_price, repair_price(profile, detail.tool_parent_type, key, int(detail.warehouse.ring_no)))

    def test_unmarked_business_rows_are_preserved(self):
        pk = self.replacement_ids[-1]
        NewToolRecord.objects.filter(tool_change_detail_id=pk).update(remark='人工业务记录')
        OldToolRecord.objects.filter(tool_change_detail_id=pk).update(
            confirmed_tool_instance=None, suggested_tool_instance=None)
        ToolChangeDetail.objects.filter(pk=self.checked_ids[-1]).update(remark='人工检查记录')
        before = self.snapshot()
        self.command(apply=True, backup=str(self.backup))
        after = self.snapshot()
        for model in (ToolChangeDetail, NewToolRecord, OldToolRecord):
            ids = [pk] if model is ToolChangeDetail else list(model.objects.filter(tool_change_detail_id=pk).values_list('pk', flat=True))
            for row_id in ids:
                self.assertEqual(before[model._meta.label][row_id], after[model._meta.label][row_id])
        self.assertEqual(before[ToolChangeDetail._meta.label][self.checked_ids[-1]], after[ToolChangeDetail._meta.label][self.checked_ids[-1]])

    def test_repeated_apply_is_a_zero_write_noop_and_preserves_original_backup(self):
        self.command(apply=True, backup=str(self.backup)); backup_text = self.backup.read_bytes(); before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            report = self.command(apply=True)
        self.assertEqual(report['changed_rows'], 0)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith('UPDATE ') for q in queries))
        self.assertEqual(self.snapshot(), before); self.assertEqual(self.backup.read_bytes(), backup_text)

    def test_restore_preview_and_apply_restore_exact_original_rows(self):
        before = self.snapshot(); self.command(apply=True, backup=str(self.backup)); enriched = self.snapshot()
        report = self.command(restore=str(self.backup)); self.assertFalse(report['applied'])
        self.assertEqual(self.snapshot(), enriched)
        report = self.command(restore=str(self.backup), apply=True); self.assertTrue(report['applied'])
        self.assertEqual(self.snapshot(), before)

    def test_restore_after_late_manual_edit_rejects_and_rolls_back_earlier_rows(self):
        self.command(apply=True, backup=str(self.backup))
        last = json.loads(self.backup.read_text(encoding='utf-8'))['rows'][-1]
        MODELS[last['model']].objects.filter(pk=last['id']).update(remark='后续人工改动')
        edited = self.snapshot()
        with self.assertRaises(CommandError):
            self.command(restore=str(self.backup), apply=True)
        self.assertEqual(self.snapshot(), edited)

    def test_external_reference_rejects_entire_enrichment(self):
        first = NewToolRecord.objects.get(tool_change_detail_id=self.replacement_ids[0])
        extra_opening = WarehouseOpeningBasicInfo(project=self.project, shield_model=self.machine, ring_no='999',
            warehouse_id='OUTSIDE', open_time=timezone.now(), summary_status='CONFIRMED')
        WarehouseOpeningBasicInfo.objects.bulk_create([extra_opening])
        detail = ToolChangeDetail(warehouse=extra_opening, cutter_position_no='1', tool_parent_type='DISC', is_replaced=True)
        ToolChangeDetail.objects.bulk_create([detail])
        OldToolRecord.objects.create(tool_change_detail=detail, confirmed_tool_instance=first.tool_instance)
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, 'outside the target set'):
            self.command(apply=True, backup=str(self.backup))
        self.assertEqual(self.snapshot(), before); self.assertFalse(self.backup.exists())

    def test_edited_seed_identity_or_wear_refuses_before_writes(self):
        ToolChangeDetail.objects.filter(pk=self.replacement_ids[-1]).update(wear_condition='人工纠正')
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, 'wear was edited'):
            self.command(apply=True, backup=str(self.backup))
        self.assertEqual(self.snapshot(), before); self.assertFalse(self.backup.exists())
