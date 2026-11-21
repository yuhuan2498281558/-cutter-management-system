import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant.tools_lifecycle import trace_tool_lifecycle
from application.shield.models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo, ToolChangeDetail,
    ToolInstance, WarehouseOpeningBasicInfo,
)


class LifecycleToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='W2-LIFE', project_name='追溯测试')
        cls.other = ProjectInfo.objects.create(project_id='W2-OTHER', project_name='其他项目')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='LIFE', shield_model='追溯机')
        cls.base_time = timezone.now()

    def detail(self, ring, position='1', project=None, **fields):
        project = project or self.project
        opening = WarehouseOpeningBasicInfo(warehouse_id=f'LIFE-{project.pk}-{ring}', project=project,
                                           shield_model=self.machine, ring_no=str(ring), summary_status='CONFIRMED',
                                           open_time=self.base_time + timedelta(days=ring))
        WarehouseOpeningBasicInfo.objects.bulk_create([opening])
        fields.setdefault('is_replaced', True)
        detail = ToolChangeDetail(warehouse=opening, cutter_position_no=position,
                                  tool_parent_type='DISC', is_checked=True, **fields)
        ToolChangeDetail.objects.bulk_create([detail])
        return detail

    def install(self, ring=15, instance=None, **fields):
        instance = instance or ToolInstance.objects.create(tool_uid=f'UID-{ring}', display_tool_no=f'DISPLAY-{ring}',
                                                           tool_parent_type='DISC', status='INSTALLED')
        detail = self.detail(ring, tool_number=instance.display_tool_no, **fields)
        NewToolRecord.objects.create(tool_change_detail=detail, tool_instance=instance)
        return instance, detail

    def query(self, ids, project=None):
        return json.loads(trace_tool_lifecycle(json.dumps({'project_id': (project or self.project).project_id,
                                                           'tool_ids': ids})))

    def test_uid_display_and_old_number_resolve_same_confirmed_segment(self):
        instance, _ = self.install()
        self.detail(40, is_replaced=False, tool_number=instance.display_tool_no, check_result='ATTENTION', wear_condition='偏磨')
        removed = self.detail(67, tool_number='NEW-67', check_result='NORMAL', wear_condition='断裂')
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance,
                                     old_tool_number='OLD-15', inspection_status='CONFIRMED', repair_price=100)
        result = self.query(['UID-15', 'DISPLAY-15', 'OLD-15'])['results']
        self.assertEqual([r['resolved_by'] for r in result], ['tool_uid', 'display_tool_no', 'old_tool_number'])
        for item in result:
            self.assertEqual(item['instance']['tool_uid'], 'UID-15')
            self.assertEqual(len(item['service_segments']), 1)
            segment = item['service_segments'][0]
            self.assertEqual((segment['install_ring'], segment['removal_ring'], segment['service_rings']), (15, 67, 52))
            self.assertEqual(segment['removal_basis'], 'confirmed')
            self.assertEqual(segment['repair']['inspection_status'], 'CONFIRMED')
            self.assertEqual([r['ring_no'] for r in segment['inspections']], [40, 67])
            self.assertFalse(item['truncated'])

    def test_instance_without_install_and_in_service_are_not_missing_tools(self):
        ToolInstance.objects.create(tool_uid='ORPHAN', display_tool_no='45-4-01')
        self.install(400)
        orphan, current = self.query(['45-4-01', 'UID-400'])['results']
        self.assertEqual(orphan['service_segments'], [])
        self.assertIn('存在这把刀的实例，但没有安装记录', orphan['missing_steps'])
        segment = current['service_segments'][0]
        self.assertEqual(segment['removal_basis'], 'in_service')
        self.assertIsNone(segment['service_rings'])
        self.assertIsNone(segment['removal_ring'])

    def test_suggested_and_pending_confirmed_identity_do_not_claim_lifetime(self):
        instance, _ = self.install()
        removed = self.detail(67)
        record = OldToolRecord.objects.create(tool_change_detail=removed, suggested_tool_instance=instance,
                                              old_tool_number='SUGGESTED', inspection_status='CONFIRMED')
        segment = self.query(['UID-15'])['results'][0]['service_segments'][0]
        self.assertEqual(segment['removal_basis'], 'suggested')
        self.assertIsNone(segment['service_rings'])
        record.confirmed_tool_instance = instance
        record.inspection_status = 'PENDING_VENDOR_FEEDBACK'
        record.save()
        result = self.query(['UID-15'])['results'][0]
        self.assertEqual(result['service_segments'][0]['removal_basis'], 'confirmed')
        self.assertIsNone(result['service_segments'][0]['service_rings'])
        self.assertIn('拆下后厂家还没反馈', result['missing_steps'])

    def test_old_number_only_never_borrows_new_installation(self):
        _, detail = self.install(30)
        OldToolRecord.objects.create(tool_change_detail=detail, old_tool_number='BASE-GD-17', repair_price=0)
        result = self.query(['BASE-GD-17'])['results'][0]
        self.assertEqual(result['resolved_by'], 'old_tool_number')
        self.assertIsNone(result['instance'])
        segment = result['service_segments'][0]
        self.assertIsNone(segment['install_ring'])
        self.assertIsNone(segment['service_rings'])
        self.assertEqual(segment['removal_ring'], 30)
        self.assertEqual(segment['repair']['repair_price_yuan'], 0)

    def test_other_project_installation_and_repair_are_not_returned(self):
        instance, _ = self.install(project=self.other)
        removed = self.detail(67, project=self.other)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance,
                                     old_tool_number='OTHER-OLD', inspection_status='CLOSED', repair_price=123)
        result = self.query(['UID-15', 'OTHER-OLD'])['results']
        self.assertEqual(result[0]['service_segments'], [])
        self.assertTrue(any('指定项目' in s for s in result[0]['missing_steps']))
        self.assertEqual(result[1]['resolved_by'], 'not_found')
        self.assertEqual(result[1]['service_segments'], [])

    def test_detail_number_fallback_and_segment_limit(self):
        self.detail(10, tool_number='LEGACY')
        self.detail(20)
        result = self.query(['LEGACY'])['results'][0]
        self.assertEqual(result['resolved_by'], 'tool_number')
        self.assertEqual(result['service_segments'][0]['removal_basis'], 'inferred')
        self.assertIsNone(result['service_segments'][0]['service_rings'])
        instance = ToolInstance.objects.create(tool_uid='REPEAT', display_tool_no='REPEAT')
        for ring in range(100, 121):
            self.install(ring, instance=instance)
        repeated = self.query(['REPEAT'])['results'][0]
        self.assertTrue(repeated['truncated'])
        self.assertEqual(len(repeated['service_segments']), 20)
        self.assertEqual(repeated['service_segments'][0]['install_ring'], 101)

    def test_invalid_tool_ids(self):
        for ids in ([], [''] , [1], ['a'] * 21, 'UID-15'):
            with self.subTest(ids=ids):
                self.assertIn('error', self.query(ids))
