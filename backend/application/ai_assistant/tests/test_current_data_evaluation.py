from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase

from application.ai_assistant.evaluation.current_data_suite import (
    ProjectEvidence, QuestionCase, build_cases, build_chains, compare_subset,
    evaluate_case, expected_facts, readonly_database, rule_runtime, selected_details, valid_detail,
)


def detail(position, kind="DISC", checked=True, replaced=False, ring="100", warehouse=1):
    return {"id": 1, "warehouse_id": warehouse, "warehouse__ring_no": ring,
            "cutter_position_no": position, "tool_parent_type": kind, "is_checked": checked,
            "is_replaced": replaced, "manufacturer": "Fixture manufacturer", "price": None}


def evidence(rows=None):
    return ProjectEvidence("EVAL-FIXTURE", rows or [], [
        {"id": 1, "ring_no": "100", "shield_model_id": 1, "summary_status": "CONFIRMED",
         "checked_tool_count": 20, "replaced_tool_count": 5, "rings_between_openings": 10,
         "opening_duration": 1.0},
        {"id": 2, "ring_no": "487", "shield_model_id": 1, "summary_status": "DRAFT",
         "checked_tool_count": None, "replaced_tool_count": None, "rings_between_openings": 387,
         "opening_duration": None},
    ], [{"ring_no": "2800", "stratum_type_codes": "FIXTURE"}], [])


class CurrentDataEvaluationTests(SimpleTestCase):
    def test_oracle_filters_actual_business_positions_and_observations(self):
        dataset = evidence([
            detail("001", replaced=True), detail("s1l", "SCRAPER", replaced=True),
            detail("G3R", replaced=True), detail("Y2", replaced=True),
            detail("S2L", "DISC", replaced=True), detail("79", checked=False),
        ])
        self.assertEqual(len(dataset.active_details), 3)
        self.assertEqual(len(selected_details(dataset, {})), 2)
        self.assertEqual(expected_facts(dataset, QuestionCase("x", "change", "fixture", "query_tool_change_data")),
                         {"total_records": 2, "replaced_count": 2})

    def test_oracle_does_not_reuse_subject_query_helpers(self):
        with patch("application.ai_assistant.tools._active_detail_query", side_effect=AssertionError("subject oracle reuse")):
            result = expected_facts(evidence([detail("1")]), QuestionCase("x", "change", "fixture", "query_tool_change_data"))
        self.assertEqual(result["total_records"], 1)

    def test_confirmed_counts_are_distinct_from_valid_field_details(self):
        dataset = evidence([detail("1", replaced=True), detail("G3R", replaced=True),
                            detail("S1L", "SCRAPER", checked=False, warehouse=2, ring="487")])
        result = expected_facts(dataset, QuestionCase("x", "opening", "fixture", "query_opening_records"))
        confirmed = result["opening_counts"]["100:1"]
        self.assertEqual(confirmed["tool_change_total"], 20)
        self.assertEqual(confirmed["detail_record_count"], 1)
        self.assertEqual(confirmed["tool_change_replaced"], 5)
        draft = result["opening_counts"]["487:1"]
        self.assertEqual(draft["tool_change_total"], 0)
        self.assertEqual(draft["count_source"], "detail_draft")

    def test_ring_scope_is_numeric_and_project_progress_ignores_future_geology(self):
        dataset = evidence([detail("1", ring="99"), detail("1", ring="100"), detail("1", ring="487")])
        self.assertEqual(dataset.latest_ring, 487)
        self.assertEqual(len(selected_details(dataset, {"ring_range": [100, 487]})), 2)
        recent = next(case for case in build_cases(dataset) if case.id == "change_recent")
        self.assertEqual(recent.params["ring_range"], [388, 487])

    def test_cases_and_chains_are_unique_and_missing_data_is_a_gap(self):
        cases = build_cases(evidence())
        self.assertEqual(len(cases), len({case.id for case in cases}))
        self.assertGreaterEqual(len(cases), 45)
        self.assertLessEqual(len(cases), 60)
        self.assertEqual(len(build_chains(evidence())), 10)
        inventory = next(case for case in cases if case.id == "inventory_available")
        self.assertTrue(inventory.gap)
        self.assertIsNone(inventory.tool)
        scrapped = next(case for case in cases if case.id == "lifecycle_SCRAPPED")
        self.assertTrue(scrapped.gap)

    def test_tunneling_empty_and_missing_metrics_are_not_fabricated(self):
        dataset = evidence()
        dataset.tunneling = [{"ring_no": "5", "thrust": 10.0, "torque": None,
                              "penetration": 2.0, "cutterhead_speed": 1.0}]
        case = QuestionCase("x", "tunneling", "fixture", "query_tunneling_summary", {"ring_range": [5, 5]})
        result = expected_facts(dataset, case)
        self.assertEqual(result["metrics"]["torque"], {"avg": None, "min": None, "max": None})
        self.assertFalse(dataset.inventory()["tunneling"]["cross_ring_trend_available"])
        case.params = {"ring_range": [6, 6]}
        self.assertEqual(expected_facts(dataset, case), {"total_records": 0})

    def test_readonly_guard_rejects_other_backends_before_transaction(self):
        connection = Mock(vendor="sqlite", in_atomic_block=False)
        with patch("application.ai_assistant.evaluation.current_data_suite.connections", {"default": connection}), patch(
            "application.ai_assistant.evaluation.current_data_suite.transaction.atomic"
        ) as atomic:
            with self.assertRaisesMessage(ValueError, "requires PostgreSQL"):
                with readonly_database():
                    pass
            atomic.assert_not_called()

    def test_numeric_mismatch_cannot_pass_on_matching_keywords(self):
        self.assertTrue(compare_subset({"total_records": 120}, {"total_records": 163, "answer": "120"}))
        self.assertFalse(compare_subset({"metrics": {"avg": 0.3}}, {"metrics": {"avg": 0.30000000000001}}))

    def test_position_boundaries(self):
        for position in ["1", "79", "80A", "80B", "Y1", "Y3", "Y5"]:
            self.assertTrue(valid_detail(detail(position)))
        for position in ["0", "80", "81", "Y2", "G3R", "S20L"]:
            self.assertFalse(valid_detail(detail(position)))

    def test_readonly_mode_and_statement_timeout_are_actually_requested(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = ("on",)
        connection = Mock(vendor="postgresql", in_atomic_block=False)
        connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        with patch("application.ai_assistant.evaluation.current_data_suite.connections", {"default": connection}), patch(
            "application.ai_assistant.evaluation.current_data_suite.transaction.atomic", return_value=nullcontext()
        ):
            with readonly_database(timeout_ms=2345):
                pass
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn("READ ONLY", statements[0])
        self.assertIn("REPEATABLE READ", statements[0])
        self.assertEqual(cursor.execute.call_args_list[1].args[1], ["2345"])

    def test_rule_evaluation_fails_closed_for_model_and_memory_access(self):
        with rule_runtime() as (assistant, _calls):
            with self.assertRaisesMessage(RuntimeError, "forbids model"):
                assistant._ensure_llm_runtime()
            with self.assertRaisesMessage(RuntimeError, "forbids memory"):
                assistant.memory.load("experiment:fixture")

    def test_unsupported_cost_must_not_be_marked_correct_when_answering_recommendations(self):
        assistant = SimpleNamespace(_direct_route=lambda question, context: {
            "rule_branch": "tool_recommendation", "answer": "fixture recommendation",
        })
        case = next(case for case in build_cases(evidence()) if case.id == "cost_project_total")
        row, _ = evaluate_case(assistant, [], evidence(), case)
        self.assertEqual(row["status"], "coverage_gap")
        self.assertTrue(row["correctness_errors"])

    def test_long_chain_checks_intent_and_interval_after_original_question_expires(self):
        chain = next(chain for chain in build_chains(evidence()) if chain["id"] == "chain_trend_interval")
        self.assertGreater(len(chain["steps"]), 3)
        for step in chain["steps"]:
            self.assertEqual(step["case"].tool, "query_tool_change_trend")
            self.assertEqual(step["case"].expected_branch, "change_trend")
            self.assertEqual(step["case"].params["interval"], 100)
