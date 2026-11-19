import io
import json
import tempfile
from pathlib import Path
from importlib.util import find_spec
from unittest import TestCase, skipUnless

import numpy as np
from django.core.management import call_command, CommandError
from django.test import TestCase as DatabaseTestCase

from application.shield.longitudinal_ratios import (
    CLASSIFICATION_SCHEME, validate_longitudinal_ratios, withhold_condition_derived_ratios,
)
from extract_longitudinal_ratios import integrate_columns
from extract_six_class_ratios import aggregate_samples
from extract_stratum_area_ratios import hatch_candidate_area
from extract_pdf_stratum_ratios import classify_colors, constrain_classes
from complete_stratum_ratios import complete_payload, smooth_unresolved_areas


class PresentationCompletionTests(TestCase):
    def test_only_unknown_share_is_allocated_using_original_neighbors(self):
        rings = {'1': {'a': 80, 'b': 20}, '2': {'a': 20, 'b': 40, 'UNRESOLVED': 40},
                 '3': {'a': 10, 'b': 30, 'unrelated': 60}}
        result, audit = smooth_unresolved_areas(rings)
        self.assertEqual(result['1'], rings['1'])
        self.assertEqual(result['3'], rings['3'])
        # Neighbor 3 is normalized over only the classes present in ring 2.
        self.assertEqual(result['2'], {'a': 37.166667, 'b': 62.833333})
        self.assertEqual(audit['2']['source_unresolved_percent'], 40)
        self.assertEqual(rings['2']['UNRESOLVED'], 40)
        self.assertEqual(result, smooth_unresolved_areas(dict(reversed(list(rings.items()))))[0])

    def test_boulder_area_stays_fixed_and_unknown_does_not_become_boulder(self):
        result, _ = smooth_unresolved_areas({'1': {
            'AREA_BOULDER': 10.480023, 'AREA_SOFT_HARD': 49.519977, 'UNRESOLVED': 40}})
        self.assertEqual(result['1'], {'AREA_BOULDER': 10.480023, 'AREA_SOFT_HARD': 89.519977})

    def test_no_evidence_is_rejected_and_blank_ring_uses_nearest_original(self):
        with self.assertRaises(ValueError):
            smooth_unresolved_areas({'1': {'UNRESOLVED': 100}})
        with self.assertRaises(ValueError):
            smooth_unresolved_areas({'1': {}})
        result, _ = smooth_unresolved_areas({'1': {'a': 100}, '2': {'UNRESOLVED': 100},
                                           '3': {'UNRESOLVED': 100}, '4': {'b': 100}})
        self.assertEqual(result['2'], {'a': 100})
        self.assertEqual(result['3'], {'b': 100})

    def test_audit_retains_raw_ratios_and_rejects_repeated_completion(self):
        payload = {'measurement_kind': 'longitudinal_section_area_percent',
                   'estimated': True, 'method': 'fixture',
                   'rings': {'1': {'AREA_CLAY_SAND': 60, 'UNRESOLVED': 40}}}
        result = complete_payload(payload)
        self.assertEqual(result['rings']['1'], {'AREA_CLAY_SAND': 100})
        self.assertEqual(result['raw_rings'], payload['rings'])
        self.assertTrue(result['completion']['estimated'])
        with self.assertRaises(ValueError):
            complete_payload(result)
        with self.assertRaises(ValueError):
            complete_payload({**payload, 'estimated': False})


@skipUnless(find_spec('shapely'), '需要 shapely：离线地层提取脚本的依赖，应用环境未安装')
class CandidateGeometryTests(TestCase):
    def test_invalid_dxf_hatch_preserves_both_candidate_lobes(self):
        from shapely.geometry import Point
        geom = hatch_candidate_area([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
        self.assertAlmostEqual(geom.area, 2)
        self.assertTrue(geom.contains(Point(1, .25)))
        self.assertTrue(geom.contains(Point(1, 1.75)))
        # A repaired candidate alone cannot classify an ambiguous PDF pixel.
        classes, codes = classify_colors(np.array([[255, 255, 255]]),
            [('clay', [221, 165, 109]), ('rock', [254, 151, 150])])
        self.assertEqual(codes[constrain_classes(classes, codes, {'rock'})[0]], 'UNRESOLVED')

    def test_repaired_candidate_discards_dangling_line_and_retains_hole(self):
        from shapely.geometry import Point
        geom = hatch_candidate_area([(0, 0), (3, 0), (3, 3), (0, 3), (0, 0),
            (-2, 0), (0, 0)])
        self.assertAlmostEqual(geom.area, 9)
        self.assertFalse(geom.intersects(Point(-1, 0)))
        hole = hatch_candidate_area([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0),
            (1, 1), (1, 3), (3, 3), (3, 1), (1, 1), (0, 0)])
        self.assertAlmostEqual(hole.area, 12)
        self.assertFalse(hole.contains(Point(2, 2)))


class LongitudinalAreaTests(TestCase):
    def test_rectangle_area_not_circle_and_unknown_not_redistributed(self):
        # Upper quarter is 25% of a rectangle (not the circular 19.55%).
        result = integrate_columns(np.array([[0, 1, 1, 2]]),
            ['WEAKLY_WEATHERED_ROCK', 'CLAY_3_3', 'UNRESOLVED'], [10],
            condition_codes=['CLAY_SAND', 'WEAK_GRANITE'])
        self.assertEqual(result, {'OTHER_IDENTIFIED': 50, 'WEAK_GRANITE': 25, 'UNRESOLVED': 25})

    def test_full_ring_width_and_changing_outline_height(self):
        result = integrate_columns(np.array([[0, 0], [1, 1]]),
            ['WEAKLY_WEATHERED_ROCK', 'FULL_WEATHERED_ROCK'], [10, 30],
            condition_codes=['SOFT_HARD', 'WEAK_GRANITE'])
        self.assertEqual(result, {'OTHER_IDENTIFIED': 75, 'WEAK_GRANITE': 25})

    def test_validation_rejects_old_rock_codes_and_invalid_totals(self):
        self.assertEqual(validate_longitudinal_ratios({}), {})
        for value in ({'CLAY_3_3': 100}, {'SOFT_HARD': 50}, {'WEAK_GRANITE': True},
                      {'SOFT_HARD': float('nan')}, {'SOFT_HARD': -1, 'WEAK_GRANITE': 101}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_longitudinal_ratios(value)

    def test_missing_drawing_width_remains_unknown(self):
        result = integrate_columns(np.array([[0, 0], [1, 1]]),
            ['WEAKLY_WEATHERED_ROCK', 'UNRESOLVED'], [10, 10], [0.86, 0.14], ['WEAK_GRANITE'])
        self.assertEqual(result, {'WEAK_GRANITE': 86, 'UNRESOLVED': 14})

    def test_engineering_conditions_never_substitute_for_area_boundaries(self):
        for condition in ('CLAY_SAND', 'SOFT_SOIL', 'SOFT_HARD'):
            result = integrate_columns(np.array([[0, 1, 1, 2]]),
                ['CLAY_3_3', 'FINE_SAND_2_5', 'UNRESOLVED'], [10],
                condition_codes=[condition, 'BOULDER'])
            self.assertEqual(result, {'OTHER_IDENTIFIED': 75, 'UNRESOLVED': 25})
            self.assertNotIn('SOFT_HARD', result)

    def test_no_unique_condition_does_not_invent_soft_hard(self):
        for conditions in ([], ['BOULDER'], ['BEDROCK_PROTRUSION'], ['CLAY_SAND', 'SOFT_HARD']):
            result = integrate_columns(np.array([[0]]), ['CLAY_3_3'], [10], condition_codes=conditions)
            self.assertEqual(result, {'OTHER_IDENTIFIED': 100})

    def test_rock_and_engineering_condition_conflict_stays_unallocated(self):
        result = integrate_columns(np.array([[0]]), ['WEAKLY_WEATHERED_ROCK'], [10],
            condition_codes=['SOFT_SOIL'])
        self.assertEqual(result, {'OTHER_IDENTIFIED': 100})

    def test_stored_old_classifications_are_withheld_without_losing_area(self):
        self.assertEqual(withhold_condition_derived_ratios({
            'CLAY_SAND': 20, 'SOFT_SOIL': 10, 'SOFT_HARD': 30, 'OTHER_IDENTIFIED': 5,
            'WEAK_GRANITE': 25, 'UNRESOLVED': 10,
        }), {'OTHER_IDENTIFIED': 90, 'UNRESOLVED': 10})

    def test_old_whole_ring_zone_shares_are_withheld(self):
        value = {'ZONE_CLAY_SAND': 25, 'ZONE_SOFT_HARD': 60, 'UNRESOLVED': 15}
        self.assertEqual(withhold_condition_derived_ratios(value), {'OTHER_IDENTIFIED':85,'UNRESOLVED':15})

    def test_child_lithologies_aggregate_into_distinct_parent_classes(self):
        classes = np.array([[0, 0, 1, 1, 2]])
        result = aggregate_samples(classes, ['CLAY_3_3','SILTY_CLAY_3_4','UNRESOLVED'],
            np.ones(classes.shape), np.zeros(classes.shape,dtype=bool), np.zeros(classes.shape,dtype=bool))
        self.assertEqual(result, {'AREA_CLAY_SAND':40,'AREA_SOFT_SOIL':40,'UNRESOLVED':20})

    def test_boulders_and_bedrock_override_only_their_actual_areas(self):
        classes = np.array([[0, 0, 0, 1, 2]])
        result = aggregate_samples(classes, ['WEAKLY_WEATHERED_ROCK','FULL_WEATHERED_ROCK','UNRESOLVED'],
            np.array([[1,2,3,2,2]]), np.array([[True,False,False,False,False]]),
            np.array([[True,True,False,True,False]]))
        self.assertEqual(result, {'AREA_BOULDER':10,'AREA_BEDROCK_PROTRUSION':20,
            'AREA_WEAK_GRANITE':30,'AREA_SOFT_HARD':20,'UNRESOLVED':20})
        self.assertEqual(sum(result.values()),100)

    def test_unmapped_child_keeps_unallocated_area(self):
        result=aggregate_samples(np.array([[0]]),['FILL'],np.ones((1,1)),
            np.zeros((1,1),dtype=bool),np.zeros((1,1),dtype=bool))
        self.assertEqual(result,{'OTHER_IDENTIFIED':100})

    def test_silty_clay_is_not_muddy_clay_soft_soil(self):
        result=aggregate_samples(np.array([[0,1]]),['CLAY_2_5_4','SILTY_CLAY_2_5'],
            np.ones((1,2)),np.zeros((1,2),dtype=bool),np.zeros((1,2),dtype=bool))
        self.assertEqual(result,{'AREA_CLAY_SAND':50,'AREA_SOFT_SOIL':50})

    def test_fill_sand_uses_the_medium_sand_symbol_parent(self):
        result=aggregate_samples(np.array([[0,1]]),['FILL_SAND','MEDIUM_SAND_3_3'],
            np.ones((1,2)),np.zeros((1,2),dtype=bool),np.zeros((1,2),dtype=bool))
        self.assertEqual(result,{'AREA_CLAY_SAND':100})


class LongitudinalImportTests(DatabaseTestCase):
    def setUp(self):
        from application.shield.models import ProjectInfo, StratumBasicInfo
        self.project = ProjectInfo.objects.create(project_id='LONG-TEST', project_name='纵断面测试')
        self.row = StratumBasicInfo.objects.create(project=self.project, ring_no='1',
            stratum_type_codes='SOFT_HARD,WEAK_GRANITE,BOULDER', stratum_type_ratios={'CLAY_3_3': 100})
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ratios.json'
        self.payload = {'measurement_kind': 'longitudinal_section_area_percent',
            'classification_scheme': CLASSIFICATION_SCHEME,
            'estimated': True, 'source': 'fixture.pdf', 'source_sha256': 'test', 'method': 'test',
            'rings': {'1': {'AREA_SOFT_HARD': 70, 'AREA_WEAK_GRANITE': 20, 'UNRESOLVED': 10}}}

    def run_import(self, apply=False):
        self.path.write_text(json.dumps(self.payload), encoding='utf-8')
        call_command('import_longitudinal_ratios', json=str(self.path),
            project=self.project.project_id, apply=apply, stdout=io.StringIO())

    def test_preview_apply_and_preserve_original_fields(self):
        from application.shield.views import StratumBasicInfoSerializer
        self.run_import()
        self.row.refresh_from_db()
        self.assertEqual(self.row.longitudinal_type_ratios, {})
        self.run_import(True)
        self.row.refresh_from_db()
        self.assertEqual(self.row.longitudinal_type_ratios, self.payload['rings']['1'])
        self.assertEqual(self.row.stratum_type_ratios, {'CLAY_3_3': 100})
        self.assertEqual(self.row.stratum_type_codes, 'SOFT_HARD,WEAK_GRANITE,BOULDER')
        data = StratumBasicInfoSerializer(self.row).data
        self.assertEqual(data['longitudinal_type_ratios'], self.payload['rings']['1'])
        self.assertEqual(data['rock_types_list'][0]['code'], 'CLAY_3_3')
        self.assertEqual([r['code'] for r in data['engineering_zones_list']],
                         ['AREA_SOFT_HARD', 'AREA_WEAK_GRANITE'])
        self.assertNotIn('工程地质条件的分类面积尚未核定', data['longitudinal_area_notes'])

    def test_missing_ring_rejects_entire_import(self):
        self.payload['rings']['2'] = {'AREA_SOFT_HARD': 100}
        with self.assertRaises(CommandError):
            self.run_import(True)
        self.row.refresh_from_db()
        self.assertEqual(self.row.longitudinal_type_ratios, {})

    def test_old_measurement_kind_rejected(self):
        self.payload['measurement_kind'] = 'cross_section_area_percent'
        with self.assertRaises(CommandError):
            self.run_import(True)

    def test_old_classification_rejected(self):
        self.payload.pop('classification_scheme')
        with self.assertRaises(CommandError):
            self.run_import(True)

    def test_tag_derived_area_rejected_even_when_tag_matches(self):
        self.payload['rings']['1'] = {'SOFT_HARD': 100}
        with self.assertRaisesMessage(CommandError, '面积边界'):
            self.run_import(True)

    def test_mixed_conditions_and_boulder_are_not_reported_as_measured_soft_hard(self):
        from application.shield.views import StratumBasicInfoSerializer
        self.row.stratum_type_codes = 'BEDROCK_PROTRUSION,WEAK_GRANITE,SOFT_HARD,BOULDER'
        self.row.longitudinal_type_ratios = {'SOFT_HARD': 96.67, 'UNRESOLVED': 3.33}
        data = StratumBasicInfoSerializer(self.row).data
        self.assertEqual(data['longitudinal_type_ratios'], {'OTHER_IDENTIFIED': 96.67, 'UNRESOLVED': 3.33})
        self.assertIn('孤石：有区段记录，面积尚未核定', data['longitudinal_area_notes'])
        self.assertEqual(self.row.longitudinal_type_ratios, {'SOFT_HARD': 96.67, 'UNRESOLVED': 3.33})

    def test_reviewed_geometry_takes_precedence_over_old_interval_tags(self):
        self.row.stratum_type_codes = 'CLAY_SAND'
        self.row.save(update_fields=['stratum_type_codes'])
        self.run_import(True)
        self.row.refresh_from_db()
        self.assertEqual(self.row.longitudinal_type_ratios, self.payload['rings']['1'])
        self.assertEqual(self.row.stratum_type_codes, 'CLAY_SAND')

    def test_old_weak_lithology_cannot_masquerade_as_full_section_zone(self):
        self.payload['rings']['1'] = {'WEAK_GRANITE': 100}
        with self.assertRaisesMessage(CommandError, '六类编码'):
            self.run_import(True)

    def test_bedrock_partition_and_overlay_notes_are_separate(self):
        from application.shield.views import StratumBasicInfoSerializer
        self.row.longitudinal_type_ratios = {'AREA_BEDROCK_PROTRUSION': 90, 'AREA_BOULDER':10}
        data = StratumBasicInfoSerializer(self.row).data
        self.assertEqual(data['engineering_zones_list'],
                         [{'code': 'AREA_BEDROCK_PROTRUSION', 'name': '基岩凸起地层'},
                          {'code':'AREA_BOULDER','name':'孤石'}])
        self.assertIn('孤石按图示轮廓面积估算', data['longitudinal_area_notes'])

    def test_import_rejects_old_primary_zone_even_with_current_version(self):
        self.payload['rings']['1']={'ZONE_SOFT_HARD':100}
        with self.assertRaises(CommandError):
            self.run_import(True)
