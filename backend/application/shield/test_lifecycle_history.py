from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from .models import (ProjectInfo, ShieldMachineBasicInfo, WarehouseOpeningBasicInfo,
                     ToolChangeDetail, StratumBasicInfo, NewToolRecord, ToolInstance, OldToolRecord)
from .mobile_views import ToolLifecycleViewSet
from .lifecycle_history import build_position_history


class LifecycleHistoryTests(TestCase):
    def setUp(self):
        self.project = ProjectInfo.objects.create(project_id='LIFE', project_name='测试')
        self.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='LIFE', shield_model='测试机')
        self.time = timezone.now()

    def detail(self, ring, *, minute=0, position='1', replacement=True, project=None):
        opening = WarehouseOpeningBasicInfo(project=project or self.project, shield_model=self.machine,
            warehouse_id=f'L-{WarehouseOpeningBasicInfo.objects.count()}', ring_no=str(ring),
            open_time=self.time + timedelta(minutes=minute))
        WarehouseOpeningBasicInfo.objects.bulk_create([opening])
        detail = ToolChangeDetail(warehouse=opening, cutter_position_no=position, tool_parent_type='DISC',
                                  tool_number=f'new-{opening.pk}', is_replaced=replacement)
        ToolChangeDetail.objects.bulk_create([detail])
        return detail

    def history(self):
        return build_position_history(self.project.pk, self.machine.pk, '1')

    def test_numeric_order_same_ring_and_inherited_inspection(self):
        self.detail(10)
        first = self.detail(2)
        self.detail(10, minute=1)
        self.detail(11, minute=2, replacement=False)
        items = self.history()
        self.assertEqual([x['install_ring_no'] for x in items], ['2', '10', '10'])
        self.assertEqual(items[0]['service_id'], first.pk)
        self.assertEqual(items[1]['usage_rings'], 0)
        self.assertEqual(items[2]['exposure_end_ring'], 11)

    def test_scope_and_complete_interval_not_removal_point(self):
        self.detail(1)
        self.detail(4, minute=3)
        other = ProjectInfo.objects.create(project_id='OTHER', project_name='其他')
        self.detail(2, minute=1, project=other)
        self.detail(2, minute=1, position='2')
        StratumBasicInfo.objects.create(project=self.project, ring_no='2', stratum_type_codes='A', stratum_type_ratios={'A': 100})
        StratumBasicInfo.objects.create(project=self.project, ring_no='4', stratum_type_codes='B')
        items = self.history()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['stratum_exposure']['encountered_codes'], ['A'])
        self.assertEqual(len(items[0]['stratum_exposure']['encountered_names']), 1)
        self.assertEqual(items[0]['stratum_exposure']['engineering_condition_codes'], ['A', 'B'])
        self.assertEqual(items[0]['stratum_exposure']['missing_rings'], 2)

    def test_unknown_install_and_confirmed_identity_conflict(self):
        self.detail(1, replacement=False)
        start = self.detail(2, minute=1)
        end = self.detail(3, minute=2)
        instance = ToolInstance.objects.create(tool_uid='real', display_tool_no='real')
        other = ToolInstance.objects.create(tool_uid='other', display_tool_no='other')
        NewToolRecord.objects.create(tool_change_detail=start, tool_instance=instance)
        OldToolRecord.objects.create(tool_change_detail=end, confirmed_tool_instance=other)
        items = self.history()
        self.assertIsNone(items[0]['stratum_exposure'])
        self.assertTrue(items[1]['identity_conflict'])
        self.assertIsNone(items[1]['stratum_exposure'])

    def test_action_rejects_inactive_and_requires_scope(self):
        view = ToolLifecycleViewSet.as_view({'get': 'position_history'}, authentication_classes=[], permission_classes=[])
        for params in ({}, {'project': self.project.pk, 'shield_machine': self.machine.pk, 'position': 'G1L'}):
            response = view(APIRequestFactory().get('/', params))
            self.assertNotEqual(response.data['code'], 2000)

    def test_confirmed_repair_status_and_reinstallation_are_separate_services(self):
        first = self.detail(1)
        second = self.detail(3, minute=1)
        instance = ToolInstance.objects.create(tool_uid='reuse', display_tool_no='reuse')
        NewToolRecord.objects.create(tool_change_detail=first, tool_instance=instance)
        NewToolRecord.objects.create(tool_change_detail=second, tool_instance=instance)
        OldToolRecord.objects.create(tool_change_detail=second, confirmed_tool_instance=instance,
                                     inspection_status='CLOSED', disposition='REPAIRABLE')
        items = self.history()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['id'], items[1]['id'])
        self.assertNotEqual(items[0]['service_id'], items[1]['service_id'])
        self.assertEqual(items[0]['status'], 'REPAIRED_CLOSED')
        self.assertEqual(items[1]['status'], 'INSTALLED')

    def test_backfilled_entry_time_cannot_reverse_service_pairing(self):
        first = self.detail(2)
        second = self.detail(10, minute=1)
        for detail, delay in [(first, 100), (second, 2)]:
            instance = ToolInstance.objects.create(tool_uid=f't-{detail.pk}', display_tool_no=f't-{detail.pk}')
            NewToolRecord.objects.create(tool_change_detail=detail, tool_instance=instance,
                                         installed_at=self.time + timedelta(minutes=delay))
        items = self.history()
        self.assertEqual([item['install_ring_no'] for item in items], ['2', '10'])
        self.assertEqual(items[0]['remove_ring_no'], '10')
        self.assertEqual(items[0]['usage_rings'], 8)

    def test_legacy_cannot_inherit_confirmed_other_instance_repair(self):
        self.detail(1)
        end = self.detail(3, minute=1)
        other = ToolInstance.objects.create(tool_uid='not-legacy', display_tool_no='not-legacy')
        OldToolRecord.objects.create(tool_change_detail=end, confirmed_tool_instance=other,
                                     inspection_status='CLOSED', disposition='SCRAP')
        item = self.history()[0]
        self.assertEqual(item['status'], 'REMOVED')
        self.assertTrue(item['identity_conflict'])
        self.assertIsNone(item['stratum_exposure'])
