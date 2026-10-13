"""Exact tool statistics from isolated DB fixtures, without any model calls."""

import json

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant import tools
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
