import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from application.ai_assistant.tools_costs import query_registered_amounts, query_tool_cost_catalog
from application.shield.models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo, ToolChangeDetail,
    ToolCost, ToolInfo, ToolInstance, WarehouseOpeningBasicInfo,
)


class ToolCostCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        model = ToolInfo(tool_parent_type='SCRAPER', tool_type_name='可换刮刀', tool_type_code='GG-1', tool_number='CAT-1')
        other = ToolInfo(tool_parent_type='DISC', tool_type_name='滚刀', tool_type_code='GD-1', tool_number='CAT-2')
        ToolInfo.objects.bulk_create([model, other])
        ToolCost.objects.bulk_create([
            ToolCost(tool_info=model, cost_type='NEW_TOOL', manufacturer='甲厂', brand='甲牌', unit_price=100, inventory=88),
            ToolCost(tool_info=model, cost_type='NEW_TOOL', manufacturer='乙厂', brand='乙牌', unit_price=300),
            ToolCost(tool_info=model, cost_type='REPAIR', manufacturer='甲厂', brand='甲牌', unit_price=20),
            ToolCost(tool_info=other, cost_type='NEW_TOOL', manufacturer='丙厂', unit_price=None),
            ToolCost(tool_info=other, cost_type='REPAIR', manufacturer='丙厂', unit_price=0),
        ])

    def query(self, **params):
        return json.loads(query_tool_cost_catalog(json.dumps(params)))

    def test_new_and_repair_prices_are_separate_without_inventory_fields(self):
        with CaptureQueriesContext(connection) as queries:
            result = self.query(tool_model='换刮')
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries))
        row = result['by_model'][0]
        self.assertEqual(row['new_tool_price_min_yuan'], 100)
        self.assertEqual(row['new_tool_price_max_yuan'], 300)
        self.assertEqual(row['new_tool_quote_count'], 2)
        self.assertEqual(row['repair_price_min_yuan'], 20)
        self.assertEqual(row['repair_quote_count'], 1)
        self.assertEqual([quote['unit_price_yuan'] for quote in result['quotes']], [100, 300, 20])
        self.assertNotIn('inventory', json.dumps(result))
        self.assertTrue(all(row['registered_at'] for row in result['quotes']))

    def test_filters_match_model_code_and_exact_vendor_and_limit_only_details(self):
        result = self.query(tool_model='GG-', list_limit=1)
        self.assertEqual(len(result['quotes']), 1)
        self.assertEqual(result['scope']['quote_count'], 3)
        self.assertEqual(result['by_model'][0]['new_tool_price_max_yuan'], 300)
        filtered = self.query(tool_type='SCRAPER', brand='甲牌', manufacturer='甲厂', cost_type='NEW_TOOL')
        self.assertEqual(filtered['scope']['quote_count'], 1)
        self.assertEqual(filtered['by_model'][0]['repair_quote_count'], 0)
        self.assertIsNone(filtered['by_model'][0]['repair_price_min_yuan'])
        self.assertEqual(self.query(manufacturer='甲')['quotes'], [])

    def test_null_and_zero_quotes_stay_distinct(self):
        result = self.query(tool_model='GD-1')
        self.assertIsNone(result['by_model'][0]['new_tool_price_min_yuan'])
        self.assertEqual(result['by_model'][0]['repair_price_min_yuan'], 0)
        self.assertEqual(result['by_model'][0]['new_tool_quote_count'], 1)
        self.assertEqual([row['unit_price_yuan'] for row in result['quotes']], [None, 0])

    def test_invalid_enum_and_limit_return_errors(self):
        for params in ({'cost_type': 'COMPLETE'}, {'tool_type': 'UNKNOWN'}, {'list_limit': 201}, {'list_limit': 0}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
        self.assertIn('NEW_TOOL', self.query(cost_type='bad')['error'])
        self.assertIn('REPAIR', self.query(cost_type='bad')['error'])


class RegisteredAmountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='AMOUNT', project_name='登记金额')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='C1', shield_model='C1')

    def opening(self, ring, machine=None):
        machine = machine or self.machine
        row = WarehouseOpeningBasicInfo(warehouse_id=f'AMT-{machine.pk}-{ring}', project=self.project,
                                        shield_model=machine, ring_no=str(ring), open_time=timezone.now(),
                                        summary_status='CONFIRMED')
        WarehouseOpeningBasicInfo.objects.bulk_create([row])
        return row

    def detail(self, opening, position, *, new=True, **fields):
        fields.setdefault('tool_parent_type', 'DISC')
        fields.setdefault('is_replaced', True)
        detail = ToolChangeDetail(warehouse=opening, cutter_position_no=position, **fields)
        ToolChangeDetail.objects.bulk_create([detail])
        if new:
            instance = ToolInstance.objects.create(tool_uid=f'AMT-{detail.pk}', display_tool_no=f'{detail.pk}')
            NewToolRecord.objects.bulk_create([NewToolRecord(tool_change_detail=detail, tool_instance=instance)])
        return detail

    def query(self, **params):
        return json.loads(query_registered_amounts(json.dumps({
            'project_id': self.project.project_id, 'shield_machine_id': self.machine.pk, **params,
        })))

    def make_costs(self):
        first, second = self.opening(2), self.opening(10)
        installed = self.detail(first, '01', manufacturer='原厂家', price=100)
        removed = self.detail(second, '1', manufacturer='本次新厂家', price=200)
        zero = self.detail(second, '2', manufacturer='零价厂家', price=0)
        missing = self.detail(second, '3', manufacturer='缺价厂家', price=None)
        OldToolRecord.objects.bulk_create([
            OldToolRecord(tool_change_detail=removed, confirmed_tool_instance=installed.new_tool_record.tool_instance,
                          inspection_status='CONFIRMED', repair_price=30),
            OldToolRecord(tool_change_detail=zero, inspection_status='CLOSED', repair_price=5),
            OldToolRecord(tool_change_detail=missing, inspection_status='PENDING_VENDOR_FEEDBACK', repair_price=80),
        ])
        self.detail(second, '80', price=9999)
        self.detail(second, '7', tool_parent_type='SCRAPER', price=9999)
        self.detail(second, '5', new=False, is_replaced=False, is_checked=True, price=9999)
        self.detail(second, '6', new=False, is_replaced=False, is_checked=False, price=9999)
        return first, second

    def test_totals_include_only_installation_and_confirmed_repairs(self):
        self.make_costs()
        with CaptureQueriesContext(connection) as queries:
            result = self.query()
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries))
        self.assertEqual(result['new_install'], {'amount_yuan': 300, 'record_count': 4, 'zero_price_count': 1, 'missing_price_count': 1})
        self.assertEqual(result['confirmed_repair'], {'amount_yuan': 35, 'record_count': 2})
        self.assertEqual(result['pending_repair'], {'amount_yuan': 80, 'record_count': 1})
        self.assertEqual(result['total_registered_cost_yuan'], 335)
        self.assertEqual(result['scope']['observation_count'], 5)
        self.assertEqual(result['scope']['replacement_count'], 4)

    def test_repair_group_uses_original_installation_outside_selected_ring_range(self):
        self.make_costs()
        result = self.query(group_by='manufacturer', ring_range=[10, 10])
        groups = {row['manufacturer']: row for row in result['groups']}
        self.assertEqual(groups['原厂家']['confirmed_repair']['amount_yuan'], 30)
        self.assertEqual(groups['本次新厂家']['new_install']['amount_yuan'], 200)
        self.assertEqual(groups['本次新厂家']['confirmed_repair']['amount_yuan'], 0)
        self.assertEqual(groups['未能确定原厂家']['confirmed_repair']['amount_yuan'], 5)
        self.assertEqual(groups['未能确定原厂家']['pending_repair']['amount_yuan'], 80)
        self.assertEqual(sum(row['total_registered_cost_yuan'] or 0 for row in groups.values()), 235)

    def test_opening_sort_is_numeric_and_type_machine_filters_apply(self):
        self.make_costs()
        other = ShieldMachineBasicInfo.objects.create(shield_model_id='C2', shield_model='C2')
        self.detail(self.opening(3, other), '1', price=900)
        self.assertEqual([row['ring_no'] for row in self.query(group_by='opening')['groups']], [2, 10])
        typed = self.query(group_by='tool_type', tool_type='DISC')
        self.assertEqual(typed['groups'][0]['tool_type'], 'DISC')
        self.assertEqual(typed['total_registered_cost_yuan'], 335)
        self.assertEqual(self.query(tool_type='SCRAPER')['new_install']['record_count'], 0)

    def test_all_missing_prices_are_null_and_real_zero_is_zero(self):
        self.detail(self.opening(11), '1', price=None)
        self.detail(self.opening(12), '1', price=0)
        missing = self.query(ring_range=[11, 11])
        self.assertIsNone(missing['new_install']['amount_yuan'])
        self.assertIsNone(missing['total_registered_cost_yuan'])
        self.assertEqual(missing['new_install']['missing_price_count'], 1)
        zero = self.query(ring_range=[12, 12])
        self.assertEqual(zero['total_registered_cost_yuan'], 0)
        self.assertEqual(zero['new_install']['zero_price_count'], 1)

    def test_unresolved_legacy_repair_does_not_double_count(self):
        detail = self.detail(self.opening(50), '1', new=False, price=20, replacement_type='REPAIR')
        OldToolRecord.objects.create(tool_change_detail=detail, repair_price=20, inspection_status='CONFIRMED')
        result = self.query()
        self.assertEqual(result['total_registered_cost_yuan'], 0)
        self.assertEqual(result['scope']['excluded_cost_source_count'], 2)
        self.assertTrue(any('待核对' in warning for warning in result['warnings']))

    def test_invalid_amount_parameters_return_errors(self):
        for params in ({'group_by': 'brand'}, {'ring_range': [10, 2]}, {'tool_type': 'bad'}, {'shield_machine_id': False}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
