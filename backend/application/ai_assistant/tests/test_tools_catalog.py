import json
from datetime import datetime, timezone as dt_timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from application.ai_assistant.tools import STRATUM_TYPE_NAMES
from application.ai_assistant.tools_catalog import query_data_catalog
from application.shield.longitudinal_ratios import AREA_LABELS
from application.shield.models import (
    TOOL_TYPES, MobileToolChangeTask, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo,
    ShieldTunnelingData, StratumBasicInfo, ToolChangeDetail, ToolCost, ToolInfo, WarehouseOpeningBasicInfo,
)
from application.shield.stratum_ratios import STRATUM_LABELS, stratum_label


class DataCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='CATALOG', project_name='目录')
        other = ProjectInfo.objects.create(project_id='CATALOG-OTHER', project_name='其他项目')
        machine = ShieldMachineBasicInfo.objects.create(shield_model_id='D1', shield_model='D1')
        first = WarehouseOpeningBasicInfo(warehouse_id='CAT-2', project=cls.project, shield_model=machine,
                                          ring_no='2', open_time=timezone.now(), summary_status='CONFIRMED')
        second = WarehouseOpeningBasicInfo(warehouse_id='CAT-10', project=cls.project, shield_model=machine,
                                           ring_no='10', open_time=timezone.now(), summary_status='DRAFT')
        outside = WarehouseOpeningBasicInfo(warehouse_id='CAT-100', project=other, shield_model=machine,
                                            ring_no='100', open_time=timezone.now())
        WarehouseOpeningBasicInfo.objects.bulk_create([first, second, outside])
        active = ToolChangeDetail(warehouse=first, cutter_position_no='01', tool_parent_type='DISC', is_replaced=True)
        invalid = ToolChangeDetail(warehouse=first, cutter_position_no='80', tool_parent_type='DISC', is_replaced=True)
        ToolChangeDetail.objects.bulk_create([
            active, invalid,
            ToolChangeDetail(warehouse=second, cutter_position_no='s1l', tool_parent_type='SCRAPER', is_checked=True),
            ToolChangeDetail(warehouse=second, cutter_position_no='2', tool_parent_type='DISC'),
            ToolChangeDetail(warehouse=outside, cutter_position_no='3', tool_parent_type='DISC', is_replaced=True),
        ])
        OldToolRecord.objects.bulk_create([
            OldToolRecord(tool_change_detail=active, inspection_status='CLOSED'),
            OldToolRecord(tool_change_detail=invalid, inspection_status='PENDING_VENDOR_FEEDBACK'),
        ])
        MobileToolChangeTask.objects.bulk_create([
            MobileToolChangeTask(warehouse=first, status='COMPLETED'),
            MobileToolChangeTask(warehouse=second, status='PENDING'),
            MobileToolChangeTask(warehouse=outside, status='RETURNED'),
        ])
        ShieldTunnelingData.objects.bulk_create([
            ShieldTunnelingData(project=cls.project, shield_machine=machine, ring_no='2', record_time=datetime(2021, 1, 2, tzinfo=dt_timezone.utc)),
            ShieldTunnelingData(project=cls.project, shield_machine=machine, ring_no='10', record_time=datetime(2021, 1, 3, tzinfo=dt_timezone.utc)),
            ShieldTunnelingData(project=other, shield_machine=machine, ring_no='100', record_time=timezone.now()),
        ])
        StratumBasicInfo.objects.bulk_create([
            StratumBasicInfo(project=cls.project, ring_no='2', stratum_type_codes='BOULDER,BOULDER',
                             longitudinal_type_ratios={'AREA_CLAY_SAND': 100}, stratum_type_ratios={'FILL': 100}),
            StratumBasicInfo(project=cls.project, ring_no='10', stratum_type_codes='CLAY_SAND',
                             longitudinal_type_ratios={'AREA_BOULDER': 10, 'AREA_CLAY_SAND': 90}),
            StratumBasicInfo(project=other, ring_no='100', stratum_type_codes='BOULDER',
                             longitudinal_type_ratios={'AREA_BOULDER': 100}),
        ])
        model = ToolInfo(tool_parent_type='DISC', tool_type_name='目录滚刀', tool_type_code='CAT-GD', tool_number='CAT-GD-1')
        ToolInfo.objects.bulk_create([model])
        ToolCost.objects.bulk_create([ToolCost(tool_info=model, cost_type=code, unit_price=100) for code in ('NEW_TOOL', 'REPAIR')])

    def query(self, **params):
        return json.loads(query_data_catalog(json.dumps({'project_id': 'CATALOG', **params})))

    def test_codes_and_names_come_from_shield_constants(self):
        result = self.query()
        self.assertEqual({row['code']: row['label'] for row in result['tool_types']}, dict(TOOL_TYPES))
        self.assertEqual({row['code']: row['label'] for row in result['stratum_codes']['legacy_labels']},
                         {code: stratum_label(code) for code in STRATUM_TYPE_NAMES})
        self.assertEqual({row['code']: row['label'] for row in result['stratum_codes']['longitudinal_area']}, AREA_LABELS)
        self.assertEqual({row['code']: row['label'] for row in result['stratum_codes']['cross_section']}, STRATUM_LABELS)
        self.assertEqual(result['tool_models'], [{'name': '目录滚刀', 'code': 'CAT-GD', 'tool_type': 'DISC'}])
        self.assertEqual(next(row['model_count'] for row in result['tool_types'] if row['code'] == 'DISC'), 1)
        legacy = {row['code']: row['ring_count'] for row in result['stratum_codes']['legacy_labels']}
        area = {row['code']: row['positive_ring_count'] for row in result['stratum_codes']['longitudinal_area']}
        self.assertEqual(legacy['BOULDER'], 1)
        self.assertEqual(area['AREA_BOULDER'], 1)

    def test_coverage_is_numeric_project_scoped_and_uses_active_observations(self):
        with CaptureQueriesContext(connection) as queries:
            result = self.query()
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries))
        coverage = result['data_coverage']
        self.assertEqual(coverage['tunneling']['record_count'], 2)
        self.assertEqual((coverage['tunneling']['ring_min'], coverage['tunneling']['ring_max']), (2, 10))
        self.assertTrue(coverage['tunneling']['time_min'].startswith('2021-01-02'))
        self.assertTrue(coverage['tunneling']['time_max'].startswith('2021-01-03'))
        self.assertEqual(coverage['openings']['count'], 2)
        self.assertEqual((coverage['openings']['ring_min'], coverage['openings']['ring_max']), (2, 10))
        self.assertEqual(coverage['openings']['summary_status_counts'], {'CONFIRMED': 1, 'DRAFT': 1})
        self.assertEqual(coverage['tool_change_observations'], {'observation_count': 2, 'replacement_count': 1})
        self.assertEqual(coverage['old_tool_repairs']['status_counts'], {'CLOSED': 1})
        self.assertEqual(coverage['mobile_tasks']['status_counts'], {'COMPLETED': 1, 'PENDING': 1})
        self.assertEqual(coverage['stratum'], {'ring_count': 2, 'ring_min': 2, 'ring_max': 10,
                                              'longitudinal_area_ring_count': 2, 'cross_section_ring_count': 1})
        self.assertEqual(coverage['cost_quotes'], {'new_tool_count': 1, 'repair_count': 1})

    def test_empty_project_keeps_shared_catalog_and_fixed_unavailable_list(self):
        result = self.query(project_id='ABSENT')
        self.assertEqual(result['data_coverage']['openings']['count'], 0)
        self.assertIsNone(result['data_coverage']['tunneling']['ring_min'])
        self.assertEqual(len(result['tool_models']), 1)
        self.assertEqual(result['data_coverage']['cost_quotes']['new_tool_count'], 1)
        self.assertEqual(result['not_available'], ['剩余寿命预测', '寿命预警', '备刀数量规划', '库存台账',
                                                  '实际采购和支付金额', '掘进原始点数据（库里只有分段均值）'])
        self.assertIn('error', json.loads(query_data_catalog('[]')))
