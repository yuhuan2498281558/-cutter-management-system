import json

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant.tools_inspections import query_tool_inspections
from application.shield.models import (
    MobileToolChangeTask, ProjectInfo, ShieldMachineBasicInfo, ToolChangeDetail, WarehouseOpeningBasicInfo,
)


class InspectionToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='W2-CHECK', project_name='检查测试')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='CHECK', shield_model='检查机')

    def opening(self, ring):
        row = WarehouseOpeningBasicInfo(warehouse_id=f'CHECK-{ring}', project=self.project,
                                       shield_model=self.machine, ring_no=str(ring), open_time=timezone.now())
        WarehouseOpeningBasicInfo.objects.bulk_create([row])
        return row

    def detail(self, opening, position, **fields):
        fields.setdefault('tool_parent_type', 'DISC')
        row = ToolChangeDetail(warehouse=opening, cutter_position_no=position, **fields)
        ToolChangeDetail.objects.bulk_create([row])
        return row

    def query(self, **params):
        return json.loads(query_tool_inspections(json.dumps({'project_id': self.project.project_id, **params})))

    def test_attention_is_not_inferred_from_default_normal_or_wear(self):
        opening = self.opening(100)
        self.detail(opening, '1', is_replaced=True, check_result='NORMAL', wear_condition='偏磨')
        self.detail(opening, '2', is_checked=True, check_result='ATTENTION', wear_condition='中度磨损')
        self.detail(opening, '3', is_checked=True, check_result='ABNORMAL_NOT_REPLACED', wear_condition='断裂')
        self.detail(opening, '4')
        result = self.query()
        self.assertEqual(result['attention_not_replaced']['record_count'], 2)
        self.assertEqual(result['unchecked']['records'][0]['cutter_position_no'], '4')
        self.assertEqual(result['unchecked']['record_count'], 1)
        self.assertEqual(result['replaced_rows_with_abnormal_wear'], 1)
        self.assertEqual(result['opening_completion'][0]['checked_count'], 3)
        self.assertEqual(result['opening_completion'][0]['position_count'], 4)
        self.assertEqual(result['opening_completion'][0]['attention_not_replaced_count'], 2)
        labels = {r['check_result']: r['label'] for r in result['check_result_counts']}
        self.assertEqual(labels['ATTENTION'], '需关注')

    def test_counts_positions_limits_and_numeric_sort_are_separate(self):
        for ring in (9, 100):
            opening = self.opening(ring)
            self.detail(opening, '002', is_checked=True, check_result='ATTENTION')
            self.detail(opening, '10', is_checked=True, check_result='ATTENTION')
            self.detail(opening, 'G1R', is_checked=True, check_result='ATTENTION')
        result = self.query(list_limit=1)
        group = result['attention_not_replaced']
        self.assertEqual((group['record_count'], group['position_count'], len(group['records'])), (4, 2, 1))
        self.assertEqual((group['records'][0]['ring_no'], group['records'][0]['cutter_position_no']), (100, '2'))
        self.assertEqual([r['ring_no'] for r in result['opening_completion']], [100, 9])
        self.assertEqual(self.query(cutter_position_no=' 02 ')['scope']['record_count'], 2)

    def test_check_result_filter_preserves_completion_and_all_detail_counts(self):
        for ring in (100, 200):
            opening = self.opening(ring)
            self.detail(opening, '1', is_checked=True, check_result='ATTENTION', mobile_status='SAVED')
            self.detail(opening, '2')
            MobileToolChangeTask.objects.create(warehouse=opening, status='UNASSIGNED')
        self.detail(opening, '3', is_checked=True, check_result='ABNORMAL_NOT_REPLACED', mobile_status='SAVED')
        for params in ({'ring_range': [100, 200]}, {'recent_openings': 1},
                       {'ring_range': [100, 200], 'tool_type': 'DISC', 'cutter_position_no': '2'}):
            with self.subTest(params=params):
                unfiltered = self.query(**params)
                filtered = self.query(**params, check_result='ATTENTION')
                for key in ('opening_completion', 'unchecked', 'check_result_counts',
                            'task_status_counts', 'mobile_status_counts'):
                    self.assertEqual(filtered[key], unfiltered[key])
                self.assertEqual(filtered['summary']['unchecked_count'], unfiltered['summary']['unchecked_count'])
                attention = filtered['attention_not_replaced']
                self.assertTrue(all(r['check_result'] == 'ATTENTION' for r in attention['records']))
                expected_count = 0 if 'cutter_position_no' in params else 1 if 'recent_openings' in params else 2
                self.assertEqual(attention['record_count'], expected_count)
                self.assertEqual(filtered['scope']['record_count'], expected_count)
                self.assertEqual(filtered['summary']['attention_count'], expected_count)
                self.assertNotIn('note', unfiltered['scope'])
                self.assertEqual(filtered['scope']['note'],
                                 '检查结果筛选只影响列出的记录；各次开仓完成度、未检查数和检查结果分布按全部明细计算。')

    def test_all_task_states_and_mobile_states_are_independent(self):
        opening = self.opening(20)
        self.detail(opening, '1', is_checked=True, check_result='ATTENTION', mobile_status='SAVED')
        for status in ('UNASSIGNED', 'RETURNED', 'CANCELLED'):
            MobileToolChangeTask.objects.create(warehouse=opening, status=status)
        result = self.query()
        self.assertEqual(result['task_status_counts'], {'UNASSIGNED': 1, 'RETURNED': 1, 'CANCELLED': 1})
        self.assertEqual(result['mobile_status_counts'], {'SAVED': 1})
        self.assertEqual(result['opening_completion'][0]['task_status'], ['CANCELLED', 'RETURNED', 'UNASSIGNED'])
        self.assertEqual(result['opening_completion'][0]['summary_status'], 'DRAFT')

    def test_recent_openings_include_latest_empty_opening(self):
        self.detail(self.opening(9), '1', is_checked=True, check_result='ATTENTION')
        self.opening(100)
        result = self.query(recent_openings=1)
        self.assertEqual(result['scope']['record_count'], 0)
        self.assertEqual(result['opening_completion'][0]['ring_no'], 100)
        self.assertEqual(result['opening_completion'][0]['task_status'], [])

    def test_filters_and_invalid_parameters(self):
        self.detail(self.opening(100), '1', is_checked=True, check_result='ATTENTION')
        self.assertEqual(self.query(check_result='PENDING')['scope']['record_count'], 0)
        for params in ({'recent_openings': 1, 'ring_range': [1, 100]}, {'ring_range': [100, 1]},
                       {'ring_range': ['1', 100]}, {'check_result': 'BAD'}, {'check_result': []}, {'tool_type': 'RIPPER'},
                       {'recent_openings': 101}, {'list_limit': 201}, {'cutter_position_no': 'G1R'},
                       {'tool_type': 'SCRAPER', 'cutter_position_no': '1'}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
        self.assertIn('error', json.loads(query_tool_inspections('[')))
        self.assertIn('error', json.loads(query_tool_inspections('[]')))
