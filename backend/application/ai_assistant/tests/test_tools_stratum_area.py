import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from application.ai_assistant.tools_stratum_area import query_opening_stratum, query_stratum_area
from application.shield.models import (
    ProjectInfo, ShieldMachineBasicInfo, StratumBasicInfo, WarehouseOpeningBasicInfo,
)


class StratumAreaToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='AREA', project_name='面积测试')
        cls.other = ProjectInfo.objects.create(project_id='OTHER', project_name='其他项目')
        StratumBasicInfo.objects.bulk_create([
            StratumBasicInfo(project=cls.project, ring_no='1', stratum_type_codes='BOULDER',
                             longitudinal_type_ratios={'AREA_CLAY_SAND': 100, 'AREA_BOULDER': 0},
                             stratum_type_ratios={'FILL': 25, 'CLAY_3_3': 75}),
            StratumBasicInfo(project=cls.project, ring_no='2', stratum_type_codes='CLAY_SAND',
                             longitudinal_type_ratios={'AREA_CLAY_SAND': 50, 'AREA_BOULDER': 50}),
            StratumBasicInfo(project=cls.project, ring_no='3'),
            StratumBasicInfo(project=cls.other, ring_no='1', longitudinal_type_ratios={'AREA_BOULDER': 100}),
        ])

    def query(self, **params):
        return json.loads(query_stratum_area(json.dumps({'project_id': 'AREA', **params})))

    def test_area_is_independent_of_legacy_labels_and_shares_use_area(self):
        result = self.query(rings=[2, 1])
        boulder = next(row for row in result['classes'] if row['code'] == 'AREA_BOULDER')
        self.assertEqual(boulder['positive_ring_count'], 1)
        self.assertEqual(boulder['area_equivalent_rings'], 0.5)
        self.assertEqual(boulder['share_pct'], 25.0)
        self.assertEqual(result['classes'][0]['code'], 'AREA_CLAY_SAND')
        self.assertEqual(result['classes'][0]['share_pct'], 75.0)
        self.assertEqual([row['ring_no'] for row in result['per_ring']], [1, 2])
        ratios = {row['code']: row['pct'] for row in result['per_ring'][0]['ratios']}
        self.assertEqual(ratios['AREA_BOULDER'], 0)
        self.assertIn('补齐', result['source_note'])
        self.assertIn('不能据此判断刀具磨损的原因', result['note'])

    def test_empty_and_absent_rings_do_not_reduce_average(self):
        result = self.query(ring_range=[1, 4])
        self.assertEqual(result['ring_count_requested'], 4)
        self.assertEqual(result['ring_count_with_data'], 2)
        self.assertEqual(result['missing_rings'], [3, 4])
        self.assertEqual(result['missing_ring_count'], 2)
        self.assertEqual(result['classes'][0]['share_pct'], 75)
        self.assertEqual(result['per_ring'][-1]['ratios'], [])

    def test_cross_section_uses_its_own_field_and_denominator(self):
        result = self.query(ring_range=[1, 2], basis='cross_section')
        self.assertEqual(result['basis_label'], '横断面岩性占比')
        self.assertEqual(result['ring_count_with_data'], 1)
        self.assertEqual(result['missing_rings'], [2])
        self.assertEqual(result['classes'][0]['code'], 'CLAY_3_3')
        self.assertEqual(result['classes'][0]['share_pct'], 75)

    def test_missing_data_gives_null_share_and_caps_missing_ring_list(self):
        result = self.query(ring_range=[10, 70])
        self.assertEqual(result['missing_ring_count'], 61)
        self.assertEqual(len(result['missing_rings']), 50)
        self.assertIsNone(result['per_ring'])
        self.assertTrue(all(row['share_pct'] is None for row in result['classes']))
        self.assertEqual(len(self.query(ring_range=[1, 20])['per_ring']), 20)
        self.assertIsNone(self.query(ring_range=[1, 21])['per_ring'])

    def test_invalid_ratios_and_old_zones_are_missing_not_six_class_areas(self):
        StratumBasicInfo.objects.bulk_create([
            StratumBasicInfo(project=self.project, ring_no='4', longitudinal_type_ratios={'AREA_BOULDER': 40}),
            StratumBasicInfo(project=self.project, ring_no='5', longitudinal_type_ratios={'ZONE_CLAY_SAND': 100}),
        ])
        result = self.query(ring_range=[1, 5])
        self.assertEqual(result['ring_count_with_data'], 2)
        self.assertEqual(result['missing_rings'], [3, 4, 5])
        self.assertTrue(any('校验' in warning for warning in result['warnings']))

    def test_parameters_reject_invalid_basis_conflicts_and_bad_ranges(self):
        for params in ({'basis': 'legacy'}, {'rings': [1], 'ring_range': [1, 2]},
                       {'ring_range': [2, 1]}, {'ring_range': [0, 2]}, {'rings': []},
                       {'rings': list(range(1, 52))}, {'rings': [1, True]}, {'rings': [1, 1]}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
        self.assertIn('longitudinal_area', self.query(basis='wrong')['error'])
        self.assertIn('error', json.loads(query_stratum_area('[]')))
        self.assertIn('error', json.loads(query_stratum_area('{')))

    def test_all_projects_do_not_collapse_identical_ring_numbers(self):
        result = json.loads(query_stratum_area('{}'))
        self.assertEqual(result['ring_count_requested'], 4)
        self.assertEqual(result['ring_count_with_data'], 3)
        boulder = next(row for row in result['classes'] if row['code'] == 'AREA_BOULDER')
        self.assertEqual(boulder['share_pct'], 50)
        self.assertEqual({row['project_id'] for row in result['per_ring']}, {'AREA', 'OTHER'})


class OpeningStratumToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='OPEN-STRATA', project_name='开仓地层')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='S1', shield_model='S1')
        other_machine = ShieldMachineBasicInfo.objects.create(shield_model_id='S2', shield_model='S2')
        cls.first = WarehouseOpeningBasicInfo(
            warehouse_id='STRATA-3', project=cls.project, shield_model=cls.machine, ring_no='3',
            open_time=timezone.now(), stratum_info_between={'SOFT_HARD': 3}, geological_conditions='当时文字',
        )
        cls.second = WarehouseOpeningBasicInfo(
            warehouse_id='STRATA-6', project=cls.project, shield_model=cls.machine, ring_no='6',
            open_time=timezone.now(), stratum_info_between={'SOFT_SOIL': 2, 'CLAY_SAND': 1},
        )
        WarehouseOpeningBasicInfo.objects.bulk_create([
            cls.first, cls.second,
            WarehouseOpeningBasicInfo(warehouse_id='OTHER-5', project=cls.project, shield_model=other_machine,
                                      ring_no='5', open_time=timezone.now()),
        ])
        StratumBasicInfo.objects.bulk_create([
            StratumBasicInfo(project=cls.project, ring_no=str(ring), stratum_type_codes=code,
                             longitudinal_type_ratios={'AREA_CLAY_SAND': 100}, stratum_type_ratios={'FILL': 100})
            for ring, code in [(1, 'CLAY_SAND'), (2, 'CLAY_SAND'), (3, 'BOULDER'),
                               (4, 'SOFT_SOIL'), (5, 'SOFT_SOIL'), (6, 'CLAY_SAND')]
        ])

    def query(self, **params):
        return json.loads(query_opening_stratum(json.dumps({
            'project_id': self.project.project_id, 'shield_machine_id': self.machine.pk, **params,
        })))

    def test_first_interval_starts_at_one_and_snapshot_is_unchanged(self):
        before = WarehouseOpeningBasicInfo.objects.filter(pk=self.first.pk).values().get()
        with CaptureQueriesContext(connection) as queries:
            result = self.query(ring_no=3)['openings'][0]
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries))
        self.assertIsNone(result['previous_opening_ring'])
        self.assertEqual(result['interval'], [1, 3])
        self.assertEqual(result['interval_summary']['legacy_label_ring_counts'], {'CLAY_SAND': 2, 'BOULDER': 1})
        self.assertEqual(result['interval_summary']['longitudinal_area'][0]['area_equivalent_rings'], 3)
        self.assertEqual(result['saved_snapshot'], {'stratum_info_between': {'SOFT_HARD': 3}, 'geological_conditions': '当时文字'})
        self.assertTrue(result['snapshot_differs_from_current'])
        self.assertEqual(before, WarehouseOpeningBasicInfo.objects.filter(pk=self.first.pk).values().get())

    def test_next_interval_excludes_previous_ring_and_other_machine(self):
        result = self.query(ring_no=6)['openings'][0]
        self.assertEqual(result['previous_opening_ring'], 3)
        self.assertEqual(result['interval'], [4, 6])
        self.assertEqual(result['interval_summary']['legacy_label_ring_counts'], {'SOFT_SOIL': 2, 'CLAY_SAND': 1})
        self.assertFalse(result['snapshot_differs_from_current'])
        self.assertEqual(result['current_ring']['legacy_labels'][0]['code'], 'CLAY_SAND')
        self.assertIsNone(result['current_ring']['legacy_labels'][0]['pct'])
        self.assertEqual(result['current_ring']['longitudinal_area'][0]['pct'], 100)
        self.assertEqual(result['current_ring']['cross_section'][0]['code'], 'FILL')

    def test_recent_default_order_and_invalid_selectors(self):
        self.assertEqual([row['ring_no'] for row in self.query()['openings']], [6])
        self.assertEqual([row['ring_no'] for row in self.query(recent_openings=2)['openings']], [6, 3])
        for params in ({'ring_no': 3, 'recent_openings': 1}, {'recent_openings': 21}, {'ring_no': 0}):
            with self.subTest(params=params):
                self.assertIn('error', self.query(**params))
