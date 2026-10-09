"""The assistant adapts shared wear semantics without owning a second lexicon."""
from django.test import SimpleTestCase

from application.ai_assistant.tools import (
    classify_wear_counts, is_abnormal_wear, is_normal_wear, normalize_wear_condition,
)
from application.shield.test_wear_contract import WEAR_CASES


class AssistantWearContractTests(SimpleTestCase):
    def test_shared_business_classification_preserves_ai_response_format(self):
        for value, state in WEAR_CASES:
            expected = state.lower() if state else 'unknown'
            with self.subTest(value=value):
                self.assertEqual(normalize_wear_condition(value), expected)
                self.assertEqual(is_normal_wear(value), expected == 'normal')
                self.assertEqual(is_abnormal_wear(value), expected == 'abnormal')

    def test_weighted_aggregates_keep_unknown_bucket(self):
        rows = [{'wear_condition': value, 'count': count} for value, count in [
            ('无异常', 3), ('正常磨损', 2), ('异常', 4), ('chip', 1), ('其他', 7), (None, 2),
        ]]
        self.assertEqual(classify_wear_counts(rows, count_key='count'), {
            'normal': 5, 'abnormal': 5, 'unknown': 9,
        })
