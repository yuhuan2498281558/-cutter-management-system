import json
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant.tools_repairs import query_old_tool_repairs
from application.shield.models import (
    OldToolPhoto, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo, ToolChangeDetail, WarehouseOpeningBasicInfo,
)


class RepairToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='W2-REPAIR', project_name='返修测试')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='REPAIR', shield_model='返修机')

    def record(self, ring, position='1', replaced=True, **fields):
        opening = WarehouseOpeningBasicInfo(warehouse_id=f'REPAIR-{ring}', project=self.project,
                                           shield_model=self.machine, ring_no=str(ring), open_time=timezone.now())
        WarehouseOpeningBasicInfo.objects.bulk_create([opening])
        detail = ToolChangeDetail(warehouse=opening, cutter_position_no=position, tool_parent_type='DISC',
                                  is_checked=True, is_replaced=replaced)
        ToolChangeDetail.objects.bulk_create([detail])
        return OldToolRecord.objects.create(tool_change_detail=detail, old_tool_number=f'OLD-{ring}', **fields)

    def query(self, **params):
        return json.loads(query_old_tool_repairs(json.dumps({'project_id': self.project.project_id, **params})))

    def test_scrap_suggestion_and_confirmed_statuses_are_separate(self):
        self.record(10, inspection_status='PENDING_VENDOR_FEEDBACK', disposition='SCRAP', repair_price=0)
        self.record(20, inspection_status='CONFIRMED', disposition='REPAIRABLE', repair_price=Decimal('12.30'))
        self.record(30, inspection_status='CLOSED', disposition='SCRAP', repair_price=Decimal('2.40'))
        result = self.query()
        self.assertEqual(result['status_counts'], {'PENDING_VENDOR_FEEDBACK': 1, 'CONFIRMED': 1, 'CLOSED': 1})
        self.assertEqual(result['scrapped_count'], 1)
        self.assertEqual(result['scrap_suggestion_count'], 1)
        self.assertEqual(result['registered_repair_amount']['confirmed_yuan'], 14.7)
        self.assertEqual(result['registered_repair_amount']['pending_yuan'], 0)
        self.assertEqual(result['disposition_by_status']['CONFIRMED'], {'REPAIRABLE': 1})
        self.assertEqual(self.query(inspection_status='PENDING_VENDOR_FEEDBACK')['scrapped_count'], 0)
        self.assertEqual(self.query(inspection_status='CLOSED')['scope']['record_count'], 1)

    def test_zero_missing_prices_and_photo_reason_multiplication(self):
        record = self.record(100, inspection_status='CONFIRMED', repair_price=Decimal('100.05'),
                             bearing_failure_reasons=['FATIGUE_DAMAGE', 'SEAL_FAILURE'], ring_damage=['CHIP'])
        OldToolPhoto.objects.bulk_create([OldToolPhoto(old_tool_record=record, image=f'fake-{i}.jpg') for i in (1, 2)])
        self.record(20, repair_price=0)
        self.record(9, repair_price=None)
        result = self.query(list_limit=1)
        self.assertEqual(result['scope']['record_count'], 3)
        self.assertEqual(result['registered_repair_amount'], {'confirmed_yuan': 100.05, 'pending_yuan': 0,
                         'priced_count': 2, 'zero_price_count': 1, 'missing_price_count': 1})
        self.assertEqual(result['photo_count'], 2)
        self.assertEqual(result['records'][0]['photo_count'], 2)
        self.assertEqual(result['records'][0]['repair_price_yuan'], 100.05)
        self.assertEqual(len(result['records'][0]['failure_reasons']), 3)
        fatigue = next(r for r in result['failure_reasons'] if r['reason'] == 'FATIGUE_DAMAGE')
        self.assertEqual(fatigue, {'component': '轴承', 'reason': 'FATIGUE_DAMAGE', 'label': '疲劳损坏', 'record_count': 1})
        missing = self.query(ring_range=[9, 9])['records'][0]
        self.assertIsNone(missing['repair_price_yuan'])
        self.assertIsNone(missing['feedback_time'])

    def test_only_active_replacements_and_selected_disposition_are_counted(self):
        self.record(10, disposition='SCRAP')
        self.record(20, position='G1R', disposition='SCRAP', repair_price=999)
        self.record(30, replaced=False, disposition='SCRAP', repair_price=999)
        self.record(40, disposition='REPAIRABLE')
        result = self.query(disposition='SCRAP')
        self.assertEqual(result['scope']['record_count'], 1)
        self.assertEqual(result['scope']['data_ring_range'], [10, 10])

    def test_invalid_status_and_scope_return_errors(self):
        for params in ({'inspection_status': 'DONE'}, {'inspection_status': []}, {'disposition': 'KEEP'}, {'ring_range': [5, 1]},
                       {'list_limit': 0}, {'tool_type': 'RIPPER'}, {'shield_machine_id': 'bad'}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
        self.assertIn('CONFIRMED', self.query(inspection_status='DONE')['error'])
        self.assertIn('error', json.loads(query_old_tool_repairs('null')))
