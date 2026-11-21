from decimal import Decimal

from django.test import SimpleTestCase

from application.ai_assistant.scoring import (
    collect_gt_numbers, extract_field, extract_numbers, hallucinated_numbers, score_answer,
)


class ScoringTests(SimpleTestCase):
    def test_signed_numbers_are_distinct_and_identifiers_are_excluded(self):
        self.assertEqual(extract_numbers('-2.75 +2.75 S14R G3R'), {-2.75, 2.75})
        self.assertEqual(hallucinated_numbers('+2.75', [{'change': -2.75}]), [2.75])
        self.assertEqual(extract_field('变化 -2.75', r'变化\s*-?(\d+\.\d+)'), -2.75)

    def test_counts_cannot_be_rescaled_but_percent_fields_can(self):
        self.assertEqual(hallucinated_numbers('82300', [{'count': 823}]), [82300])
        self.assertEqual(hallucinated_numbers('8.23', [{'count': 823}]), [8.23])
        self.assertEqual(hallucinated_numbers('82300', [{'abnormal_rate_denominator': 823}]), [82300])
        self.assertEqual(hallucinated_numbers('27.5%', [{'abnormal_rate': 0.275}]), [])
        self.assertEqual(hallucinated_numbers('0.275', [{'abnormal_rate_pct': 27.5}]), [])

    def test_decimal_and_nested_numbers_are_supported(self):
        rows = [{'amount': Decimal('2.75'), 'groups': [{'count': 8, 'avg': None, 'flag': True}]}]
        self.assertEqual(collect_gt_numbers(rows), {2.75, 8})
        self.assertEqual(hallucinated_numbers('2.75 和 8', rows), [])
        result = score_answer('金额2.75', rows[0], {'answer_extract': {'amount': r'金额(\d+\.\d+)'}})
        self.assertTrue(result['exact_match'])

    def test_dict_and_json_tool_results_collect_nested_fields(self):
        for calls in ({'summary': {'amount': Decimal('2.75')}},
                      [{'result': {'summary': {'amount': Decimal('2.75')}}}],
                      [{'result': '{"summary": {"amount": 2.75}}'}]):
            with self.subTest(calls=calls):
                self.assertEqual(hallucinated_numbers('2.75', [], tool_results=calls), [])
        self.assertEqual(hallucinated_numbers('275', [], tool_results={'amount': Decimal('2.75')}), [275])

    def test_missing_data_is_not_zero(self):
        spec = {'answer_extract': {'amount': r'金额(\d+)', 'count': r'记录数(\d+)'}}
        result = score_answer('未找到换刀记录', {'amount': 0, 'count': 0}, spec)
        self.assertFalse(result['exact_match'])
        self.assertEqual(result['extracted'], {'amount': None, 'count': None})
        self.assertTrue(score_answer('金额0 记录数0', {'amount': 0, 'count': 0}, spec)['exact_match'])
        self.assertFalse(score_answer('金额0 记录数0', {'amount': None, 'count': 0}, spec)['exact_match'])
