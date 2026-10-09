"""Service-stratum manufacturer cohorts, exercised through the real API action."""
from django.test import TestCase

from .models import OldToolRecord, ProjectInfo, StratumBasicInfo
from . import test_analysis as analysis_helpers


class StratumPerformanceTests(TestCase):
    setUpTestData = classmethod(analysis_helpers.AnalysisContractTests.setUpTestData.__func__)
    opening = analysis_helpers.AnalysisContractTests.opening
    detail = analysis_helpers.AnalysisContractTests.detail
    install = analysis_helpers.AnalysisContractTests.install
    query = analysis_helpers.AnalysisContractTests.query

    def segment(self, start=1, end=4):
        installed = self.detail(self.opening(start), is_replaced=True,
                                manufacturer='原厂家', price=120)
        instance = self.install(installed)
        removed = self.detail(self.opening(end), is_replaced=True,
                              manufacturer='新厂家', price=900, wear_condition='偏磨')
        OldToolRecord.objects.create(tool_change_detail=removed,
                                    confirmed_tool_instance=instance,
                                    inspection_status='CONFIRMED')
        return installed, removed

    def stratum(self, ring, code, ratios=None, project=None):
        return StratumBasicInfo.objects.create(project=project or self.project,
            ring_no=str(ring), stratum_type_codes=code, stratum_type_ratios=ratios or {})

    def data(self, **params):
        return self.query('brand_stratum_performance', **params)

    def test_interval_excludes_install_includes_removal_and_uses_original_vendor(self):
        self.segment()
        self.stratum(1, 'INSTALL_ONLY', {'INSTALL_ONLY': 100})
        self.stratum(2, 'A', {'A': 100})
        self.stratum(3, 'A', {'A': 100})
        self.stratum(4, 'B', {'B': 100})
        data = self.data(start_ring=4, end_ring=4, manufacturer='原厂家')
        self.assertEqual({row['stratum_code'] for row in data['items']}, {'A', 'B'})
        self.assertEqual(data['paired_count'], 1)
        self.assertEqual(len(data['service_rows']), 1)
        for row in data['items']:
            self.assertEqual(row['manufacturer'], '原厂家')
            self.assertEqual(row['avg_installation_price'], 120)
            self.assertEqual(row['avg_service_rings'], 3)
            self.assertEqual(row['complete_ratio_sample_count'], 1)
        by_code = {row['stratum_code']: row for row in data['items']}
        self.assertEqual(by_code['A']['avg_equivalent_rings'], 2)
        self.assertEqual(by_code['B']['avg_equivalent_rings'], 1)
        self.assertEqual(self.data(manufacturer='新厂家')['items'], [])

    def test_project_strata_do_not_leak_into_equal_ring_numbers(self):
        self.segment()
        other = ProjectInfo.objects.create(project_id='STRATUM-OTHER', project_name='其他项目')
        self.stratum(2, 'OTHER', {'OTHER': 100}, project=other)
        self.stratum(2, 'A', {'A': 100})
        data = self.data()
        self.assertEqual([row['stratum_code'] for row in data['items']], ['A'])
        exposure = data['service_rows'][0]['stratum_exposure']
        self.assertEqual(exposure['known_rings'], 1)
        self.assertEqual(exposure['missing_rings'], 2)

    def test_partial_ratios_preserve_known_sum_but_do_not_average_missing_as_zero(self):
        self.segment()
        self.stratum(2, 'A', {'A': 100})
        self.stratum(3, 'A')
        self.stratum(4, 'A')
        row = self.data()['items'][0]
        self.assertEqual(row['known_equivalent_rings'], 1)
        self.assertEqual(row['missing_ratio_rings'], 2)
        self.assertEqual(row['ratio_sample_count'], 1)
        self.assertEqual(row['complete_ratio_sample_count'], 0)
        self.assertIsNone(row['avg_equivalent_rings'])

    def test_tags_without_ratios_are_not_zero_measurements(self):
        self.segment()
        self.stratum(2, 'A')
        data = self.data()
        self.assertEqual(data['items'], [])
        self.assertEqual(data['stratum_options'], [])
        self.assertEqual(data['missing_stratum_segment_count'], 1)
        self.assertEqual(data['service_rows'][0]['stratum_exposure']['engineering_condition_codes'], ['A'])

    def test_engineering_labels_do_not_become_rock_cohorts(self):
        self.segment()
        self.stratum(2, 'WEAK_GRANITE,BOULDER', {'WEAKLY_WEATHERED_ROCK': 32, 'FULL_WEATHERED_ROCK': 68})
        data = self.data()
        self.assertEqual({row['stratum_code'] for row in data['items']}, {'WEAKLY_WEATHERED_ROCK', 'FULL_WEATHERED_ROCK'})
        self.assertEqual(self.data(service_stratum='WEAK_GRANITE')['items'], [])

    def test_serializer_separates_positive_rock_types_and_engineering_conditions(self):
        from .views import StratumBasicInfoSerializer
        row = self.stratum(400, 'WEAK_GRANITE,BOULDER', {'WEAKLY_WEATHERED_ROCK': 32, 'FULL_WEATHERED_ROCK': 68, 'CLAY_3_4_2': 0})
        data = StratumBasicInfoSerializer(row).data
        self.assertEqual({item['code'] for item in data['rock_types_list']}, {'WEAKLY_WEATHERED_ROCK', 'FULL_WEATHERED_ROCK'})
        self.assertEqual({item['code'] for item in data['stratum_types_list']}, {'WEAK_GRANITE', 'BOULDER'})

    def test_old_dictionary_name_is_corrected_only_in_display(self):
        from dvadmin.system.models import Dictionary
        from .stratum_ratios import stratum_label
        parent = Dictionary.objects.create(value='stratum_type', label='地层')
        old = Dictionary.objects.create(parent=parent, value='WEAK_GRANITE', label='全断面弱风化花岗岩')
        row = self.stratum(400, 'WEAK_GRANITE')
        self.assertEqual(row.get_stratum_types()[0]['name'], '弱风化花岗岩段（含局部侵入）')
        self.assertEqual(stratum_label('WEAK_GRANITE'), row.get_stratum_types()[0]['name'])
        old.refresh_from_db()
        self.assertEqual(old.label, '全断面弱风化花岗岩')

    def test_selected_code_uses_whole_segment_not_only_removal_stratum(self):
        self.segment()
        self.stratum(2, 'A', {'A': 100})
        self.stratum(4, 'B', {'B': 100})
        data = self.data(service_stratum='A', start_ring=4, stratum_type='NOT_PRESENT')
        self.assertEqual([row['stratum_code'] for row in data['items']], ['A'])
        self.assertEqual(len(data['service_rows']), 1)
        self.assertEqual(data['meta']['scope']['service_stratum'], 'A')
        absent = self.data(service_stratum='NOT_PRESENT')
        self.assertEqual(absent['items'], [])
        self.assertEqual(absent['service_rows'], [])

    def test_no_samples_and_unpaired_samples_do_not_create_cohorts(self):
        empty = self.data()
        self.assertEqual(empty['items'], [])
        self.assertEqual(empty['paired_count'], 0)
        self.detail(self.opening(4), is_replaced=True, manufacturer='未确认厂家')
        self.stratum(4, 'A', {'A': 100})
        data = self.data()
        self.assertEqual(data['items'], [])
        self.assertEqual(data['service_rows'], [])
        self.assertEqual(data['unpaired_count'], 1)
