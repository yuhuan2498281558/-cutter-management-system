"""现有工具修正的隔离数据库验收，不调用模型或开发库写入。"""

import json
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from application.ai_assistant import tools
from application.shield.cutter_position_scope import ACTIVE_CUTTER_POSITION_CODES, cutter_position_sort_key
from application.shield.models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo,
    ShieldTunnelingData, StratumBasicInfo, ToolChangeDetail, ToolCost,
    ToolInfo, ToolInstance, WarehouseOpeningBasicInfo,
)


class ToolsRefreshTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='REFRESH', project_name='刷新测试')
        cls.other_project = ProjectInfo.objects.create(project_id='OTHER', project_name='其他项目')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='REFRESH-A', shield_model='A')
        cls.other_machine = ShieldMachineBasicInfo.objects.create(shield_model_id='REFRESH-B', shield_model='B')
        cls.time = timezone.now().replace(microsecond=0)

    def call(self, function, **params):
        result = json.loads(function(json.dumps({'project_id': self.project.project_id, **params})))
        self.assertNotIn('error', result, result)
        return result

    def opening(self, ring, machine=None, project=None, **fields):
        sequence = WarehouseOpeningBasicInfo.objects.count()
        fields.setdefault('open_time', self.time + timedelta(minutes=ring, seconds=sequence))
        fields.setdefault('summary_status', 'CONFIRMED')
        row = WarehouseOpeningBasicInfo(
            warehouse_id=f'REFRESH-{sequence}', project=project or self.project,
            shield_model=machine or self.machine, ring_no=str(ring), **fields,
        )
        WarehouseOpeningBasicInfo.objects.bulk_create([row])
        return row

    def detail(self, opening, position='1', **fields):
        fields.setdefault('is_checked', True)
        fields.setdefault('tool_parent_type', 'SCRAPER' if position.strip().upper().startswith('S') else 'DISC')
        row = ToolChangeDetail(warehouse=opening, cutter_position_no=position, **fields)
        ToolChangeDetail.objects.bulk_create([row])
        return row

    def info(self, name='型号甲'):
        count = ToolInfo.objects.count()
        row = ToolInfo(tool_type_name=name, tool_parent_type='DISC',
                       tool_type_code=f'MODEL-{count}', tool_number=f'ARCHIVE-{count}')
        ToolInfo.objects.bulk_create([row])
        return row

    def install(self, opening, info, position='1'):
        number = f'INSTANCE-{NewToolRecord.objects.count()}'
        detail = self.detail(opening, position, tool_number=number, is_replaced=True)
        instance = ToolInstance.objects.create(tool_uid=number, display_tool_no=number,
                                               tool_info=info, tool_parent_type='DISC')
        NewToolRecord.objects.create(tool_change_detail=detail, tool_instance=instance)
        return detail, instance

    def remove(self, opening, instance, position='1', status='CONFIRMED', suggested=False):
        detail = self.detail(opening, position, is_replaced=True)
        fields = {'suggested_tool_instance' if suggested else 'confirmed_tool_instance': instance}
        OldToolRecord.objects.create(tool_change_detail=detail, inspection_status=status, **fields)
        return detail

    def stratum(self, ring, label='', areas=None, project=None):
        StratumBasicInfo.objects.bulk_create([StratumBasicInfo(
            project=project or self.project, ring_no=str(ring), stratum_type_codes=label,
            longitudinal_type_ratios=areas or {},
        )])

    def tunnel(self, ring=5, **fields):
        fields.setdefault('project', self.project)
        fields.setdefault('shield_machine', self.machine)
        fields.setdefault('record_time', self.time)
        row = ShieldTunnelingData(ring_no=str(ring), **fields)
        ShieldTunnelingData.objects.bulk_create([row])
        return row

    def test_opening_machine_status_and_manual_detail_difference(self):
        opening = self.opening(100, checked_tool_count=5, replaced_tool_count=3,
                               opening_duration=8, tool_change_duration=5.94)
        self.detail(opening, is_replaced=True)
        self.detail(opening, '2', is_replaced=False)
        self.detail(opening, 'G1R', is_replaced=True)
        self.opening(200, summary_status='DRAFT')
        self.opening(300, machine=self.other_machine)
        result = self.call(tools.query_opening_records, shield_machine_id=self.machine.pk,
                           summary_status='CONFIRMED')
        self.assertEqual(result['total_openings'], 1)
        self.assertEqual(result['summary_status_counts'], {'CONFIRMED': 1})
        row = result['recent_records'][0]
        self.assertEqual((row['tool_change_total'], row['tool_change_replaced']), (5, 3))
        self.assertEqual(row['count_difference'], {'checked': 3, 'replaced': 2})
        self.assertEqual(row['summary_missing_fields'], [])
        self.assertIsNone(row['summary_confirmed_at'])
        self.assertIsNone(row['summary_withdrawn_at'])
        self.assertEqual(row['tool_change_duration_hours'], 5.9)
        self.assertIn('人工汇总数和明细统计数不同：人工汇总按整仓填写，明细只统计 122 个有效刀位上已检查或已更换的记录。', row['warnings'])
        self.assertEqual(self.call(tools.query_opening_records, shield_machine_id=-1)['total_openings'], 0)
        self.assertEqual(self.call(tools.query_opening_records, summary_status='DRAFT')['total_openings'], 1)
        invalid = json.loads(tools.query_opening_records('{"summary_status":"PENDING"}'))
        self.assertIn('CONFIRMED', invalid['error'])

    def test_opening_full_means_efficiency_and_readings_are_not_display_limited(self):
        first = self.opening(10, rings_between_openings=10, opening_duration=2, tool_change_duration=1,
                             checked_tool_count=20, replaced_tool_count=5, right_revolution_reading=100, left_revolution_reading=20)
        self.opening(20, rings_between_openings=10, opening_duration=4, tool_change_duration=2,
                     checked_tool_count=40, replaced_tool_count=10, right_revolution_reading=300, left_revolution_reading=30)
        last = self.opening(50, rings_between_openings=30, opening_duration=9, tool_change_duration=3,
                            checked_tool_count=90, replaced_tool_count=15, right_revolution_reading=10, left_revolution_reading=40)
        self.opening(30, machine=self.other_machine, right_revolution_reading=999, left_revolution_reading=999)
        for position in ('1', '2', '3', '4'):
            self.detail(first, position, is_replaced=True)
            self.detail(last, position, is_replaced=True)
            self.detail(last, '0' + position, is_replaced=True)
        data = self.call(tools.query_opening_records, shield_machine_id=self.machine.pk, limit=1)
        self.assertEqual((data['avg_rings_between_openings'], data['recent_avg_rings_between_openings']), (16.7, 30))
        self.assertEqual((data['avg_opening_duration_hours'], data['recent_avg_opening_duration_hours']), (5, 9))
        self.assertEqual(data['efficiency_all'], {'opening_count': 3, 'check_denominator': 150,
                         'check_minutes_per_tool': 6, 'replace_denominator': 30, 'replace_minutes_per_tool': 12})
        self.assertIsNone(data['recent_records'][0]['revolutions_since_previous'])
        self.assertEqual(len(data['recent_records'][0]['top_replaced_positions']), 4)
        self.assertTrue(data['recent_records'][0]['top_positions_tied'])
        selected = self.call(tools.query_opening_records, shield_machine_id=self.machine.pk, ring_range=[20, 20])
        self.assertEqual(selected['recent_records'][0]['revolutions_since_previous'], 210)
        first_data = self.call(tools.query_opening_records, ring_range=[10, 10])['recent_records'][0]
        self.assertTrue(first_data['positions_all_once'])
        self.assertEqual(first_data['top_replaced_positions'], [])

    def test_tunneling_speed_and_complete_ring_revolution_counts(self):
        self.tunnel(5, advance_speed=30, counter_revolutions=90, integrated_revolutions=80)
        self.tunnel('05', advance_speed=60, counter_revolutions=None, integrated_revolutions=20)
        self.tunnel(6, advance_speed=None, counter_revolutions=100)
        self.tunnel(7, project=self.other_project, counter_revolutions=999)
        data = self.call(tools.query_tunneling_summary)
        self.assertEqual(data['metrics']['advance_speed'], {'avg': 45, 'min': 30, 'max': 60})
        self.assertEqual((data['counter_ring_count'], data['integrated_ring_count']), (1, 1))

    def test_opening_queries_stay_constant_with_full_efficiency_and_limited_details(self):
        query_counts = []
        previous = 0
        for total in (5, 15, 30):
            for index in range(previous + 1, total + 1):
                opening = self.opening(index, summary_status='CONFIRMED' if index % 2 else 'DRAFT',
                                       checked_tool_count=8, replaced_tool_count=4,
                                       opening_duration=2.25, tool_change_duration=0.37)
                self.detail(opening, '1', is_replaced=True, wear_condition='正常')
                self.detail(opening, '2', is_checked=False, is_replaced=True, wear_condition='偏磨')
                self.detail(opening, '3', is_replaced=False, wear_condition='正常')
                self.detail(opening, '4', is_checked=False, is_replaced=False)
                self.detail(opening, 'G1R', is_replaced=True)
            with CaptureQueriesContext(connection) as queries:
                data = self.call(tools.query_opening_records, limit=5)
            query_counts.append(len(queries))
            for name, indices in [('all', range(1, total + 1)), ('recent', range(total - 4, total + 1))]:
                confirmed = sum(index % 2 for index in indices)
                drafts = len(indices) - confirmed
                checked, replaced = 8 * confirmed + 2 * drafts, 4 * confirmed + 2 * drafts
                self.assertEqual(data[f'efficiency_{name}'], {
                    'opening_count': len(indices), 'check_denominator': checked, 'replace_denominator': replaced,
                    'check_minutes_per_tool': round(2.25 * len(indices) * 60 / checked, 1),
                    'replace_minutes_per_tool': round(0.37 * len(indices) * 60 / replaced, 1),
                })
            self.assertEqual([int(row['ring_no']) for row in data['recent_records']], list(range(total, total - 5, -1)))
            for row in data['recent_records']:
                self.assertEqual((row['detail_record_count'], row['detail_checked_count'], row['detail_replaced_count']), (4, 2, 2))
                self.assertEqual(row['wear_distribution'], {'正常': 2, '偏磨': 1})
                self.assertEqual(row['abnormal_rate'], '33.3%')
            previous = total
        self.assertEqual(query_counts, [query_counts[0]] * 3)

    def test_recommendation_price_sort_and_weighted_service_use_all_models(self):
        first, second = self.info('甲型号'), self.info('乙型号')
        for position, info, end in [('1', first, 20), ('2', second, 40), ('3', second, 40)]:
            _, instance = self.install(self.opening(10), info, position)
            self.remove(self.opening(end), instance, position)
        for info, price, vendor in [(first, 50, '甲厂'), (first, 80, '乙厂'), (second, 300, '甲厂')]:
            ToolCost.objects.create(tool_info=info, cost_type='NEW_TOOL', unit_price=price, manufacturer=vendor)
        default = self.call(tools.recommend_tools, min_samples=1)
        ordered = self.call(tools.recommend_tools, min_samples=1, sort_by='price_per_ring', top_n=1)
        self.assertEqual(default['recommendations'][0]['tool_type_name'], '乙型号')
        row = ordered['recommendations'][0]
        self.assertEqual(row['tool_type_name'], '甲型号')
        self.assertEqual([q['price_per_ring_yuan'] for q in row['manufacturer_prices']], [5, 8])
        self.assertEqual(ordered['service_summary'], {'completed_service_count': 3, 'total_service_rings': 70, 'avg_service_rings': 23.3})
        self.assertEqual(len(ordered['service_by_model']), 2)

    def test_missing_opening_fields_keep_zero_and_null_distinct(self):
        self.opening(10, summary_status='DRAFT', opening_duration=0, checked_tool_count=0,
                     summary_confirmed_at=self.time, summary_withdrawn_at=self.time)
        row = self.call(tools.query_opening_records)['recent_records'][0]
        self.assertEqual(row['summary_missing_fields'], ['换刀总时长', '更换刀具数量'])
        self.assertEqual(row['count_difference'], {'checked': 0, 'replaced': None})
        self.assertIsNone(row['tool_change_duration_hours'])
        self.assertEqual(row['summary_confirmed_at'], self.time.strftime('%Y-%m-%d %H:%M'))
        self.assertEqual(row['summary_withdrawn_at'], self.time.strftime('%Y-%m-%d %H:%M'))

    def test_recent_openings_use_primary_keys_and_machine_and_numeric_order(self):
        for ring in [9, 80, 100, 100]:
            self.detail(self.opening(ring, last_ring_no='1'), is_replaced=True)
        self.detail(self.opening(999, machine=self.other_machine), is_replaced=True)
        self.detail(self.opening(1000, project=self.other_project), is_replaced=True)
        result = self.call(tools.query_tool_change_data, last_n_openings=1, shield_machine_id=self.machine.pk)
        self.assertEqual(result['total_records'], 1)
        selected = WarehouseOpeningBasicInfo.objects.filter(project=self.project, shield_model=self.machine,
                                                             ring_no='100').latest('open_time')
        self.assertEqual(result['scope']['opening_ids'], [selected.pk])
        self.assertEqual(self.call(tools.query_tool_change_data, last_n_openings=2,
                                   shield_machine_id=self.machine.pk)['total_records'], 2)
        self.assertEqual(self.call(tools.query_tool_change_data, last_n_openings=2,
                                   shield_machine_id=-1)['total_records'], 0)

    def test_normalized_positions_all_observations_and_abnormal_sort(self):
        for index, (position, replaced, wear) in enumerate([
            ('001', True, '正常'), ('1', True, '偏磨'), ('1', False, '偏磨'),
            ('2', True, '正常'), ('2', False, '偏磨'), ('2', False, '偏磨'), ('2', False, '偏磨'),
            ('s14r', False, '待确认'),
        ]):
            self.detail(self.opening(index + 1), position, is_replaced=replaced, wear_condition=wear,
                        check_result='NORMAL' if replaced else 'ATTENTION')
        changed = self.call(tools.query_tool_change_data)
        self.assertEqual(changed['top_replaced_positions'][0], {'cutter_position_no': '1', 'replacement_count': 2})
        self.assertIn('现场观测记录', changed['scope_note'])
        result = self.call(tools.query_cutter_position_stats, cutter_position_no='0001')
        row = result['top_positions'][0]
        self.assertEqual((row['observation_count'], row['replacement_count']), (3, 2))
        self.assertEqual((row['abnormal_observation_count'], row['classified_observation_count']), (2, 3))
        self.assertEqual(row['abnormal_observation_rate'], 66.7)
        self.assertEqual(row['observation_wear_distribution']['偏磨'], 2)
        self.assertEqual(sum(item['count'] for item in row['wear_distribution']), 2)
        abnormal = self.call(tools.query_cutter_position_stats, sort_by='abnormal', top_n=1)
        self.assertEqual(abnormal['top_positions'][0]['cutter_position_no'], '2')
        self.assertEqual((abnormal['matched_position_count'], abnormal['returned_position_count']), (3, 1))
        self.assertTrue(abnormal['truncated'])
        unknown = self.call(tools.query_cutter_position_stats, cutter_position_no=' S14r ')['top_positions'][0]
        self.assertIsNone(unknown['abnormal_observation_rate'])
        self.assertEqual(unknown['replacement_count'], 0)

    def test_all_positions_ties_and_single_position_outside_default_top(self):
        opening = self.opening(100)
        for position in sorted(ACTIVE_CUTTER_POSITION_CODES, reverse=True):
            self.detail(opening, position, is_replaced=True, wear_condition='正常')
        expected = sorted(ACTIVE_CUTTER_POSITION_CODES, key=cutter_position_sort_key)
        default = self.call(tools.query_cutter_position_stats)
        self.assertEqual([row['cutter_position_no'] for row in default['top_positions']], expected[:10])
        self.assertTrue(default['truncated'])
        for params in [{'include_all': True, 'top_n': 1}, {'top_n': 200}, {'include_all': True, 'sort_by': 'abnormal'}]:
            result = self.call(tools.query_cutter_position_stats, **params)
            self.assertEqual(result['returned_position_count'], 122)
            self.assertFalse(result['truncated'])
            self.assertEqual([row['cutter_position_no'] for row in result['top_positions']], expected)
        single = self.call(tools.query_cutter_position_stats, cutter_position_no='s14r')
        self.assertEqual(single['top_positions'][0]['cutter_position_no'], 'S14R')
        for params in [{'cutter_position_no': 'Y2'}, {'sort_by': 'wear'}, {'include_all': 'true'}]:
            self.assertIn('error', json.loads(tools.query_cutter_position_stats(json.dumps(params))))

    def test_change_trend_insufficient_and_first_last_wording_and_wear(self):
        first = self.opening(10)
        self.detail(first, is_replaced=False, wear_condition='正常')
        self.detail(first, '2', is_replaced=False, wear_condition='待核定')
        one = self.call(tools.query_tool_change_trend)
        self.assertEqual(one['trend'], '数据不足')
        self.assertEqual(one['note'], '只有 1 个环段有数据，无法判断趋势。')
        self.assertIsNone(one['first_last_change_pct_points'])
        empty = self.call(tools.query_tool_change_trend, ring_range=[11, 20])
        self.assertEqual(empty['note'], '只有 0 个环段有数据，无法判断趋势。')
        self.detail(self.opening(110), is_replaced=True, wear_condition='偏磨')
        result = self.call(tools.query_tool_change_trend, interval=50)
        self.assertEqual(result['trend'], '末段高于首段')
        self.assertEqual(result['first_last_change_pct_points'], 100.0)
        self.assertEqual(result['note'], '末段更换率比首段高 100.0 个百分点。这只比较了首末两段，不是趋势检验。')
        self.assertEqual(result['summary']['total_records'], 3)
        self.assertEqual(result['summary']['nonempty_segment_count'], 2)
        self.assertEqual(result['segments'][0]['unknown_count'], 1)
        self.assertEqual(result['segments'][0]['normal_count'], 1)
        self.assertEqual(result['segments'][-1]['abnormal_rate'], '100.0%')
        self.assertIsNone(result['segments'][1]['abnormal_rate'])
        self.detail(self.opening(210), is_replaced=False, wear_condition='正常')
        self.assertEqual(self.call(tools.query_tool_change_trend, interval=50)['trend'], '首末持平')
        lower = self.call(tools.query_tool_change_trend, ring_range=[100, 220], interval=50)
        self.assertEqual(lower['trend'], '末段低于首段')

    def test_recommendation_new_quotes_budget_and_zero_quote(self):
        info = self.info()
        _, instance = self.install(self.opening(10), info)
        self.remove(self.opening(20), instance)
        for price, manufacturer in [(5400, '甲厂'), (3400, '乙厂')]:
            ToolCost.objects.create(tool_info=info, cost_type='NEW_TOOL', unit_price=price,
                                    brand=manufacturer, manufacturer=manufacturer, inventory=0)
        ToolCost.objects.create(tool_info=info, cost_type='REPAIR', unit_price=1230)
        result = self.call(tools.recommend_tools, min_samples=1)
        row = result['recommendations'][0]
        self.assertEqual(row['unit_price_yuan'], 3400)
        self.assertEqual(row['cost_per_ring_yuan'], 340)
        self.assertEqual(row['cost_per_ring_range_yuan'], [340, 540])
        self.assertEqual(row['price_basis'], 'NEW_TOOL')
        self.assertEqual((row['new_tool_price_min_yuan'], row['new_tool_price_max_yuan']), (3400, 5400))
        self.assertEqual(row['new_tool_quote_count'], 2)
        self.assertEqual([q['manufacturer'] for q in row['new_tool_quotes']], ['乙厂', '甲厂'])
        self.assertIsNone(row['manufacturer'])
        self.assertIsNone(row['inventory'])
        self.assertEqual(self.call(tools.recommend_tools, max_unit_price=1300, min_samples=1)['ranked_count'], 0)
        ToolCost.objects.create(tool_info=info, cost_type='NEW_TOOL', unit_price=0)
        row = self.call(tools.recommend_tools, max_unit_price=1300, min_samples=1)['recommendations'][0]
        self.assertEqual(row['cost_per_ring_yuan'], 0)

    def test_change_trend_tolerance_uses_unrounded_rates(self):
        for ring, total in [(10, 34), (110, 33)]:
            opening = self.opening(ring)
            for position in range(1, total + 1):
                self.detail(opening, str(position), is_replaced=position == 1)
        result = self.call(tools.query_tool_change_trend, interval=100)
        self.assertEqual([row['replacement_rate'] for row in result['segments']], ['2.9%', '3.0%'])
        self.assertEqual(result['trend'], '首末持平')
        self.assertEqual(result['first_last_change_pct_points'], 0.1)

    def test_recommendation_missing_new_quote_excluded_with_budget(self):
        info = self.info()
        self.install(self.opening(10), info)
        ToolCost.objects.create(tool_info=info, cost_type='REPAIR', unit_price=100)
        result = self.call(tools.recommend_tools, max_unit_price=1300)
        self.assertEqual(result['recommendations'], [])
        self.assertIn('1 种型号因没有新刀报价被排除', result['warnings'])
        no_budget = self.call(tools.recommend_tools)['insufficient_evidence'][0]
        self.assertIsNone(no_budget['new_tool_price_min_yuan'])
        self.assertIsNone(no_budget['cost_per_ring_range_yuan'])

    def test_recommendation_only_confirmed_segments_enter_average(self):
        info = self.info()
        start = self.opening(10)
        instances = [self.install(start, info, str(n))[1] for n in range(1, 6)]
        self.remove(self.opening(20), instances[0], status='CLOSED')
        self.remove(self.opening(30), instances[1], '2', status='PENDING_VENDOR_FEEDBACK')
        self.remove(self.opening(40), instances[2], '3', suggested=True)
        self.detail(self.opening(50), '4', is_replaced=True)
        row = self.call(tools.recommend_tools, min_samples=1)['recommendations'][0]
        self.assertEqual(row['installed_count'], 5)
        self.assertEqual(row['completed_service_count'], 1)
        self.assertEqual(row['unconfirmed_removed_count'], 3)
        self.assertEqual(row['in_service_count'], 1)
        self.assertEqual((row['avg_service_rings'], row['min_service_rings'], row['max_service_rings']), (10, 10, 10))
        self.assertIn('平均服役环数只用厂家已确认或已归档的拆下记录；还没确认的单独计数，没有算进平均值。',
                      self.call(tools.recommend_tools)['note'])

    def test_conflicting_confirmed_removals_do_not_enter_average(self):
        info = self.info()
        _, instance = self.install(self.opening(10), info)
        self.remove(self.opening(20), instance)
        self.remove(self.opening(30), instance)
        result = self.call(tools.recommend_tools, min_samples=1)
        self.assertEqual(result['recommendations'], [])
        self.assertEqual(result['insufficient_evidence'][0]['completed_service_count'], 0)

    def test_stratum_area_label_and_install_ring_excluded(self):
        info = self.info()
        _, instance = self.install(self.opening(10), info)
        self.remove(self.opening(20), instance)
        self.stratum(10, 'BOULDER', {'AREA_BOULDER': 20})
        self.stratum(11, 'SOFT_SOIL', {'AREA_BOULDER': 2})
        label = self.call(tools.recommend_tools, stratum_types=['BOULDER'], min_samples=1)
        self.assertEqual(label['recommendations'], [])
        area = self.call(tools.recommend_tools, stratum_types=['AREA_BOULDER'],
                         stratum_basis='longitudinal_area', min_samples=1)
        self.assertEqual(area['recommendations'][0]['completed_service_count'], 1)
        self.assertEqual(area['criteria']['stratum_basis'], 'longitudinal_area')
        self.assertEqual(area['recommendations'][0]['avg_service_rings'], 10)
        self.stratum(20, 'BOULDER')
        self.assertEqual(self.call(tools.recommend_tools, stratum_types=['BOULDER'],
                                   min_samples=1)['recommendations'][0]['installed_count'], 1)
        for params in [{'stratum_types': ['AREA_BOULDER']},
                       {'stratum_basis': 'longitudinal_area', 'stratum_types': ['BOULDER']}]:
            error = json.loads(tools.recommend_tools(json.dumps(params)))['error']
            self.assertIn('不认识的地层编码：', error)
            self.assertIn('历史地层标签可用：', error)
            self.assertIn('纵断面面积分类可用：', error)
        self.assertIn('error', json.loads(tools.recommend_tools('{"stratum_basis":"bad"}')))

    def test_in_service_stratum_end_uses_same_machine_latest_opening(self):
        info = self.info()
        self.install(self.opening(10), info)
        self.opening(20)
        self.opening(100, machine=self.other_machine)
        self.stratum(50, areas={'AREA_BOULDER': 5})
        params = {'stratum_types': ['AREA_BOULDER'], 'stratum_basis': 'longitudinal_area'}
        self.assertEqual(self.call(tools.recommend_tools, **params)['recommendations'], [])
        self.stratum(20, areas={'AREA_BOULDER': 2})
        row = self.call(tools.recommend_tools, **params)['insufficient_evidence'][0]
        self.assertEqual(row['installed_count'], 1)
        self.assertEqual(row['in_service_count'], 1)

    def test_position_stratum_separates_replacement_and_label_counts(self):
        self.detail(self.opening(10), '17', is_replaced=True)
        self.detail(self.opening(20), '17', is_replaced=True)
        self.stratum(10, 'BOULDER,SOFT_SOIL')
        self.stratum(20, 'BOULDER')
        result = self.call(tools.query_position_stratum_impact)
        row = result['top_positions'][0]
        self.assertEqual((row['replacement_count'], row['total']), (2, 3))
        self.assertIn('一次更换可能对应多个标签', result['note'])

    def test_tunneling_limit_and_single_segment_identity(self):
        for index in range(12):
            self.tunnel(raw_parameters={'segment_index': index + 1, 'segment_count': 12},
                        point_count=74, record_time=self.time + timedelta(minutes=index))
        self.assertEqual(len(self.call(tools.query_tunneling_summary, limit=3)['recent_records']), 3)
        self.assertEqual(len(self.call(tools.query_tunneling_summary)['recent_records']), 10)
        self.assertEqual(len(self.call(tools.query_tunneling_summary, limit=200)['recent_records']), 12)
        single = self.call(tools.query_tunneling_trend, start_time=(self.time + timedelta(minutes=11)).isoformat())
        self.assertEqual(single['trend'], '数据不足')
        self.assertEqual(single['segments'][0]['segment_index'], 12)
        self.assertEqual(single['segments'][0]['count'], 74)
        self.assertEqual(single['summary']['segment_mode'], 'single_ring_time_segments')
        self.assertNotIn('整体趋势为 稳定', ' '.join(single['facts']))

    def test_tunneling_threshold_and_hit_records_are_consistent(self):
        for index, (torque, penetration) in enumerate([(10, 5), (10, 5), (14, 10)], start=1):
            row = self.tunnel(torque=torque, penetration=penetration, thrust=100,
                              raw_parameters={'segment_index': index, 'start_time': 'start', 'end_time': 'end'})
        result = self.call(tools.query_tunneling_anomaly, threshold_k=1.1)
        self.assertEqual(result['threshold_k'], 1.1)
        self.assertEqual({item['field'] for item in result['anomaly_fields']}, {'torque', 'penetration'})
        self.assertEqual(len(result['anomaly_records']), 2)
        hit = result['anomaly_records'][0]
        self.assertEqual((hit['record_id'], hit['ring_no'], hit['segment_index']), (row.pk, '5', 3))
        self.assertEqual((hit['start_time'], hit['end_time']), ('start', 'end'))
        self.assertEqual((hit['value'], hit['average'], hit['ratio']), (14, 11.333, 1.235))
        self.assertNotIn('未发现', ' '.join(result['highlights']))
        self.assertIn('贯入度平均值为 6.667mm/r', ' '.join(result['facts']))
        normal = self.call(tools.query_tunneling_anomaly, threshold_k=1.5)
        self.assertEqual(normal['anomaly_fields'], [])
        self.assertEqual(normal['anomaly_records'], [])
        self.assertIn('未发现', ' '.join(normal['highlights']))

    def test_correlation_needs_common_rings_and_reports_coverage(self):
        self.tunnel(torque=10)
        self.detail(self.opening(15), is_replaced=True)
        self.stratum(5, 'BOULDER')
        result = self.call(tools.query_tunneling_wear_correlation, ring_range=[1, 100], interval=50)
        self.assertEqual(result['comparable_segment_count'], 0)
        self.assertEqual(result['coverage']['tunneling']['ring_min'], 5)
        self.assertEqual(result['coverage']['tool_change']['ring_min'], 15)
        self.assertEqual(result['coverage']['stratum']['ring_count'], 1)
        self.assertIsNotNone(result['coverage']['tunneling']['time_min'])
        self.assertIsNotNone(result['coverage']['tool_change']['open_time_max'])
        self.assertEqual(result['segments_missing_tunneling'], ['51-100'])
        self.assertEqual(result['segments_missing_observation'], ['51-100'])
        self.assertIn('掘进数据和换刀数据没有足够的共同环段，下面只分别列出两类数据，不做对照。', result['warnings'])
        self.assertNotIn('最高', ' '.join(result['facts'] + result['highlights']))
        self.assertIn('历史地层标签出现次数最多', result['note'])
        self.assertIn('这里只是把掘进、换刀和地层数据按环段并列，不代表它们之间有关联或因果。', result['note'])
        self.detail(self.opening(5), is_replaced=True)
        one = self.call(tools.query_tunneling_wear_correlation, ring_range=[1, 100])
        self.assertEqual(one['comparable_segment_count'], 1)
        self.assertNotIn('最高', ' '.join(one['facts'] + one['highlights']))
        self.tunnel(55, torque=20)
        self.detail(self.opening(55), is_replaced=True)
        two = self.call(tools.query_tunneling_wear_correlation, ring_range=[1, 100])
        self.assertEqual(two['comparable_segment_count'], 2)
        self.assertNotIn('没有足够的共同环段', ' '.join(two['warnings']))

    def test_invalid_ring_ranges_return_error_in_refreshed_tools(self):
        for function in [tools.query_opening_records, tools.query_tool_change_data, tools.query_cutter_position_stats,
                         tools.query_tool_change_trend, tools.recommend_tools, tools.query_position_stratum_impact,
                         tools.query_tunneling_summary, tools.query_tunneling_trend,
                         tools.query_tunneling_anomaly, tools.query_tunneling_wear_correlation]:
            with self.subTest(function=function.__name__):
                error = json.loads(function('{"ring_range":[20,10]}'))['error']
                self.assertIn('起始环号不能大于结束环号', error)
