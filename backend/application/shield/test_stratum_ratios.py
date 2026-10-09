from unittest import TestCase
import math

from application.shield.stratum_ratios import summarize_stratum_exposure, validate_stratum_ratios


class StratumRatioTests(TestCase):
    def test_circle_integration_uses_area_not_height(self):
        from extract_stratum_area_ratios import circular_area_integral as area
        self.assertAlmostEqual(area(1, 0, 1)-area(-1, 0, 1), math.pi)
        self.assertAlmostEqual(area(0, 0, 1)-area(-1, 0, 1), math.pi/2)
        # Top quarter by height is not a quarter of the circular area.
        fraction = (area(1, 0, 1)-area(.5, 0, 1))/math.pi
        self.assertAlmostEqual(fraction, .1955011094778853)

    def test_validation(self):
        self.assertEqual(validate_stratum_ratios({}), {})
        self.assertEqual(validate_stratum_ratios({'A': 25, 'B': 75}), {'A': 25., 'B': 75.})
        for value in (None, [], {'A': True}, {'A': float('nan')}, {'A': 50}, {'A': -1, 'B': 101}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_stratum_ratios(value)

    def test_interval_missing_and_weighting(self):
        rows = [
            {'ring_no': '9', 'stratum_type_ratios': {'A': 100}},
            {'ring_no': '10', 'stratum_type_ratios': {'A': 25, 'B': 75}},
            {'ring_no': '11', 'stratum_type_codes': 'A,B'},
            {'ring_no': '13', 'stratum_type_ratios': {'B': 100}},
        ]
        result = summarize_stratum_exposure(rows, 9, 12)
        self.assertEqual(result['equivalent_rings'], {'A': .25, 'B': .75})
        self.assertEqual(result['missing_rings'], 2)
        self.assertEqual(result['total_rings'], 3)
        self.assertEqual(result['encountered_codes'], ['A', 'B'])

    def test_duplicate_and_invalid_are_missing(self):
        rows = [{'ring_no': '1', 'stratum_type_ratios': {'A': 100}}] * 2
        rows.append({'ring_no': '2', 'stratum_type_ratios': {'A': 50}})
        result = summarize_stratum_exposure(rows, 0, 2)
        self.assertEqual(result['known_rings'], 0)
        self.assertEqual(result['invalid_rings'], [1, 2])

    def test_unresolved_area_is_explicit(self):
        result = summarize_stratum_exposure([
            {'ring_no': '1', 'stratum_type_ratios': {'A': 80, 'UNRESOLVED': 20}},
        ], 0, 2)
        self.assertEqual(result['equivalent_rings'], {'A': .8})
        self.assertEqual(result['known_rings'], 0)
        self.assertEqual(result['missing_rings'], 2)
        self.assertEqual(result['incomplete_rings'], 1)
        self.assertAlmostEqual(result['unknown_area_equivalent_rings'], 1.2)

    def test_conditions_and_positive_area_rocks_are_separate(self):
        result = summarize_stratum_exposure([
            {'ring_no': '1', 'stratum_type_codes': 'WEAK_GRANITE,BOULDER',
             'stratum_type_ratios': {'WEAKLY_WEATHERED_ROCK': 32, 'FULL_WEATHERED_ROCK': 68, 'ZERO': 0}},
            {'ring_no': '2', 'stratum_type_codes': 'SOFT_HARD'},
        ], 0, 2)
        self.assertEqual(result['encountered_codes'], ['FULL_WEATHERED_ROCK', 'WEAKLY_WEATHERED_ROCK'])
        self.assertEqual(result['engineering_condition_codes'], ['BOULDER', 'SOFT_HARD', 'WEAK_GRANITE'])
        self.assertEqual(result['missing_rings'], 1)
