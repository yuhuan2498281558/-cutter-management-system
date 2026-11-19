from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from decimal import Decimal

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
        self.assertLessEqual(len(cases), 90)
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
        ), patch('application.ai_assistant.evaluation.current_data_suite.transaction.set_rollback') as rollback:
            with readonly_database(timeout_ms=2345):
                pass
        rollback.assert_called_once_with(True, using='default')
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

    def test_actual_cost_question_must_not_pass_unrelated_recommendations(self):
        assistant = SimpleNamespace(_direct_route=lambda question, context: {
            "rule_branch": "tool_recommendation", "answer": "fixture recommendation",
        })
        case = next(case for case in build_cases(evidence()) if case.id == "cost_project_total")
        row, _ = evaluate_case(assistant, [], evidence(), case)
        self.assertEqual(row["status"], "fail")
        self.assertIn('Expected rule_branch registered_amounts', ' '.join(row['failures']))
        self.assertTrue(row['expected_facts'])

    def test_long_chain_checks_intent_and_interval_after_original_question_expires(self):
        chain = next(chain for chain in build_chains(evidence()) if chain["id"] == "chain_trend_interval")
        self.assertGreater(len(chain["steps"]), 3)
        for step in chain["steps"]:
            self.assertEqual(step["case"].tool, "query_tool_change_trend")
            self.assertEqual(step["case"].expected_branch, "change_trend")
            self.assertEqual(step["case"].params["interval"], 100)

    def test_trend_tail_uses_last_observed_ring(self):
        dataset = evidence([detail('1', ring='15'), detail('2', ring='487', replaced=True)])
        case = QuestionCase('tail', 'trend', 'fixture', 'query_tool_change_trend', {'interval': 50})
        self.assertEqual(expected_facts(dataset, case)['segments'][-1],
                         {'ring_range': '465-487', 'total': 1, 'replaced': 1})
        case.params['ring_range'] = [1, 300]
        self.assertEqual(expected_facts(dataset, case)['segments'][0]['ring_range'], '15-15')

    def test_new_cases_have_branch_and_explicit_specialized_parameters(self):
        cases = {case.id: case for case in build_cases(evidence())}
        self.assertEqual(cases['area_boulder'].params, {'rings': [2199], 'basis': 'longitudinal_area'})
        self.assertEqual(cases['area_cross'].params['basis'], 'cross_section')
        self.assertIn('manufacturers', cases['manufacturer_named'].params)
        branches = {case.expected_branch for case in cases.values()}
        self.assertTrue({'stratum_area', 'opening_stratum', 'tool_inspections', 'old_tool_repairs',
                         'tool_lifecycle', 'manufacturer_service', 'tool_cost_catalog',
                         'registered_amounts', 'data_catalog'} <= branches)
        self.assertFalse(cases['repair_pending_total'].gap)
        self.assertEqual(cases['confirmed_openings'].params['summary_status'], 'CONFIRMED')

    def test_new_oracles_recompute_repairs_amounts_and_inspections(self):
        row = detail('1', replaced=True)
        row.update(price=Decimal('12.50'), check_result='NORMAL', mobile_status='SAVED')
        attention = dict(detail('2'), id=2, check_result='ATTENTION', mobile_status='SAVED')
        dataset = evidence([row, attention])
        dataset.installations = [{'tool_change_detail_id': 1}]
        dataset.repairs = [{'tool_change_detail_id': 1, 'inspection_status': 'PENDING_VENDOR_FEEDBACK',
                            'disposition': 'SCRAP', 'repair_price': Decimal('7.50')}]
        with patch('application.shield.analysis_metrics.confirmed_service_segments', side_effect=AssertionError('oracle reuse')), patch(
            'application.shield.analysis_metrics.cost_source_rows', side_effect=AssertionError('oracle reuse')):
            repairs = expected_facts(dataset, QuestionCase('r', '', '', 'query_old_tool_repairs'))
            amounts = expected_facts(dataset, QuestionCase('a', '', '', 'query_registered_amounts'))
            checks = expected_facts(dataset, QuestionCase('i', '', '', 'query_tool_inspections'))
        self.assertEqual((repairs['scrapped_count'], repairs['scrap_suggestion_count']), (0, 1))
        self.assertEqual(amounts['total_registered_cost_yuan'], 12.5)
        self.assertEqual(amounts['pending_repair']['amount_yuan'], 7.5)
        self.assertEqual(checks['attention_not_replaced']['record_count'], 1)

    def test_area_oracle_keeps_two_bases_separate_and_first_opening_starts_at_one(self):
        dataset = evidence()
        dataset.strata = [{'ring_no': '100', 'stratum_type_codes': 'CLAY_SAND',
                          'longitudinal_type_ratios': {'AREA_CLAY_SAND': 80, 'AREA_BOULDER': 20},
                          'stratum_type_ratios': {'CLAY_3_3': 100}}]
        case = QuestionCase('a', '', '', 'query_stratum_area', {'rings': [100], 'basis': 'longitudinal_area'})
        with patch('application.shield.longitudinal_ratios.validate_longitudinal_ratios', side_effect=AssertionError('oracle reuse')):
            area = expected_facts(dataset, case)
        self.assertEqual(area['area_classes']['AREA_BOULDER']['share_pct'], 20)
        case.params['basis'] = 'cross_section'
        self.assertEqual(set(expected_facts(dataset, case)['area_classes']), {'CLAY_3_3'})
        opening = expected_facts(dataset, QuestionCase('o', '', '', 'query_opening_stratum', {'ring_no': 100}))
        self.assertEqual(opening['openings'][0]['interval'], [1, 100])

    def test_manual_review_does_not_count_as_pass(self):
        case = QuestionCase('m', '', '', 'query_tool_change_data', manual_review='服役环数需人工验收')
        dataset = evidence()
        calls = []
        def route(question, context):
            calls.append({'tool': case.tool, 'params': {'project_id': dataset.project_id}, 'result': {'total_records': 0}})
            return {'answer': '未找到换刀记录。'}
        row, _ = evaluate_case(SimpleNamespace(_direct_route=route), calls, dataset, case)
        self.assertEqual(row['status'], 'coverage_gap')
        self.assertEqual(row['coverage_gap'], case.manual_review)

    def test_lifecycle_checks_removal_ring_from_business_relations(self):
        start = dict(detail('1', ring='100', replaced=True), id=1)
        end = dict(detail('1', ring='487', warehouse=2, replaced=True), id=2)
        dataset = evidence([start, end])
        dataset.lifecycle_samples = {'INSPECTED': {'tool_uid': 'FIXTURE-UID', 'instance_id': 7, 'lifecycle_status': 'INSPECTED'}}
        dataset.installations = [{'tool_change_detail_id': 1, 'tool_instance_id': 7}]
        dataset.repairs = [{'tool_change_detail_id': 2, 'confirmed_tool_instance_id': 7}]
        result = expected_facts(dataset, QuestionCase('l', '', '', 'trace_tool_lifecycle', {'tool_ids': ['FIXTURE-UID']}))
        self.assertEqual(result['results'][0]['service_segments'], [{'install_ring': 100, 'removal_ring': 487}])
        self.assertNotIn('service_rings', result['results'][0]['service_segments'][0])
