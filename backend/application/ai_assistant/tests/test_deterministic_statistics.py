"""Exact tool statistics from isolated DB fixtures, without any model calls."""

import json
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant import tools
from application.ai_assistant.llm_service import ToolAssistant
from application.shield.models import (
    ProjectInfo, ShieldMachineBasicInfo, ShieldTunnelingData, StratumBasicInfo,
    ToolChangeDetail, WarehouseOpeningBasicInfo,
)


class DeterministicStatisticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id="STAT-ONE", project_name="One")
        cls.other_project = ProjectInfo.objects.create(project_id="STAT-TWO", project_name="Two")
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id="STAT-A", shield_model="A")
        cls.other_machine = ShieldMachineBasicInfo.objects.create(shield_model_id="STAT-B", shield_model="B")

    def call(self, function, **params):
        result = json.loads(function(json.dumps({"project_id": self.project.project_id, **params})))
        self.assertNotIn("error", result, result)
        return result

    def opening(self, ring, project=None, machine=None, suffix=""):
        project, machine = project or self.project, machine or self.machine
        row = WarehouseOpeningBasicInfo(
            warehouse_id=f"{project.pk}-{machine.pk}-{ring}-{suffix}",
            project=project, shield_model=machine, ring_no=str(ring), open_time=timezone.now(),
        )
        WarehouseOpeningBasicInfo.objects.bulk_create([row])
        return row

    def detail(self, opening, position="1", **kwargs):
        kwargs.setdefault("tool_parent_type", "SCRAPER" if position.startswith("S") else "DISC")
        kwargs.setdefault("is_checked", True)
        row = ToolChangeDetail(warehouse=opening, cutter_position_no=position, **kwargs)
        ToolChangeDetail.objects.bulk_create([row])

    def tunnel(self, ring, **kwargs):
        kwargs.setdefault("project", self.project)
        kwargs.setdefault("shield_machine", self.machine)
        ShieldTunnelingData.objects.bulk_create([ShieldTunnelingData(ring_no=str(ring), **kwargs)])

    def stratum(self, ring, codes, project=None):
        StratumBasicInfo.objects.bulk_create([StratumBasicInfo(
            project=project or self.project, ring_no=str(ring), stratum_type_codes=codes,
        )])

    def test_change_total_uses_records_not_average_of_segment_rates(self):
        self.detail(self.opening(100), is_replaced=True)
        other = self.opening(200)
        for position in range(1, 10):
            self.detail(other, str(position), is_replaced=False)
        result = self.call(tools.query_tool_change_trend, ring_range=[95, 205], interval=50)
        summary = result['summary']
        self.assertEqual((summary['total_records'], summary['replaced_count']), (10, 1))
        self.assertEqual(summary['replacement_rate_pct'], 10.0)
        self.assertEqual(summary['segment_count'], 3)
        self.assertEqual(summary['nonempty_segment_count'], 2)
        self.assertEqual(summary['requested_ring_range'], [95, 205])
        self.assertEqual(summary['effective_ring_range'], [100, 200])
        self.assertEqual(sum(row['total'] for row in result['segments']), 10)
        self.assertEqual(sum(row['replaced'] for row in result['segments']), 1)
        self.assertEqual(result['segments'][-1]['ring_range'], '200-200')
        self.assertIn('不使用人工确认开仓汇总', summary['count_basis'])

    def test_different_ranges_requery_exact_subset_including_boundaries(self):
        for ring in [99, 100, 150, 200, 201]:
            self.detail(self.opening(ring), is_replaced=True)
        for bounds, expected in [([100, 200], 3), ([150, 150], 1), ([100, 149], 1), ([300, 400], 0)]:
            with self.subTest(bounds=bounds):
                summary = self.call(tools.query_tool_change_trend, ring_range=bounds)['summary']
                self.assertEqual(summary['total_records'], expected)
                self.assertEqual(summary['requested_ring_range'], bounds)

    def test_change_counts_respect_project_machine_type_and_active_inspections(self):
        opening = self.opening(100)
        self.detail(opening, "1", is_replaced=True, is_checked=False)
        self.detail(opening, "2", is_checked=False, is_replaced=False)
        self.detail(opening, "3", tool_parent_type="SCRAPER", is_replaced=True)
        self.detail(opening, "G1R", is_replaced=True)
        self.detail(opening, "S1L", is_replaced=True)
        self.detail(self.opening(100, machine=self.other_machine), is_replaced=True)
        self.detail(self.opening(100, project=self.other_project), is_replaced=True)
        summary = self.call(tools.query_tool_change_trend, tool_type="DISC",
                            shield_machine_id=self.machine.pk)['summary']
        self.assertEqual((summary['total_records'], summary['replaced_count']), (1, 1))

    def test_change_counts_observations_not_unique_tool_instances(self):
        for ring in [100, 200]:
            self.detail(self.opening(ring), tool_number="SAME-TOOL", is_replaced=True)
        summary = self.call(tools.query_tool_change_trend)['summary']
        self.assertEqual(summary['replaced_count'], 2)
        self.assertIn("不是去重刀具实例数", summary['count_basis'])

    def test_zero_replacements_and_missing_sample_are_distinct(self):
        self.detail(self.opening(100), is_replaced=False)
        populated = self.call(tools.query_tool_change_trend, ring_range=[100, 100])
        empty = self.call(tools.query_tool_change_trend, ring_range=[101, 200])
        self.assertEqual(populated['summary']['replacement_rate_pct'], 0)
        self.assertEqual(empty['total'], 0)
        self.assertEqual(empty['summary']['segment_count'], 0)
        self.assertIsNone(empty['summary']['replacement_rate_pct'])
        self.assertIsNone(empty['summary']['effective_ring_range'])

    def test_tunneling_scalar_routes_and_explicit_changes(self):
        self.tunnel(100, thrust=12)
        assistant = ToolAssistant.__new__(ToolAssistant)
        cases = [
            ('有记录范围内掘进分段平均推力的最大值是多少', 'tunneling'),
            ('有记录范围内各分段均值的平均推力多少？', 'tunneling'),
            ('平均总推力是多少', 'tunneling'),
            ('分析掘进分段推力的最小值', 'tunneling'),
            ('推力分段均值情况怎么样', 'tunneling'),
            ('推力随环号怎么变化', 'tunneling_trend'),
            ('按50环分段统计推力', 'tunneling_trend'),
            ('每50环平均推力多少', 'tunneling_trend'),
            ('按区间分段统计平均推力', 'tunneling_trend'),
            ('各阶段平均推力多少', 'tunneling_trend'),
            ('掘进参数有没有异常偏高', 'tunneling_anomaly'),
            ('分析掘进参数与换刀磨损的关联', 'tunneling_wear_correlation'),
        ]
        with patch.object(assistant, '_ensure_llm_runtime', side_effect=AssertionError('禁止调用模型')), \
                patch('application.ai_assistant.llm_service.query_tunneling_summary',
                      wraps=tools.query_tunneling_summary) as summary_tool:
            for question, branch in cases:
                with self.subTest(question=question):
                    summary_tool.reset_mock()
                    result = assistant._direct_route(question, {'project_id': self.project.project_id})
                    self.assertEqual(result['rule_branch'], branch)
                    self.assertEqual(summary_tool.call_count, int(branch == 'tunneling'))

    def test_change_abnormal_summary_uses_all_filtered_records(self):
        first, last = self.opening(100), self.opening(200)
        self.detail(first, wear_condition=' 偏磨 ', is_replaced=False)
        for position in ['1', '2', '3']:
            self.detail(last, position, wear_condition='正常', is_replaced=True)
        self.detail(last, '4', wear_condition='未识别状态')
        result = self.call(tools.query_tool_change_trend, ring_range=[100, 200], interval=50)
        summary = result['summary']
        self.assertEqual((summary['total_records'], summary['replaced_count']), (5, 3))
        self.assertEqual((summary['normal_count'], summary['abnormal_count'], summary['unknown_count']), (3, 1, 1))
        self.assertEqual(summary['abnormal_rate'], '25.0%')
        for name in ['normal_count', 'abnormal_count', 'unknown_count']:
            self.assertEqual(summary[name], sum(segment[name] for segment in result['segments']))
        assistant = ToolAssistant.__new__(ToolAssistant)
        answer = assistant._format_trend_answer(json.dumps(result))
        for name in ['normal_count', 'abnormal_count', 'unknown_count', 'abnormal_rate']:
            del summary[name]
        self.assertEqual(answer, assistant._format_trend_answer(json.dumps(result)))

    def test_position_abnormal_summary_includes_positions_beyond_top_n(self):
        opening = self.opening(100)
        for position, wear, replaced in [('1', '正常', True), ('01', '正常', True), ('001', '未识别状态', False)]:
            self.detail(opening, position, wear_condition=wear, is_replaced=replaced)
        self.detail(opening, '2', wear_condition=' abnormal ', is_replaced=False)
        self.detail(opening, '3', wear_condition='偏磨', is_checked=False)
        self.detail(opening, 'G1R', wear_condition='偏磨', is_replaced=True)
        self.detail(self.opening(99), wear_condition='偏磨')
        self.detail(self.opening(100, project=self.other_project), wear_condition='偏磨')
        self.detail(self.opening(100, machine=self.other_machine), wear_condition='偏磨')
        result = self.call(tools.query_cutter_position_stats, ring_range=[100, 100],
                           shield_machine_id=self.machine.pk, top_n=1)
        summary = result['summary']
        self.assertTrue(result['truncated'])
        self.assertEqual(result['top_positions'][0]['abnormal_observation_count'], 0)
        self.assertEqual((summary['total_records'], summary['position_count']), (4, 2))
        self.assertEqual((summary['abnormal_observation_count'], summary['classified_observation_count']), (1, 3))
        self.assertEqual(summary['abnormal_observation_rate'], 33.3)
        assistant = ToolAssistant.__new__(ToolAssistant)
        answer = assistant._format_cutter_position_answer(json.dumps(result))
        for name in ['abnormal_observation_count', 'classified_observation_count', 'abnormal_observation_rate']:
            del summary[name]
        self.assertEqual(answer, assistant._format_cutter_position_answer(json.dumps(result)))

    def test_abnormal_summary_rate_is_null_without_classified_observations(self):
        self.detail(self.opening(100), wear_condition='未识别状态')
        for bounds in [[100, 100], [101, 200]]:
            for function, count, rate in [
                (tools.query_tool_change_trend, 'abnormal_count', 'abnormal_rate'),
                (tools.query_cutter_position_stats, 'abnormal_observation_count', 'abnormal_observation_rate'),
            ]:
                with self.subTest(tool=function.__name__, bounds=bounds):
                    summary = self.call(function, ring_range=bounds)['summary']
                    self.assertEqual(summary[count], 0)
                    self.assertIsNone(summary[rate])
                    if function == tools.query_cutter_position_stats:
                        self.assertEqual(summary['classified_observation_count'], 0)

    def test_stratum_associations_are_not_unique_rings(self):
        self.stratum(100, "CLAY_SAND,BOULDER, CLAY_SAND")
        self.stratum(200, "")
        result = self.call(tools.query_stratum_data)
        self.assertEqual(result['total_rings'], 2)
        self.assertEqual(result['unique_project_ring_count'], 2)
        self.assertEqual(result['label_association_count'], 3)
        self.assertEqual(sum(result['stratum_distribution'].values()), 3)
        self.assertIn("面积占比", result['note'])
        self.assertIn("地层基础信息表", result['note'])
        self.assertIn("未限定开仓点", result['note'])

    def test_stratum_numeric_ring_dedup_is_scoped_per_project(self):
        self.stratum("001", "CLAY_SAND")
        self.stratum("1", "BOULDER")
        self.stratum("1", "SOFT_SOIL", self.other_project)
        project_result = self.call(tools.query_stratum_data)
        self.assertEqual(project_result['total_rings'], 2)
        self.assertEqual(project_result['unique_project_ring_count'], 1)
        all_result = self.call(tools.query_stratum_data, project_id=None)
        self.assertEqual(all_result['total_rings'], 3)
        self.assertEqual(all_result['unique_project_ring_count'], 2)

    def test_stratum_range_and_empty_result_summary(self):
        self.stratum(99, "CLAY_SAND")
        self.stratum(100, "BOULDER")
        result = self.call(tools.query_stratum_data, ring_range=[100, 110])
        self.assertEqual(result['summary']['requested_ring_range'], [100, 110])
        self.assertEqual(result['summary']['effective_ring_range'], [100, 100])
        self.assertEqual(result['label_association_count'], 1)
        empty = self.call(tools.query_stratum_data, ring_range=[101, 110])
        self.assertEqual(empty['total_rings'], 0)
        self.assertEqual(empty['summary']['label_association_count'], 0)
        self.assertIsNone(empty['summary']['effective_ring_range'])

    def test_unrestricted_stratum_keeps_legacy_unparseable_ring_labels(self):
        self.stratum('待核定', 'BOULDER')
        result = self.call(tools.query_stratum_data)
        self.assertEqual(result['total_rings'], 1)
        self.assertEqual(result['label_association_count'], 1)
        self.assertEqual(result['unique_project_ring_count'], 0)
        self.assertEqual(result['unresolved_ring_record_count'], 1)
        self.assertIsNone(result['summary']['effective_ring_range'])

    def test_tunneling_does_not_average_rounded_segment_averages(self):
        self.tunnel(100, thrust=0, penetration=None, point_count=100)
        self.tunnel(150, thrust=10, penetration=1.23456, point_count=1)
        self.tunnel(150, thrust=None, penetration=None, point_count=300)
        result = self.call(tools.query_tunneling_trend, ring_range=[100, 150], interval=50)
        self.assertEqual(result['summary']['total_records'], 3)
        self.assertEqual(result['summary']['segment_count'], 2)
        self.assertEqual(result['summary']['effective_ring_range'], [100, 150])
        self.assertEqual(result['segments'][-1]['ring_range'], '150-150')
        self.assertEqual(result['segments'][0]['avg_thrust'], 0)
        self.assertIsNone(result['segments'][0]['avg_penetration'])
        self.assertFalse(result['summary']['overall_metric_averages_available'])
        self.assertNotIn('avg_thrust', result['summary'])
        self.assertNotIn('avg_penetration', result['summary'])
        self.assertIn('sum/count', result['summary']['count_basis'])

    def test_tunneling_single_ring_points_are_not_record_total(self):
        self.tunnel(100, thrust=0, point_count=100, raw_parameters={'segment_index': 1})
        self.tunnel(100, thrust=None, point_count=300, raw_parameters={'segment_index': 2})
        result = self.call(tools.query_tunneling_trend, ring_range=[100, 100])
        self.assertEqual(result['summary']['total_records'], 2)
        self.assertEqual(sum(row['count'] for row in result['segments']), 400)
        self.assertEqual(result['summary']['segment_count'], 2)
        self.assertEqual(result['summary']['segment_mode'], 'single_ring_time_segments')
        self.assertFalse(result['summary']['overall_metric_averages_available'])

    def test_tunneling_scope_and_empty_summary(self):
        self.tunnel(99, thrust=7)
        self.tunnel(100, thrust=8)
        self.tunnel(100, thrust=9, project=self.other_project)
        self.tunnel(100, thrust=10, shield_machine=self.other_machine)
        result = self.call(tools.query_tunneling_trend, ring_range=[100, 100],
                           shield_machine_id=self.machine.pk)
        self.assertEqual(result['summary']['total_records'], 1)
        self.assertEqual(result['summary']['requested_ring_range'], [100, 100])
        empty = self.call(tools.query_tunneling_trend, ring_range=[101, 110])
        self.assertEqual(empty['total_records'], 0)
        self.assertEqual(empty['summary']['segment_count'], 0)
        self.assertIsNone(empty['summary']['effective_ring_range'])
