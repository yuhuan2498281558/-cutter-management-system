import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant.tools_manufacturer import compare_manufacturer_service
from application.shield.models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo, ToolChangeDetail,
    ToolInstance, WarehouseOpeningBasicInfo,
)


class ManufacturerToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='W2-MAKER', project_name='厂家测试')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='MAKER', shield_model='厂家机')
        cls.base_time = timezone.now()

    def detail(self, ring, position='1', **fields):
        opening, _ = WarehouseOpeningBasicInfo.objects.get_or_create(
            warehouse_id=f'MAKER-{ring}', defaults={'project': self.project, 'shield_model': self.machine,
            'ring_no': str(ring), 'open_time': self.base_time + timedelta(days=ring), 'summary_status': 'CONFIRMED'})
        detail = ToolChangeDetail(warehouse=opening, cutter_position_no=position, tool_parent_type='DISC',
                                  is_checked=True, is_replaced=True, **fields)
        ToolChangeDetail.objects.bulk_create([detail])
        return detail

    def pair(self, position='1', status='CONFIRMED', identity=True, install_ring=10, removal_ring=30, wear='偏磨'):
        instance = ToolInstance.objects.create(tool_uid=f'MAKER-{position}', display_tool_no=f'DISPLAY-{position}')
        installed = self.detail(install_ring, position, manufacturer='A', price=Decimal('10.10'))
        NewToolRecord.objects.create(tool_change_detail=installed, tool_instance=instance)
        removed = self.detail(removal_ring, position, manufacturer='B', price=Decimal('20.20'), wear_condition=wear)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance if identity else None,
                                     inspection_status=status)
        return installed, removed

    def query(self, **params):
        return json.loads(compare_manufacturer_service(json.dumps({'project_id': self.project.project_id,
                                                                    'min_samples': 1, **params})))

    def test_original_manufacturer_gets_old_wear_and_new_supplier_gets_amount(self):
        self.pair()
        result = self.query(ring_range=[30, 30])
        maker = result['service_by_install_manufacturer'][0]
        self.assertEqual(maker['manufacturer'], 'A')
        self.assertEqual(maker['confirmed_segment_count'], 1)
        self.assertEqual(maker['avg_service_rings'], 20)
        self.assertEqual(maker['abnormal_count'], 1)
        self.assertEqual(maker['abnormal_rate_pct'], 100)
        self.assertEqual(result['supply_by_new_manufacturer'], [
            {'manufacturer': 'B', 'install_count': 1, 'registered_amount_yuan': 20.2}])

    def test_pending_and_unknown_identity_are_excluded_from_mean(self):
        self.pair('1', status='CONFIRMED', wear='偏磨')
        self.pair('2', status='CLOSED', wear='正常')
        self.pair('3', status='PENDING_VENDOR_FEEDBACK')
        self.pair('4', identity=False)
        result = self.query(ring_range=[30, 30])
        maker = result['service_by_install_manufacturer'][0]
        self.assertEqual(maker['confirmed_segment_count'], 2)
        self.assertEqual(maker['classified_count'], 2)
        self.assertEqual(maker['abnormal_rate_pct'], 50)
        self.assertEqual(result['unconfirmed']['pending_feedback_count'], 1)
        self.assertEqual(result['unconfirmed']['no_confirmed_identity_count'], 1)

    def test_exact_manufacturer_filter_applies_to_each_attribution(self):
        self.pair()
        a = self.query(ring_range=[30, 30], manufacturers=['A'])
        b = self.query(ring_range=[30, 30], manufacturers=['B'])
        self.assertEqual(len(a['service_by_install_manufacturer']), 1)
        self.assertEqual(a['supply_by_new_manufacturer'], [])
        self.assertEqual(b['service_by_install_manufacturer'], [])
        self.assertEqual(b['supply_by_new_manufacturer'][0]['install_count'], 1)
        self.assertEqual(self.query(manufacturers=[' A '])['service_by_install_manufacturer'], [])

    def test_small_samples_and_unclassified_wear_are_not_zero_risk(self):
        self.pair(wear='待核对')
        result = self.query(min_samples=2, ring_range=[30, 30])
        self.assertEqual(result['service_by_install_manufacturer'], [])
        maker = result['insufficient_samples'][0]
        self.assertEqual(maker['classified_count'], 0)
        self.assertIsNone(maker['abnormal_rate_pct'])

    def test_competing_confirmed_removals_do_not_enter_mean(self):
        installed, _ = self.pair()
        conflict = self.detail(40, manufacturer='B', wear_condition='正常')
        OldToolRecord.objects.create(tool_change_detail=conflict,
                                     confirmed_tool_instance=installed.new_tool_record.tool_instance,
                                     inspection_status='CLOSED')
        result = self.query(ring_range=[30, 30])
        self.assertEqual(result['service_by_install_manufacturer'], [])
        self.assertEqual(result['unconfirmed']['no_confirmed_identity_count'], 1)
        self.assertIn('同一安装段存在多个已确认拆除记录', result['scope']['unconfirmed_reasons'])

    def test_in_service_without_removal_ring_and_zero_supply_price(self):
        instance = ToolInstance.objects.create(tool_uid='CURRENT', display_tool_no='CURRENT')
        installed = self.detail(100, manufacturer='A', price=0)
        NewToolRecord.objects.create(tool_change_detail=installed, tool_instance=instance)
        result = self.query()
        self.assertEqual(result['unconfirmed']['in_service_count'], 1)
        self.assertEqual(result['service_by_install_manufacturer'], [])
        self.assertEqual(result['supply_by_new_manufacturer'][0]['registered_amount_yuan'], 0)
        self.assertEqual(self.query(ring_range=[1, 2])['unconfirmed']['in_service_count'], 1)

    def test_invalid_parameters(self):
        for params in ({'manufacturers': 'A'}, {'manufacturers': ['']}, {'min_samples': 0},
                       {'min_samples': True}, {'ring_range': [30, 10]}, {'tool_type': 'RIPPER'}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
