"""Business fixtures for assistant queries; no model service or external APIs."""
import json

from django.test import TestCase
from django.utils import timezone

from application.ai_assistant import tools
from application.shield.models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo,
    ShieldTunnelingData, ToolChangeDetail, ToolInstance, WarehouseOpeningBasicInfo,
)


class QueryContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id="AI-CONTRACT", project_name="Contract")
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id="A", shield_model="A")
        cls.other_machine = ShieldMachineBasicInfo.objects.create(shield_model_id="B", shield_model="B")

    def opening(self, ring, machine=None, **fields):
        machine = machine or self.machine
        # Query fixtures do not run opening creation/mobile task signals.
        opening = WarehouseOpeningBasicInfo(
            warehouse_id=f"{machine.pk}-{ring}", project=self.project,
            shield_model=machine, ring_no=str(ring), open_time=timezone.now(), **fields,
        )
        WarehouseOpeningBasicInfo.objects.bulk_create([opening])
        return opening

    def detail(self, opening, position, **fields):
        fields.setdefault("tool_parent_type", "SCRAPER" if position.upper().startswith("S") else "DISC")
        row = ToolChangeDetail(warehouse=opening, cutter_position_no=position, **fields)
        ToolChangeDetail.objects.bulk_create([row])
        return row

    def query(self, function, **params):
        return json.loads(function(json.dumps({"project_id": self.project.project_id, **params})))

    def test_current_wear_choices_do_not_hide_chipped_blades(self):
        for value in ['崩口', 'CHIP', 'chip', '偏磨', '断裂']:
            with self.subTest(value=value):
                self.assertEqual(tools.normalize_wear_condition(value), 'abnormal')
        self.assertEqual(tools.normalize_wear_condition('其他'), 'unknown')
        self.assertEqual(tools.normalize_wear_condition(''), 'unknown')

    def test_manufacturer_missing_evidence_is_not_zero_risk_and_zero_price_survives(self):
        opening = self.opening(100)
        self.detail(opening, '1', is_checked=True, is_replaced=True,
                    manufacturer='Unknown', wear_condition='待核实')
        self.detail(opening, '2', is_checked=True, is_replaced=True,
                    manufacturer='Known', wear_condition='无异常', price=0)
        result = self.query(tools.compare_manufacturer_performance)
        known, unknown = result['manufacturers']
        self.assertEqual(known['manufacturer'], 'Known')
        self.assertEqual(known['abnormal_rate_pct'], 0)
        self.assertEqual(known['abnormal_rate_denominator'], 1)
        self.assertEqual(known['avg_cost_per_change_yuan'], 0)
        self.assertEqual(unknown['manufacturer'], 'Unknown')
        self.assertIsNone(unknown['abnormal_rate_pct'])
        self.assertEqual(unknown['unclassified_wear_count'], 1)
        self.assertNotIn('质量最好', result['note'])

    def test_invalid_historical_positions_and_type_mismatches_are_excluded(self):
        opening = self.opening(100)
        for position, tool_type in [("1", "DISC"), ("s1l", "SCRAPER"), ("G1R", "DISC"),
                                    ("Y2", "DISC"), ("S2R", "RIPPER"), ("2", "SCRAPER")]:
            self.detail(opening, position, tool_parent_type=tool_type, is_checked=True, is_replaced=True)
        result = self.query(tools.query_tool_change_data)
        self.assertEqual(result["total_records"], 2)
        self.assertEqual(result["replaced_count"], 2)

    def test_draft_precreated_rows_do_not_become_inspections_or_zero_wear(self):
        opening = self.opening(100)
        self.detail(opening, "1")
        record = self.query(tools.query_opening_records)["recent_records"][0]
        self.assertEqual(record["detail_record_count"], 1)
        self.assertEqual(record["detail_checked_count"], 0)
        self.assertEqual(record["tool_change_total"], 0)
        self.assertEqual(record["summary_status"], "DRAFT")
        self.assertIsNone(record["replacement_rate"])
        self.assertIsNone(record["abnormal_rate"])

    def test_confirmed_summary_preserves_manual_counts_and_distinguishes_detail_counts(self):
        opening = self.opening(100, summary_status="CONFIRMED", checked_tool_count=20, replaced_tool_count=5)
        self.detail(opening, "1", is_checked=True, is_replaced=True)
        record = self.query(tools.query_opening_records)["recent_records"][0]
        self.assertEqual((record["tool_change_total"], record["tool_change_replaced"]), (20, 5))
        self.assertEqual((record["detail_checked_count"], record["detail_replaced_count"]), (1, 1))
        self.assertEqual(record["count_source"], "confirmed_summary")
        self.assertEqual(record["replacement_rate"], "25.0%")

    def test_position_ranking_honors_ring_window(self):
        self.detail(self.opening(99), "1", is_checked=True, is_replaced=True)
        self.detail(self.opening(150), "2", is_checked=True, is_replaced=True)
        result = self.query(tools.query_cutter_position_stats, ring_range=[100, 200])
        self.assertEqual([row["cutter_position_no"] for row in result["top_positions"]], ["2"])
        self.assertEqual(result["total_records"], 1)

    def test_tunneling_extrema_are_numeric(self):
        ShieldTunnelingData.objects.bulk_create([
            ShieldTunnelingData(project=self.project, shield_machine=self.machine, ring_no=ring)
            for ring in ["99", "100"]
        ])
        result = self.query(tools.query_tunneling_summary)
        self.assertEqual(result["ring_range"], [99, 100])

    def test_other_machine_replacement_does_not_remove_this_instance(self):
        installed = self.detail(self.opening(100), "S1L", tool_number="100-S1L-01", is_checked=True, is_replaced=True)
        instance = ToolInstance.objects.create(tool_uid="A-100-S1L", display_tool_no=installed.tool_number, status="INSTALLED")
        NewToolRecord.objects.create(tool_change_detail=installed, tool_instance=instance)
        self.detail(self.opening(120, self.other_machine), "S1L", is_checked=True, is_replaced=True)
        result = self.query(tools.calculate_tool_performance, tool_numbers=[installed.tool_number])["tools"][0]
        self.assertIsNone(result["removal_ring_no"])
        self.assertIsNone(result["service_rings"])
        self.assertEqual(result["lifecycle_status"], "INSTALLED")
        recommendation = self.query(tools.recommend_tools, min_samples=1)
        self.assertEqual(recommendation['recommendations'], [])
        self.assertEqual(recommendation['insufficient_evidence'][0]['completed_service_count'], 0)

    def test_wear_and_vendor_status_follow_removed_identity_not_new_number(self):
        installed = self.detail(self.opening(100), "S1L", tool_number="100-S1L-01", is_checked=True, is_replaced=True, wear_condition="轴承损坏")
        instance = ToolInstance.objects.create(tool_uid="A-100-S1L", display_tool_no=installed.tool_number, status="SCRAPPED")
        NewToolRecord.objects.create(tool_change_detail=installed, tool_instance=instance)
        self.detail(self.opening(110), "S1L", tool_number=installed.tool_number, is_checked=True, wear_condition="正常")
        removed = self.detail(self.opening(120), "S1L", tool_number="120-S1L-01", is_checked=True, is_replaced=True, wear_condition="偏磨")
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance,
                                     old_tool_number=installed.tool_number, inspection_status="CLOSED", disposition="SCRAP")
        result = self.query(tools.calculate_tool_performance, tool_numbers=[installed.tool_number])["tools"][0]
        self.assertEqual(result["service_rings"], 20)
        self.assertEqual(result["lifecycle_status"], "SCRAPPED")
        self.assertEqual(result["inspection_status"], "CLOSED")
        self.assertEqual([row["ring_no"] for row in result["inspections"]], [110, 120])
        self.assertEqual([row["wear_condition"] for row in result["inspections"]], ["正常", "偏磨"])
        self.assertFalse(result["removal_inferred"])

    def test_legacy_fallback_is_explicit_and_does_not_claim_known_lifetime(self):
        installed = self.detail(self.opening(100), "S1L", tool_number="legacy-S1L", is_checked=True, is_replaced=True)
        self.detail(self.opening(120), "S1L", is_checked=True, is_replaced=True)
        result = self.query(tools.calculate_tool_performance, tool_numbers=[installed.tool_number])["tools"][0]
        self.assertTrue(result["install_ring_inferred"])
        self.assertTrue(result["removal_inferred"])
        self.assertIsNone(result["service_rings"])
        self.assertEqual(result["removal_ring_no"], 120)
