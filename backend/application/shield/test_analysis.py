"""Analysis API contract tests using the isolated Django test database."""
from django.test import TestCase
from django.utils import timezone
from datetime import datetime, timedelta, timezone as datetime_timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from .analysis_views import AnalysisViewSet
from .models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo,
    ToolChangeDetail, ToolInstance, WarehouseOpeningBasicInfo,
)


class AnalysisContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='ANALYSIS-TEST', project_name='分析测试')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='ANALYSIS-A', shield_model='A机')

    def opening(self, ring, **fields):
        fields.setdefault('summary_status', 'CONFIRMED')
        fields.setdefault('shield_model', self.machine)
        row = WarehouseOpeningBasicInfo(
            project=self.project, warehouse_id=f'{ring}-{WarehouseOpeningBasicInfo.objects.count()}',
            ring_no=str(ring), open_time=timezone.now(), **fields,
        )
        WarehouseOpeningBasicInfo.objects.bulk_create([row])
        return row

    def detail(self, opening, position='1', **fields):
        fields.setdefault('tool_parent_type', 'SCRAPER' if position.upper().startswith('S') else 'DISC')
        row = ToolChangeDetail(warehouse=opening, cutter_position_no=position, **fields)
        ToolChangeDetail.objects.bulk_create([row])
        return row

    def query(self, action, **params):
        request = APIRequestFactory().get('/api/shield/analysis/' + action + '/', {'project': self.project.pk, **params})
        view = AnalysisViewSet.as_view({'get': action}, authentication_classes=[], permission_classes=[])
        response = view(request)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['code'], 2000)
        return response.data['data']

    def install(self, detail):
        instance = ToolInstance.objects.create(tool_uid=f'instance-{detail.pk}', display_tool_no=f'tool-{detail.pk}')
        NewToolRecord.objects.create(tool_change_detail=detail, tool_instance=instance)
        return instance

    def test_confirmed_default_active_observed_and_summary_gap(self):
        opening = self.opening(100, checked_tool_count=6, replaced_tool_count=3)
        self.detail(opening, is_checked=True, is_replaced=True, price=100)
        self.detail(opening, '2', wear_condition='NORMAL')
        self.detail(opening, 'G1L', is_checked=True, is_replaced=True, price=900)
        self.detail(self.opening(200, summary_status='DRAFT'), is_checked=True, is_replaced=True)
        data = self.query('overview')
        self.assertEqual(data['kpi']['total_replacements'], 1)
        self.assertEqual(data['kpi']['detail_checked_count'], 1)
        self.assertEqual(data['kpi']['replacement_gap'], 2)
        self.assertEqual(data['meta']['draft_opening_count'], 1)
        self.assertEqual(data['meta']['excluded_inactive_count'], 1)
        self.assertEqual(data['meta']['unobserved_count'], 1)
        self.assertEqual(data['meta']['schema_version'], 2)
        self.assertEqual(self.query('overview', summary_status='ALL')['kpi']['total_replacements'], 2)

    def test_untyped_replacements_are_in_monthly_total(self):
        self.detail(self.opening(100), is_replaced=True, price=100)
        data = self.query('overview')
        self.assertEqual(data['monthly_trend'][0]['untyped'], 1)
        self.assertEqual(data['monthly_trend'][0]['total_replacements'], data['kpi']['total_replacements'])

    def test_custom_precreated_normal_is_not_an_inspection(self):
        opening = self.opening(100)
        self.detail(opening, wear_condition='NORMAL')
        self.detail(opening, '2', is_checked=True, wear_condition='')
        data = self.query('custom_chart', metrics='checked_tool_count,abnormal_rate')
        self.assertEqual(data['record_count'], 1)
        self.assertEqual(data['series'][0]['data'], [1])
        self.assertEqual(data['series'][1]['data'], [None])

    def test_invalid_scope_is_rejected_not_broadened(self):
        view = AnalysisViewSet.as_view({'get': 'overview'}, authentication_classes=[], permission_classes=[])
        for params in ({'project': 'invalid'}, {'start_ring': 200, 'end_ring': 100}, {'summary_status': 'invalid'}):
            response = view(APIRequestFactory().get('/', params))
            self.assertEqual(response.data['code'], 4000)
            self.assertIsNone(response.data['data'])

    def test_scope_names_are_unique_with_ring_annotations_and_multiple_openings(self):
        from django.db.models import Count
        from .analysis_views import _build_opening_queryset, _meta
        for ring in (100, 200, 300):
            self.detail(self.opening(ring), is_checked=True)
        params = {'project': str(self.project.pk), 'start_ring': '100', 'end_ring': '300'}
        openings = _build_opening_queryset(params).annotate(detail_count=Count('tool_change_details'))
        meta = _meta(openings, params)
        self.assertEqual(meta['scope']['project_name'], '分析测试')
        self.assertEqual(meta['scope']['shield_machine_name'], 'A机')
        self.assertEqual(self.query('overview', start_ring=100)['meta']['scope']['project_name'], '分析测试')

    def test_track_invalid_bounds_are_rejected_by_every_action(self):
        actions = ('filter_options', 'custom_fields', 'custom_chart', 'overview', 'cost_overview', 'cost_trend',
                   'brand_cost', 'brand_price_trend', 'brand_performance_trend', 'wear_distribution', 'wear_trend')
        for action in actions:
            view = AnalysisViewSet.as_view({'get': action}, authentication_classes=[], permission_classes=[])
            for params in ({'blade_track_min': '-1'}, {'blade_track_max': 'NaN'}, {'blade_track_max': 'Infinity'},
                           {'blade_track_min': '1e3'}, {'blade_track_min': 'x'},
                           {'blade_track_min': '200', 'blade_track_max': '100'}):
                with self.subTest(action=action, params=params):
                    response = view(APIRequestFactory().get('/', params))
                    self.assertEqual(response.data['code'], 4000)
                    self.assertIsNone(response.data['data'])

    def test_track_bounds_are_inclusive_decimal_current_position_radii(self):
        opening = self.opening(100, blade_track='历史文本 R6810')
        for position in ('1', '14', '18', 'S19L', 'S19R', 'Y2'):
            self.detail(opening, position, is_replaced=True, price=10)
        def positions(**bounds):
            return {row['cutter_position_no'] for row in self.query('cost_overview', **bounds)['source_rows']}
        self.assertEqual(positions(blade_track_min='0', blade_track_max='135'), {'1'})
        self.assertEqual(positions(blade_track_min='1655', blade_track_max='1655'), {'18'})
        self.assertEqual(positions(blade_track_min='2035', blade_track_max='2035'), {'14'})
        self.assertEqual(positions(blade_track_min='6765.2', blade_track_max='6765.20'), {'S19L', 'S19R'})
        self.assertEqual(positions(blade_track_min='6810'), set())
        self.assertEqual(positions(blade_track_max='0'), set())
        meta = self.query('overview', blade_track_min='6765.2')['meta']
        self.assertEqual(meta['scope']['blade_track_min'], '6765.2')
        self.assertIn('blade_track_range', meta['filter_capabilities'])
        self.assertIn('中心', meta['blade_track_basis'])

    def test_track_range_applies_to_sources_wear_custom_options_and_summary_counts(self):
        opening = self.opening(100, checked_tool_count=2, replaced_tool_count=2)
        self.install(self.detail(opening, '1', is_checked=True, is_replaced=True, price=100, manufacturer='A', wear_condition='NORMAL'))
        self.install(self.detail(opening, '2', is_checked=True, is_replaced=True, price=900, manufacturer='B', wear_condition='偏磨'))
        scope = {'blade_track_min': '135', 'blade_track_max': '135'}
        overview = self.query('overview', **scope)
        self.assertEqual(overview['kpi']['total_replacements'], 1)
        self.assertEqual(overview['kpi']['total_cost'], 100)
        self.assertEqual(overview['kpi']['summary_detail_replaced_count'], 2)
        self.assertEqual(overview['kpi']['replacement_gap'], 0)
        self.assertEqual(self.query('cost_trend', **scope)['items'][0]['replacement_count'], 1)
        self.assertEqual(self.query('cost_overview', **scope)['cost_sources']['total'], 100)
        self.assertEqual(self.query('wear_distribution', **scope)['normal_count'], 1)
        self.assertEqual(self.query('wear_distribution', **scope)['abnormal_count'], 0)
        self.assertEqual(self.query('wear_trend', **scope)['items'][0]['checked_count'], 1)
        self.assertEqual(self.query('custom_chart', metrics='total_cost', **scope)['series'][0]['data'], [100])
        self.assertEqual(self.query('filter_options', **scope)['manufacturers'], ['A'])
        self.assertEqual(self.query('brand_price_trend', **scope)['series'][0]['data'], [100])
        self.assertEqual(self.query('brand_cost', **scope)['items'][0]['manufacturer'], 'A')
        self.assertIn('blade_track_range', self.query('custom_fields', **scope)['meta']['filter_capabilities'])

    def test_track_removal_scope_keeps_prior_install_outside_ring_and_radius_range(self):
        installed = self.detail(self.opening(100), '1', is_replaced=True, price=100, manufacturer='A')
        instance = self.install(installed)
        removed = self.detail(self.opening(200), '2', is_replaced=True, price=200, manufacturer='B', wear_condition='偏磨')
        self.install(removed)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance,
                                    inspection_status='CONFIRMED', repair_price=20)
        scope = {'start_ring': 200, 'end_ring': 200, 'blade_track_min': '255', 'blade_track_max': '255', 'manufacturer': 'A'}
        brand = self.query('brand_cost', **scope)
        self.assertEqual(brand['service_rows'][0]['installation_detail_id'], installed.pk)
        self.assertEqual(brand['service_rows'][0]['service_rings'], 100)
        self.assertEqual(brand['cost_sources']['confirmed_repair'], 20)
        self.assertEqual(self.query('brand_performance_trend', **scope)['lifespan_series'][0]['data'], [100])
        self.assertEqual(self.query('cost_overview', **scope)['cost_sources']['total'], 20)
        self.assertEqual(self.query('wear_distribution', **scope)['abnormal_count'], 1)
        self.assertEqual(self.query('custom_chart', metrics='total_cost', x_field='manufacturer', **scope)['series'][0]['data'], [20])

    def test_track_range_does_not_hide_competing_removal_outside_radius_or_ring(self):
        installed = self.detail(self.opening(100), '1', is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        for ring, position in ((200, '2'), (300, '3')):
            removed = self.detail(self.opening(ring), position, is_replaced=True)
            OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        result = self.query('brand_cost', start_ring=200, end_ring=200, blade_track_min='255', blade_track_max='255')
        self.assertEqual(len(result['service_rows']), 1)
        self.assertFalse(result['service_rows'][0]['paired'])
        self.assertIn('多个', result['service_rows'][0]['reason'])

    def test_modern_install_repair_and_legacy_cost_reconcile(self):
        first, second = self.opening(100), self.opening(200)
        modern = self.detail(first, is_replaced=True, price=100)
        self.install(modern)
        OldToolRecord.objects.create(tool_change_detail=modern, inspection_status='CONFIRMED', repair_price=25)
        self.detail(second, is_replaced=True, price=40, replacement_type='COMPLETE')
        self.detail(second, '2', is_replaced=True, price=10)
        overview = self.query('cost_overview')
        self.assertEqual(overview['cost_sources']['total'], 175)
        self.assertEqual(overview['cost_sources']['installation'], 100)
        self.assertEqual(overview['cost_sources']['confirmed_repair'], 25)
        self.assertEqual(overview['cost_sources']['legacy'], 50)
        self.assertEqual(sum(row['total'] for row in overview['type_breakdown']), 175)
        trend = self.query('cost_trend')['items']
        self.assertEqual(trend[-1]['cumulative_cost'], 175)
        self.assertEqual(self.query('overview')['kpi']['total_cost'], 175)
        self.assertEqual(overview['source_rows_total'], len(overview['source_rows']))

    def test_feedback_status_zero_and_missing_prices_remain_distinct(self):
        opening = self.opening(100)
        missing = self.detail(opening, is_replaced=True)
        self.install(missing)
        OldToolRecord.objects.create(tool_change_detail=missing, inspection_status='CONFIRMED')
        zero = self.detail(opening, '2', is_replaced=True, price=0)
        self.install(zero)
        repair = OldToolRecord.objects.create(tool_change_detail=zero, repair_price=15)
        part = self.query('cost_overview')['cost_sources']
        self.assertEqual((part['priced_count'], part['missing_price_count'], part['repair_missing_price_count'], part['pending_repair_count']), (1, 1, 1, 1))
        repair.inspection_status = 'CLOSED'
        repair.save()
        part = self.query('cost_overview')['cost_sources']
        self.assertEqual(part['total'], 15)
        self.assertEqual(part['pending_repair_count'], 0)

    def test_legacy_repair_overlap_is_quarantined(self):
        detail = self.detail(self.opening(100), is_replaced=True, price=50, replacement_type='REPAIR')
        OldToolRecord.objects.create(tool_change_detail=detail, repair_price=60, inspection_status='CLOSED')
        part = self.query('cost_overview')['cost_sources']
        self.assertEqual((part['total'], part['unresolved'], part['unresolved_count']), (0, 110, 1))

    def test_source_filter_includes_modern_repair_without_legacy_type(self):
        detail = self.detail(self.opening(100), is_replaced=True, price=100)
        self.install(detail)
        OldToolRecord.objects.create(tool_change_detail=detail, repair_price=20, inspection_status='CONFIRMED')
        self.assertEqual(self.query('cost_overview', cost_type='REPAIR')['cost_sources']['total'], 20)
        self.assertEqual(self.query('cost_overview', cost_type='COMPLETE')['cost_sources']['total'], 100)

    def test_unit_allocation_is_unavailable_for_single_or_multiple_machine(self):
        self.opening(100)
        self.assertIsNone(self.query('cost_overview')['cost_per_ring']['total'])
        self.opening(200)
        self.assertTrue(self.query('cost_overview')['cost_per_ring']['available'])
        other = ShieldMachineBasicInfo.objects.create(shield_model_id='ANALYSIS-B', shield_model='B')
        self.opening(300, shield_model=other)
        self.assertFalse(self.query('cost_overview')['cost_per_ring']['available'])

    def test_vendor_wear_follows_old_install_and_filter_preserves_segment(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A', price=100)
        old = self.install(installed)
        removed = self.detail(self.opening(200), is_replaced=True, manufacturer='B', price=200, wear_condition='偏磨')
        current = self.install(removed)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=old, inspection_status='CONFIRMED', repair_price=20)
        next_removed = self.detail(self.opening(300), is_replaced=True, manufacturer='A', price=300, wear_condition='正常')
        self.install(next_removed)
        OldToolRecord.objects.create(tool_change_detail=next_removed, confirmed_tool_instance=current, inspection_status='CONFIRMED')
        data = self.query('brand_cost', manufacturer='A', start_ring=200, end_ring=300)
        item = data['items'][0]
        self.assertEqual((item['manufacturer'], item['avg_lifespan'], item['lifespan_count']), ('A', 100, 1))
        self.assertEqual(item['abnormal_rate'], 1)
        self.assertEqual(item['cost_sources']['confirmed_repair'], 20)
        trend = self.query('brand_performance_trend', manufacturer='A', start_ring=200, end_ring=300)
        self.assertEqual(trend['lifespan_series'][0]['data'], [100, None])
        self.assertEqual(trend['abnormal_rate_series'][0]['data'], [1, None])
        cost = self.query('cost_overview', manufacturer='A', start_ring=200, end_ring=300)
        self.assertEqual(cost['cost_sources']['confirmed_repair'], 20)

    def test_suggested_cross_machine_duplicate_and_same_ring_do_not_make_lifetimes(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        first = self.detail(self.opening(200), is_replaced=True, manufacturer='B')
        old = OldToolRecord.objects.create(tool_change_detail=first, suggested_tool_instance=instance)
        self.assertEqual(self.query('brand_cost')['pairing_unresolved_count'], 2)
        old.confirmed_tool_instance = instance
        old.inspection_status = 'CONFIRMED'
        old.save()
        duplicate = self.detail(self.opening(300), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=duplicate, confirmed_tool_instance=instance, inspection_status='CLOSED')
        self.assertEqual(sum(row['lifespan_count'] for row in self.query('brand_cost')['items']), 0)

    def test_no_price_or_wear_sample_is_null_not_zero(self):
        detail = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        self.install(detail)
        item = self.query('brand_cost')['items'][0]
        self.assertIsNone(item['avg_cost'])
        self.assertIsNone(item['abnormal_rate'])
        self.assertEqual(item['missing_price_count'], 1)
        self.assertEqual(self.query('brand_price_trend')['series'][0]['data'], [None])

    def test_custom_cost_includes_repair_and_rejects_new_vendor_wear(self):
        detail = self.detail(self.opening(100), is_replaced=True, manufacturer='A', price=100)
        self.install(detail)
        OldToolRecord.objects.create(tool_change_detail=detail, repair_price=20, inspection_status='CONFIRMED')
        result = self.query('custom_chart', metrics='total_cost,avg_price')
        self.assertEqual(result['series'][0]['data'], [120])
        self.assertEqual(result['series'][1]['data'], [100])
        request = APIRequestFactory().get('/', {'x_field': 'manufacturer', 'metrics': 'abnormal_rate'})
        response = AnalysisViewSet.as_view({'get': 'custom_chart'}, authentication_classes=[], permission_classes=[])(request)
        self.assertEqual(response.data['code'], 4000)

    def test_cross_machine_and_same_ring_pairs_are_excluded(self):
        install_opening = self.opening(100)
        installed = self.detail(install_opening, is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        other = ShieldMachineBasicInfo.objects.create(shield_model_id='OTHER', shield_model='OTHER')
        removed = self.detail(self.opening(200, shield_model=other), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        rows = self.query('brand_cost', start_ring=200)['service_rows']
        self.assertFalse(rows[0]['paired'])
        self.assertIsNone(rows[0]['service_rings'])
        same_ring = self.detail(self.opening(100), '2', is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=same_ring, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        rows = self.query('brand_cost', end_ring=100)['service_rows']
        self.assertTrue(any(row['reason'] == '同环拆装待核对' for row in rows))

    def test_multiple_installations_resolve_latest_segment_not_first_install(self):
        first = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        instance = self.install(first)
        first_remove = self.detail(self.opening(150), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=first_remove, confirmed_tool_instance=instance, inspection_status='CLOSED')
        second = self.detail(self.opening(200), is_replaced=True, manufacturer='A')
        NewToolRecord.objects.create(tool_change_detail=second, tool_instance=instance)
        last = self.detail(self.opening(250), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=last, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        result = self.query('brand_cost', start_ring=250, manufacturer='A')
        self.assertEqual(result['items'][0]['avg_lifespan'], 50)
        self.assertEqual(result['service_rows'][0]['installation_ring_no'], '200')

    def test_cost_source_filter_and_custom_vendor_cost_reconcile(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A', price=100)
        instance = self.install(installed)
        removed = self.detail(self.opening(200), is_replaced=True, manufacturer='B', price=200)
        self.install(removed)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED', repair_price=30)
        result = self.query('custom_chart', start_ring=200, manufacturer='A', x_field='manufacturer', metrics='total_cost')
        self.assertEqual(result['series'][0]['data'], [30])
        result = self.query('custom_chart', start_ring=200, cost_type='REPAIR', metrics='total_cost')
        self.assertEqual(result['series'][0]['data'], [30])
        wear = self.query('wear_trend', manufacturer='A', start_ring=200)['items'][0]
        self.assertEqual(wear['checked_count'], 1)
        self.assertIsNone(wear['abnormal_rate'])

    def test_withdrawal_and_feedback_updates_have_no_stale_aggregate(self):
        opening = self.opening(100)
        detail = self.detail(opening, is_replaced=True, price=100)
        self.install(detail)
        self.assertEqual(self.query('overview')['kpi']['total_cost'], 100)
        WarehouseOpeningBasicInfo.objects.filter(pk=opening.pk).update(summary_status='DRAFT')
        self.assertEqual(self.query('overview')['kpi']['total_cost'], 0)
        self.assertEqual(self.query('overview', summary_status='DRAFT')['kpi']['total_cost'], 100)

    def test_wear_normalization_and_observation_counts_are_consistent(self):
        opening = self.opening(100)
        self.detail(opening, is_checked=True, wear_condition=' normal ')
        self.detail(opening, '2', is_checked=True, wear_condition='偏磨')
        self.detail(opening, '3', is_checked=True, wear_condition='')
        self.detail(opening, '4', wear_condition='NORMAL')
        distribution = self.query('wear_distribution')
        trend = self.query('wear_trend')['items'][0]
        self.assertEqual((distribution['total'], distribution['wear_recorded_count'], distribution['unrecorded_count']), (3, 2, 1))
        self.assertEqual((trend['checked_count'], trend['total'], trend['abnormal_rate']), (3, 2, 0.5))

    def test_summary_gap_is_not_artificially_inflated_by_manufacturer_filter(self):
        opening = self.opening(100, checked_tool_count=2, replaced_tool_count=2)
        self.detail(opening, is_replaced=True, manufacturer='A')
        self.detail(opening, '2', is_replaced=True, manufacturer='B')
        result = self.query('overview', manufacturer='A')
        self.assertEqual(result['kpi']['total_replacements'], 1)
        self.assertEqual(result['kpi']['summary_detail_replaced_count'], 2)
        self.assertEqual(result['kpi']['replacement_gap'], 0)
        self.assertEqual(result['recent_openings'][0]['replacement_gap'], 0)

    def test_registered_actions_keep_real_permission_checks(self):
        from dvadmin.system.models import ApiWhiteList, Menu, MenuButton, Role, RoleMenuButtonPermission, Users
        ApiWhiteList.objects.all().delete()
        role = Role.objects.create(name='分析只读测试', key='analysis-reader')
        user = Users.objects.create(username='analysis-reader', name='分析读取', is_superuser=False)
        user.role.add(role)
        menu = Menu.objects.create(name='分析测试', web_path='/shield/analysis')
        actions = ('filter_options', 'custom_fields', 'custom_chart', 'overview', 'cost_overview', 'cost_trend', 'brand_cost', 'brand_price_trend', 'brand_performance_trend', 'wear_distribution', 'wear_trend')
        for action in actions:
            path = f'/api/shield/analysis/{action}/'
            view = AnalysisViewSet.as_view({'get': action})
            request = APIRequestFactory().get(path)
            force_authenticate(request, user=user)
            self.assertEqual(view(request).data['code'], 4000)
            button = MenuButton.objects.create(menu=menu, name=action, value=f'Analysis{action}', api=path, method=0)
            RoleMenuButtonPermission.objects.create(role=role, menu_button=button)
            request = APIRequestFactory().get(path)
            force_authenticate(request, user=user)
            self.assertEqual(view(request).data['code'], 2000, action)

    def test_pending_or_draft_removal_does_not_poison_confirmed_segment(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        removed = self.detail(self.opening(200), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        pending = self.detail(self.opening(300), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=pending, confirmed_tool_instance=instance)
        draft = self.detail(self.opening(400, summary_status='DRAFT'), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=draft, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        item = self.query('brand_cost', start_ring=200, end_ring=200, manufacturer='A')['items'][0]
        self.assertEqual(item['avg_lifespan'], 100)

    def test_vendor_repair_only_month_is_present_in_overview(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        removed = self.detail(self.opening(200), is_replaced=True, manufacturer='B', price=200)
        self.install(removed)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED', repair_price=30)
        result = self.query('overview', start_ring=200, manufacturer='A')
        self.assertEqual(result['kpi']['total_cost'], 30)
        self.assertEqual(sum(row['cost'] for row in result['monthly_trend']), 30)

    def test_intervening_cross_machine_install_is_an_identity_conflict(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        other = ShieldMachineBasicInfo.objects.create(shield_model_id='INTERVENING', shield_model='B机')
        intervening = self.detail(self.opening(150, shield_model=other), is_replaced=True)
        NewToolRecord.objects.create(tool_change_detail=intervening, tool_instance=instance)
        removed = self.detail(self.opening(200), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        row = self.query('brand_cost', start_ring=200)['service_rows'][0]
        self.assertFalse(row['paired'])
        self.assertIn('跨项目或盾构机', row['reason'])

    def test_reinstall_without_confirmed_prior_removal_is_not_a_new_segment(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A')
        instance = self.install(installed)
        reinstall = self.detail(self.opening(200), is_replaced=True, manufacturer='A')
        NewToolRecord.objects.create(tool_change_detail=reinstall, tool_instance=instance)
        removed = self.detail(self.opening(250), is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        row = self.query('brand_cost', start_ring=250)['service_rows'][0]
        self.assertFalse(row['paired'])
        self.assertIn('重复安装', row['reason'])

    def test_huge_or_non_numeric_historical_ring_does_not_break_queries(self):
        self.detail(self.opening('999999999999999999'), is_replaced=True, price=100)
        self.detail(self.opening('100环'), is_replaced=True, price=100)
        self.detail(self.opening(100), is_replaced=True, price=50)
        result = self.query('overview')
        self.assertEqual(result['kpi']['total_cost'], 50)
        self.assertEqual(result['meta']['excluded_invalid_ring_opening_count'], 2)
        self.assertEqual(self.query('cost_trend')['items'][-1]['cumulative_cost'], 50)

    def test_late_install_date_is_not_a_confirmed_segment(self):
        first, last = self.opening(100), self.opening(200)
        WarehouseOpeningBasicInfo.objects.filter(pk=first.pk).update(open_time=timezone.now() + timedelta(days=1))
        first.refresh_from_db()
        instance = self.install(self.detail(first, is_replaced=True, manufacturer='A'))
        removed = self.detail(last, is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        row = self.query('brand_cost', start_ring=200)['service_rows'][0]
        self.assertFalse(row['paired'])

    def test_month_boundary_uses_same_local_month_for_count_and_amount(self):
        opening = self.opening(100)
        WarehouseOpeningBasicInfo.objects.filter(pk=opening.pk).update(open_time=datetime(2026, 8, 31, 16, 30, tzinfo=datetime_timezone.utc))
        self.install(self.detail(opening, is_replaced=True, price=100))
        result = self.query('overview')['monthly_trend']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['total_replacements'], 1)
        self.assertEqual(result[0]['cost'], 100)

    def test_installation_average_excludes_legacy_repair_prices(self):
        opening = self.opening(100)
        self.install(self.detail(opening, is_replaced=True, manufacturer='A', price=100))
        self.detail(opening, '2', is_replaced=True, manufacturer='A', replacement_type='REPAIR', price=900)
        item = self.query('brand_cost')['items'][0]
        self.assertEqual((item['avg_cost'], item['priced_count'], item['legacy_replacement_count']), (100, 1, 1))
        self.assertEqual(self.query('brand_price_trend')['series'][0]['data'], [100])

    def test_existing_department_scope_filters_amount_and_trace_rows(self):
        from dvadmin.system.models import Dept, Menu, MenuButton, Role, RoleMenuButtonPermission, Users
        dept = Dept.objects.create(name='可读部门', key='analysis-own')
        other = Dept.objects.create(name='其他部门', key='analysis-other')
        role = Role.objects.create(name='分析部门只读', key='analysis-dept-reader')
        user = Users.objects.create(username='analysis-dept-reader', dept=dept, is_superuser=False)
        user.role.add(role)
        menu = Menu.objects.create(name='部门分析', web_path='/shield/analysis')
        own, hidden = self.opening(100, dept_belong_id=dept.pk), self.opening(200, dept_belong_id=other.pk)
        self.detail(own, is_replaced=True, price=10, dept_belong_id=dept.pk)
        self.detail(hidden, is_replaced=True, price=900, dept_belong_id=other.pk)
        path = '/api/shield/analysis/cost_overview/'
        button = MenuButton.objects.create(menu=menu, name='cost', value='AnalysisDepartment', api=path, method=0)
        RoleMenuButtonPermission.objects.create(role=role, menu_button=button, data_range=2)
        request = APIRequestFactory().get(path)
        force_authenticate(request, user=user)
        data = AnalysisViewSet.as_view({'get': 'cost_overview'})(request).data
        self.assertEqual(data['code'], 2000, data)
        self.assertEqual(data['data']['cost_sources']['total'], 10)
        self.assertEqual({row['opening_id'] for row in data['data']['source_rows']}, {own.pk})
        # A later unscoped test request must not inherit this user's filter.
        self.assertEqual(self.query('cost_overview')['cost_sources']['total'], 910)

    def test_hidden_installation_relation_does_not_become_visible_supply_sample(self):
        from dvadmin.system.models import Dept, Menu, MenuButton, Role, RoleMenuButtonPermission, Users
        dept = Dept.objects.create(name='关系可读', key='analysis-relation-own')
        other = Dept.objects.create(name='关系隐藏', key='analysis-relation-other')
        role = Role.objects.create(name='关系只读', key='analysis-relation-reader')
        user = Users.objects.create(username='analysis-relation-reader', dept=dept, is_superuser=False)
        user.role.add(role)
        opening = self.opening(100, dept_belong_id=dept.pk)
        detail = self.detail(opening, is_replaced=True, price=100, manufacturer='A', dept_belong_id=dept.pk)
        self.install(detail)
        NewToolRecord.objects.filter(tool_change_detail=detail).update(dept_belong_id=other.pk)
        path = '/api/shield/analysis/brand_cost/'
        menu = Menu.objects.create(name='关系分析', web_path='/shield/analysis')
        button = MenuButton.objects.create(menu=menu, name='brand', value='AnalysisRelation', api=path, method=0)
        RoleMenuButtonPermission.objects.create(role=role, menu_button=button, data_range=2)
        request = APIRequestFactory().get(path)
        force_authenticate(request, user=user)
        result = AnalysisViewSet.as_view({'get': 'brand_cost'})(request).data
        self.assertEqual(result['code'], 2000, result)
        self.assertEqual(result['data']['items'][0]['installation_count'], 0)
        self.assertIsNone(result['data']['items'][0]['avg_cost'])

    def test_brand_query_cost_does_not_grow_per_supplier_and_pairs_once(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from unittest.mock import patch
        from . import analysis_views as views
        first, second = self.opening(100), self.opening(200)
        def add_supplier(position, manufacturer):
            installed = self.detail(first, position, is_replaced=True, manufacturer=manufacturer, price=100)
            instance = self.install(installed)
            removed = self.detail(second, position, is_replaced=True, manufacturer=manufacturer, price=120)
            self.install(removed)
            OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        add_supplier('1', 'A')
        with CaptureQueriesContext(connection) as one:
            self.query('brand_cost')
        add_supplier('2', 'B'); add_supplier('3', 'C')
        with patch.object(views, 'confirmed_service_segments', wraps=views.confirmed_service_segments) as paired:
            with CaptureQueriesContext(connection) as three:
                result = self.query('brand_cost')
        self.assertEqual(paired.call_count, 1)
        self.assertEqual(len(one), len(three))
        self.assertEqual(len(result['items']), 3)
        self.assertTrue(all(item['avg_lifespan'] == 100 for item in result['items']))

    def test_slim_brand_trends_preserve_exact_trends_metadata_and_default_details(self):
        installed = self.detail(self.opening(100), is_replaced=True, manufacturer='A', price=100)
        instance = self.install(installed)
        removed = self.detail(self.opening(200), is_replaced=True, manufacturer='B', price=200, wear_condition='偏磨')
        self.install(removed)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance,
                                    inspection_status='CONFIRMED', repair_price=30)
        for action in ('brand_price_trend', 'brand_performance_trend'):
            full = self.query(action)
            slim = self.query(action, include_details='false')
            full['meta'].pop('generated_at'); slim['meta'].pop('generated_at')
            for key in ('items', 'source_rows', 'service_rows'):
                self.assertIn(key, full); self.assertNotIn(key, slim)
                full.pop(key)
            self.assertEqual(full, slim)
            self.assertIn('source_rows', self.query(action, include_details='true'))
        self.assertIn('source_rows', self.query('brand_cost', include_details='false'))

    def test_suggested_pairing_sources_do_not_trigger_per_row_deferred_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        first, second = self.opening(100), self.opening(200)
        instance = self.install(self.detail(first, is_replaced=True, manufacturer='A'))
        def add_suggestion(position):
            removed = self.detail(second, position, is_replaced=True, manufacturer='B')
            OldToolRecord.objects.create(tool_change_detail=removed, suggested_tool_instance=instance)
        add_suggestion('1')
        with CaptureQueriesContext(connection) as one:
            self.query('brand_cost')
        add_suggestion('2'); add_suggestion('3')
        with CaptureQueriesContext(connection) as three:
            data = self.query('brand_cost')
        self.assertEqual(len(one), len(three))
        self.assertEqual(sum(row['pairing_source'] == 'suggested' for row in data['service_rows']), 3)

    def test_cost_sources_have_stable_numeric_ring_order_within_each_position(self):
        for ring in (100, 9, 10):
            opening = self.opening(ring)
            for position in ('2', '1'):
                detail = self.detail(opening, position, is_replaced=True, price=100)
                self.install(detail)
                OldToolRecord.objects.create(tool_change_detail=detail, inspection_status='CONFIRMED', repair_price=20)
        rows = self.query('cost_overview')['source_rows']
        self.assertEqual([(row['cutter_position_no'], row['ring_no']) for row in rows],
                         [(position, ring) for position in ('1', '2') for ring in ('9', '10', '100') for _ in range(2)])
        self.assertEqual(len({row['id'] for row in rows}), 12)
