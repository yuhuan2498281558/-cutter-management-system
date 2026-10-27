"""规则与展示契约；领域工具使用桩数据，不初始化模型或写聊天记录。"""
import json
from contextlib import ExitStack
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from application.ai_assistant import llm_service
from application.ai_assistant.answer_reporting import render_report
from application.ai_assistant.llm_service import ToolAssistant, _data_coverage
from application.ai_assistant.memory_service import MemoryService, MemorySnapshot
from application.ai_assistant.views import _build_project_snapshot
from application.shield.models import (
    ProjectInfo, ShieldMachineBasicInfo, ShieldTunnelingData, StratumBasicInfo,
    WarehouseOpeningBasicInfo,
)


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _opening(ring=487, **fields):
    return {'ring_no': str(ring), 'last_ring_no': None, 'opening_duration': 10,
            'tool_change_duration_hours': 4, 'tool_change_total': 20,
            'tool_change_replaced': 2, 'abnormal_rate': '20%',
            'rings_between_openings': 30, 'wear_distribution': {'偏磨': 2},
            'top_replaced_positions': ['S1L'], **fields}


class RoutingRefreshTests(SimpleTestCase):
    def setUp(self):
        self.assistant = ToolAssistant.__new__(ToolAssistant)
        self.assistant.memory = MemoryService(backend='django')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.direct_chat = self.stack.enter_context(patch.object(self.assistant, '_direct_chat', side_effect=AssertionError('禁止调用模型')))
        self.stack.enter_context(patch.object(self.assistant, '_ensure_llm_runtime', side_effect=AssertionError('禁止初始化模型')))
        self.coverage = self.stack.enter_context(patch('application.ai_assistant.llm_service._data_coverage', return_value={
            'record_count': 10, 'ring_min': 5, 'ring_max': 5,
            'time_min': '2026-03-01', 'time_max': '2026-03-02',
        }))
        self.coverage.side_effect = lambda project, domain, rings=None: ({'record_count': 0} if rings else self.coverage.return_value)
        self.tools = {}
        self.named_manufacturers = self.stack.enter_context(patch.object(self.assistant, '_named_manufacturers', return_value=[]))
        fixtures = {
            'query_opening_records': {'total_openings': 1, 'recent_records': [_opening()]},
            'query_tool_change_data': {'total_records': 20, 'replaced_count': 4, 'replacement_rate': '20%',
                                       'wear_distribution': [], 'top_replaced_positions': [{'cutter_position_no': 'S1L', 'replacement_count': 4}]},
            'query_cutter_position_stats': {'total_records': 20, 'top_positions': []},
            'query_tool_change_trend': {'interval': 50, 'segments': [
                {'ring_range': '100-149', 'total': 20, 'replaced': 8, 'replacement_rate': '40%', 'abnormal_rate': '10%'},
                {'ring_range': '150-170', 'total': 10, 'replaced': 3, 'replacement_rate': '30%', 'abnormal_rate': '20%'},
            ]},
            'query_tunneling_summary': {'total_records': 1, 'metrics': {}},
            'query_tunneling_trend': {'total_records': 1, 'segments': []},
            'query_tunneling_anomaly': {'total_records': 1, 'anomaly_fields': []},
            'query_tunneling_wear_correlation': {'total_records': 1, 'segments': []},
            'query_stratum_data': {'total_rings': 10, 'stratum_distribution': {'孤石': 2}},
            'analyze_stratum_wear_correlation': {'stratum_analysis': []},
            'query_position_stratum_impact': {'top_positions': []},
            'compare_manufacturer_service': {'service_by_install_manufacturer': []},
            'recommend_tools': {'recommendations': []},
            'trace_tool_lifecycle': {'results': []},
            'query_stratum_area': {'classes': []},
        }
        for name, fixture in fixtures.items():
            self.tools[name] = self.stack.enter_context(patch(f'application.ai_assistant.llm_service.{name}', return_value=_json(fixture)))

    def ask(self, query, prepared=False):
        context = {'project_id': 'REFRESH'}
        if prepared:
            context = self.assistant._prepare_query_context(query, MemorySnapshot(scope_key='user:test'), context)
        return self.assistant._direct_route(query, context)

    def params(self, tool):
        return json.loads(self.tools[tool].call_args.args[0])

    def test_first_match_for_corrected_question_families(self):
        cases = [
            ('对比前后阶段换刀频率和异常磨损变化', 'change_trend'),
            ('分析最近开仓记录中异常磨损率较高的开仓', 'opening'),
            ('查询最近5次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率', 'opening'),
            ('结合开仓时长和检查刀具数量，统计平均检查一把刀需要多长时间', 'opening_efficiency'),
            ('结合开仓时长和更换刀具数量，统计平均更换一把刀需要多长时间', 'opening_efficiency'),
            ('平均每把刀需要多长时间', 'opening_efficiency'),
            ('统计换刀更换率，并列出主要更换刀位', 'tool_change_summary'),
            ('找出换刀频率最高的环段并列出主要刀位', 'change_trend'),
            ('按50环为一段统计换刀情况，列出每段现场观测记录数、更换数、更换率和已分类异常率', 'change_trend'),
            ('分析最近100环换刀变化，比较首末环段的更换率', 'change_trend'),
            ('按50环为一段，找出更换次数最多的环段并列出该段的主要刀位', 'change_trend'),
            ('统计100环到300环的换刀分段情况', 'change_trend'),
            ('100到300环的开仓时长按检查数折算平均是多少小时每把', 'opening_efficiency'),
            ('结合地层看每次开仓的刀位异常', 'opening_stratum_change'),
            ('每次开仓经过的地层和刀位异常有没有联动', 'opening_stratum_change'),
            ('找出异常磨损集中的刀位，并列出异常类型', 'cutter_position'),
            ('分析刀盘不同刀位的磨损分布情况', 'cutter_position'),
            ('分析不同地层下的换刀数量和更换率', 'stratum_wear'),
            ('统计各地层下换刀频率', 'stratum_wear'),
            ('分析软土地基下的换刀数量和更换率', 'stratum_wear'),
            ('查询 S1L 刀位服役轨迹', 'position_point_query'),
            ('分析最近100环不同厂家的磨损表现', 'manufacturer_service'),
            ('分析最近100环地层与磨损的关系', 'stratum_wear'),
            ('分析最近100环掘进参数与磨损的关联', 'tunneling_wear_correlation'),
        ]
        for query, branch in cases:
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertEqual(result['rule_branch'], branch)
        self.assertEqual(self.params('query_tool_change_data')['cutter_position_no'], 'S1L')

    def test_rate_count_and_recent_manufacturer_are_not_broad_intents(self):
        self.assertFalse(self.assistant._is_recent_abnormal_wear_cause_query('最近开仓异常磨损率较高'))
        self.assertFalse(self.assistant._is_opening_efficiency_query('开仓检查数和更换数'))
        result = self.ask('统计最近100环各厂家的磨损情况')
        self.assertEqual(result['rule_branch'], 'manufacturer_service')
        self.tools['query_tool_change_data'].assert_not_called()
        self.assertEqual(self.params('compare_manufacturer_service')['ring_range'], [388, 487])

    def test_cause_question_and_comprehensive_request(self):
        self.assertEqual(self.ask('结合掘进参数和换刀记录，分析异常磨损可能原因')['rule_branch'], 'recent_abnormal_wear_cause')
        for tool in self.tools.values():
            tool.reset_mock()
        self.assertIsNone(self.ask('综合换刀、开仓、地层、刀位、厂家和寿命数据，生成近期风险清单和处理建议'))
        self.assertIsNone(self.ask('结合换刀、开仓和地层数据进行综合分析'))
        for tool in self.tools.values():
            tool.assert_not_called()
        self.direct_chat.assert_not_called()

    def test_area_requests_use_area_tool(self):
        for query in ('第2199环孤石占多少', '统计当前项目地层分布，列出各地层类型占比', '第一百环地层面积', '软土地基比例', '第100环细砂占多少', '查询下一阶段地层面积'):
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertEqual(result['rule_branch'], 'stratum_area')
                self.assertIn('地层面积组成', result['answer'])
                self.assertEqual(self.params('query_stratum_area')['basis'], 'longitudinal_area')
        self.direct_chat.assert_not_called()
        self.tools['query_stratum_data'].assert_not_called()

    def test_overall_rate_precedes_positions_and_peak_uses_same_segment(self):
        result = self.ask('统计换刀更换率，并列出主要更换刀位')
        self.assertLess(result['answer'].index('现场观测记录'), result['answer'].index('高频更换刀位'))
        self.assertIn('20%', result['answer'])
        result = self.ask('找出换刀频率最高的环段并列出主要刀位')
        self.assertEqual(self.params('query_cutter_position_stats')['ring_range'], [100, 149])
        self.assertIn('环段长度 50 环', result['answer'])
        self.assertIn('已分类异常率', result['answer'])

    def test_abnormal_ranking_and_whole_head_parameters(self):
        self.ask('找出异常磨损集中的刀位，并列出异常类型')
        self.assertEqual(self.params('query_cutter_position_stats')['sort_by'], 'abnormal')
        self.ask('分析刀盘不同刀位的磨损分布情况')
        self.assertTrue(self.params('query_cutter_position_stats')['include_all'])

    def test_group_service_keeps_type_after_context_preparation(self):
        for name, kind in [('滚刀', 'DISC'), ('刮刀', 'SCRAPER')]:
            with self.subTest(kind=kind):
                result = self.ask(f'统计{name}平均寿命和集中更换环段', prepared=True)
                self.assertEqual(result['rule_branch'], 'group_service')
                self.assertEqual(self.params('recommend_tools')['tool_type'], kind)
                self.assertEqual(self.params('recommend_tools')['top_n'], 50)
                self.assertEqual(self.params('query_tool_change_trend')['tool_type'], kind)
                self.assertIn('各型号已拆下刀具的服役环数', result['answer'])
                self.assertIn('这是已经拆下的刀从安装到拆下经过的环数，按型号统计；不是在役刀具的剩余寿命预测。', result['answer'])

    def test_abnormal_ranking_uses_observations_and_lists_types(self):
        self.tools['query_cutter_position_stats'].return_value = _json({'total_records': 20, 'sort_by': 'abnormal', 'top_positions': [
            {'cutter_position_no': '1', 'replacement_count': 9, 'observation_count': 10, 'abnormal_observation_count': 1,
             'classified_observation_count': 10, 'abnormal_observation_rate': 10, 'observation_wear_distribution': {'偏磨': 1, '正常': 9}},
            {'cutter_position_no': '2', 'replacement_count': 2, 'observation_count': 10, 'abnormal_observation_count': 8,
             'classified_observation_count': 10, 'abnormal_observation_rate': 80, 'observation_wear_distribution': {'断裂': 8, '正常': 2}},
        ]})
        answer = self.ask('列出异常磨损集中的刀位')['answer']
        self.assertLess(answer.index('| 2 |'), answer.index('| 1 |'))
        self.assertIn('断裂 8次', answer)
        self.assertNotIn('正常 9次', answer)

    def test_recommendation_keeps_service_constraints_and_area_codes(self):
        result = self.ask('在软土地基下推荐前3种滚刀，单价不超过10000元，最少完成服役样本10把', prepared=True)
        self.assertEqual(result['rule_branch'], 'tool_recommendation')
        params = self.params('recommend_tools')
        for key, expected in {'tool_type': 'DISC', 'top_n': 3, 'min_samples': 10, 'max_unit_price': 10000,
                              'stratum_types': ['SOFT_SOIL'], 'stratum_basis': 'label'}.items():
            self.assertEqual(params[key], expected)
        self.ask('按孤石面积推荐前五种刮刀，单价上限2万元')
        params = self.params('recommend_tools')
        self.assertEqual(params['stratum_basis'], 'longitudinal_area')
        self.assertEqual(params['stratum_types'], ['AREA_BOULDER'])
        self.assertEqual(params['max_unit_price'], 20000)
        self.assertEqual(params['top_n'], 5)

    def test_full_instance_remains_lifecycle_and_position_is_not_partial_id(self):
        self.ask('查询487-S14R-01的服役寿命')
        self.assertEqual(self.params('trace_tool_lifecycle')['tool_ids'], ['487-S14R-01'])
        self.tools['trace_tool_lifecycle'].reset_mock()
        self.assertEqual(self.ask('查询 S1L 刀位服役轨迹')['rule_branch'], 'position_point_query')
        self.tools['trace_tool_lifecycle'].assert_not_called()

    def test_chinese_rings_and_recent_anchor(self):
        result = self.ask('最近两百五十环换刀情况', prepared=True)
        self.assertEqual(self.params('query_tool_change_data')['ring_range'], [238, 487])
        self.assertTrue(result['answer'].startswith('统计范围：以最新一次开仓（第 487 环）为终点往前 250 环，即第 238–487 环。'))
        self.assertEqual(self.assistant._extract_ring_range('第一百环地层分布'), [100, 100])
        self.assertEqual(self.assistant._extract_ring_range('第一百环到一千二百环换刀情况'), [100, 1200])

    def test_parallel_types_and_discrete_rings_all_reach_tools(self):
        result = self.ask('统计滚刀和刮刀的换刀数量', prepared=True)
        self.assertEqual(result['rule_branch'], 'multiple_scopes')
        self.assertEqual([json.loads(c.args[0])['tool_type'] for c in self.tools['query_tool_change_data'].call_args_list], ['DISC', 'SCRAPER'])
        self.assertIn('滚刀', result['answer'])
        self.assertIn('刮刀', result['answer'])
        self.tools['query_tool_change_data'].reset_mock()
        result = self.ask('第10环和第100环换刀情况', prepared=True)
        self.assertEqual([json.loads(c.args[0])['ring_range'] for c in self.tools['query_tool_change_data'].call_args_list], [[10, 10], [100, 100]])
        self.assertIn('第 10 环', result['answer'])
        self.assertIn('第 100 环', result['answer'])

    def test_tunneling_interval_limit_and_named_manufacturer_filter(self):
        self.ask('第100环到第300环每100环统计掘进趋势')
        self.assertEqual(self.params('query_tunneling_trend')['interval'], 100)
        self.ask('查询最近15条掘进记录')
        self.assertEqual(self.params('query_tunneling_summary')['limit'], 15)
        self.named_manufacturers.return_value = ['厂家A', '厂家B']
        result = self.ask('比较厂家A和厂家B的刀具表现')
        self.assertEqual(self.params('compare_manufacturer_service')['manufacturers'], ['厂家A', '厂家B'])
        self.assertNotIn('现在还不能只看指定厂家', result['answer'])
        self.assertIn('厂家A、厂家B', result['answer'])

    def test_discrete_empty_rings_do_not_become_zero_wear_claims(self):
        self.tools['query_tool_change_data'].return_value = _json({'total_records': 0, 'message': '未找到换刀记录'})
        answer = self.ask('第10环和第100环换刀情况')['answer']
        self.assertEqual(answer.count('未找到换刀记录'), 2)
        self.assertNotIn('None', answer)
        self.assertNotIn('判断原因', answer)

    def test_recent_empty_tunneling_uses_actual_coverage(self):
        self.tools['query_tunneling_summary'].return_value = _json({'total_records': 0})
        result = self.ask('最近100环掘进参数')
        self.assertEqual(self.params('query_tunneling_summary')['ring_range'], [388, 487])
        self.assertIn('这个范围里没有掘进数据。库里的掘进数据只覆盖第 5–5 环（2026-03-01 至 2026-03-02）。想看这些记录，可以问"最近有记录的 100 环掘进"。', result['answer'])

    def test_recent_recorded_tunneling_uses_own_latest_ring(self):
        result = self.ask('最近有记录的100环掘进参数', prepared=True)
        self.assertEqual(self.params('query_tunneling_summary')['ring_range'], [1, 5])
        self.assertTrue(result['answer'].startswith('统计范围：以掘进数据最新的一条记录（第 5 环）为终点往前 100 环，即第 1–5 环。'))
        self.tools['query_opening_records'].assert_not_called()

    def test_opening_status_is_explicit_and_recent_openings_keeps_limit(self):
        self.ask('查询最近15次已确认开仓记录')
        self.assertEqual(self.params('query_opening_records')['limit'], 15)
        self.assertEqual(self.params('query_opening_records')['summary_status'], 'CONFIRMED')
        self.ask('查询草稿开仓记录')
        self.assertEqual(self.params('query_opening_records')['summary_status'], 'DRAFT')

    def test_opening_optional_confirmation_fields_are_visible(self):
        answer = self.assistant._format_opening_answer(_json({'total_openings': 1,
            'summary_status_counts': {'CONFIRMED': 1, 'DRAFT': 0}, 'recent_records': [_opening(
                summary_confirmed_at='2026-01-01', summary_withdrawn_at=None,
                summary_missing_fields=['tool_change_duration'], count_difference={'checked': 2, 'replaced': -1})]}))
        for text in ('已确认 1 次，草稿 0 次', '汇总确认时间 2026-01-01', '汇总缺少换刀时长', '检查 2 把，更换 -1 把'):
            self.assertIn(text, answer)
        answer = self.assistant._format_opening_answer(_json({'total_openings': 15,
            'summary_status_counts': {'CONFIRMED': 15}, 'recent_records': [_opening()]}))
        self.assertIn('已确认 15 次，草稿 0 次', answer)

    def test_thirty_positions_and_all_positions_are_not_truncated(self):
        positions = [{'cutter_position_no': str(i), 'replacement_count': i, 'tool_parent_type': 'DISC',
                      'observation_count': i + 2, 'observation_wear_distribution': {'偏磨': 1},
                      'abnormal_observation_count': 1, 'classified_observation_count': 2,
                      'abnormal_observation_rate': 50} for i in range(1, 31)]
        self.tools['query_cutter_position_stats'].return_value = _json({'total_records': 1000, 'top_positions': positions, 'matched_position_count': 30})
        result = self.ask('列出更换次数最高的前30个刀位')
        self.assertEqual(self.params('query_cutter_position_stats')['top_n'], 30)
        self.assertEqual(sum(line.startswith('| ') for line in result['answer'].splitlines()), 32)
        result = self.ask('查询全刀盘磨损分布')
        self.assertIn('共 30 个刀位', result['answer'])
        self.assertIn('| 30 |', result['answer'])

    def test_fifteen_openings_and_efficiencies_show_fifteen_rows(self):
        records = [_opening(i) for i in range(1, 16)]
        self.tools['query_opening_records'].return_value = _json({'total_openings': 15, 'recent_records': records})
        result = self.ask('查询最近15次开仓记录')
        self.assertIn('最近 **15** 次', result['answer'])
        tables = result['answer'].split('### 现场明细')
        self.assertEqual(sum(line.startswith('| ') for line in tables[0].splitlines()), 17)
        self.assertEqual(sum(line.startswith('| ') for line in tables[1].splitlines()), 17)
        result = self.ask('查询最近15次开仓效率')
        self.assertIn('最近 15 次', result['answer'])
        self.assertEqual(sum(line.startswith('| ') for line in result['answer'].splitlines()), 17)

    def test_efficiency_weights_counts_and_uses_change_duration(self):
        records = [_opening(10, opening_duration=10, tool_change_duration_hours=2, tool_change_total=2, tool_change_replaced=1),
                   _opening(20, opening_duration=30, tool_change_duration_hours=6, tool_change_total=18, tool_change_replaced=3),
                   _opening(30, opening_duration=0, tool_change_duration_hours=0, tool_change_total=20, tool_change_replaced=4),
                   _opening(40, opening_duration=0, tool_change_duration_hours=None, tool_change_total=0, tool_change_replaced=40)]
        answer = self.assistant._format_opening_efficiency_answer(_json({'recent_records': records}))
        self.assertIn('平均检查一把刀约 60.0 分钟；平均更换一把刀约 60.0 分钟', answer)
        self.assertIn('1 次开仓缺少换刀总时长', answer)
        self.assertIn('| 30 | 0.0 | 0.0 | 20 | 4 | 0.0 | 0.0 |', answer)
        self.assertIn('平均值 = 总时长 ÷ 总把数，是按开仓（换刀）总时长折算的，不是每把刀的实际作业工时。', answer)

    def test_abnormal_types_use_classified_denominator(self):
        answer = self.assistant._format_tool_change_answer(_json({'total_records': 20, 'replaced_count': 3, 'replacement_rate': '15%',
            'wear_distribution': [{'wear_condition': '正常', 'count': 10}, {'wear_condition': '偏磨', 'count': 3},
                                  {'wear_condition': '断裂', 'count': 2}, {'wear_condition': '待核实', 'count': 5}]}))
        self.assertIn('异常合计 5 条', answer)
        self.assertIn('已分类的观测记录数（15 条）', answer)
        self.assertIn('| 偏磨 | 3 | 20% |', answer)
        self.assertIn('| 断裂 | 2 | 13.3% |', answer)
        self.assertIn('正常 10 条；未分类 5 条', answer)

    def test_first_opening_stratum_starts_at_one_and_unknown_is_not_ranked(self):
        answer = self.assistant._format_opening_stratum_change_answer(_json({'total_openings': 2, 'recent_records': [
            _opening(15, abnormal_rate='10%'), _opening(30, last_ring_no='15', abnormal_rate=None),
        ]}), {'project_id': 'REFRESH'})
        self.assertEqual([json.loads(c.args[0])['ring_range'] for c in self.tools['query_stratum_data'].call_args_list], [[1, 15], [16, 30]])
        self.assertIn('异常率最高的几次开仓', answer)
        self.assertNotIn('高异常', answer)
        self.assertIn('异常率 暂无', answer)
        self.assertIn('异常磨损率最高的是环号 15', answer)

    def test_opening_abnormal_sort_places_unknown_last(self):
        self.tools['query_opening_records'].return_value = _json({'total_openings': 3, 'recent_records': [
            _opening(300, abnormal_rate=None), _opening(200, abnormal_rate='5%'), _opening(100, abnormal_rate='20%'),
        ]})
        answer = self.ask('查询最近开仓记录中异常率较高的开仓')['answer']
        self.assertLess(answer.index('| 100 |'), answer.index('| 200 |'))
        self.assertLess(answer.index('| 200 |'), answer.index('| 300 |'))
        self.assertIn('异常率为暂无', answer)

    def test_insufficient_trend_never_compares_even_with_two_stub_rows(self):
        data = {'trend': '数据不足', 'segments': [
            {'ring_range': '1-50', 'total': 2, 'replaced': 1, 'replacement_rate': '50%', 'abnormal_rate': 50},
            {'ring_range': '51-60', 'total': 2, 'replaced': 2, 'replacement_rate': '100%', 'abnormal_rate': None},
        ]}
        answer = self.assistant._format_trend_answer(_json(data))
        self.assertNotIn('首个有效段（', answer)
        self.assertIn('已分类异常率', answer)
        data.update(trend='末段高于首段', first_last_change_pct_points=50, note='首末更换率相差 50 个百分点。')
        self.assertIn(data['note'], self.assistant._format_trend_answer(_json(data)))

    def test_new_fields_and_old_payloads_render_without_invented_prices(self):
        for extra, price in [({}, '暂无新刀报价'), ({'new_tool_price_min_yuan': 100, 'new_tool_price_max_yuan': 200}, '100–200'),
                             ({'new_tool_price_min_yuan': 0, 'new_tool_price_max_yuan': 0}, '0')]:
            answer = self.assistant._format_recommend_tools_answer(_json({'recommendations': [{'tool_type_name': '型号A',
                'manufacturer': '不代表厂家', 'inventory': 99, 'unit_price_yuan': 99999, **extra}]}))
            self.assertIn(f'| 型号A | {price} |', answer)
            self.assertNotIn('99999', answer)
            self.assertNotIn('不代表厂家', answer)
            self.assertNotIn('库存', answer)
            self.assertIn('平均服役环数只用厂家已确认的拆下记录；报价是各厂家的新刀报价区间，不代表某一家。', answer)
        for extra in ({}, {'replacement_count': 3}):
            answer = self.assistant._format_position_stratum_answer(_json({'top_positions': [{'position': 'S1L', 'total': 5, **extra}]}))
            self.assertIn('地层标签关联次数', answer)
            if extra:
                self.assertIn('实际更换次数', answer)
                self.assertIn('| 3 |', answer)
        answer = self.assistant._format_opening_efficiency_answer(_json({'recent_records': [{'ring_no': 1, 'opening_duration': 0, 'tool_change_total': 1}]}))
        self.assertIn('平均更换一把刀约 暂无', answer)

    def test_anomaly_records_show_ring_segment_time_and_value(self):
        answer = self.assistant._format_tunneling_anomaly_answer(_json({'total_records': 3, 'threshold_k': 1.5,
            'anomaly_records': [{'record_id': 1, 'ring_no': 5, 'segment_index': 2, 'start_time': '2026-01-01 10:00',
                                 'end_time': '2026-01-01 10:05', 'metric': 'thrust', 'value': 180, 'average': 100, 'ratio': 1.8}]}))
        self.assertIn('分段均值偏高筛查', answer)
        self.assertIn('| 5 | 2 | 2026-01-01 10:00 | 2026-01-01 10:05 | 总推力 | 180 | 100 | 1.8 |', answer)
        self.assertNotIn('波动', answer)
        # 服务层调用不再传单位，报告用贯入度的 mm/r
        self.assertIn('| 贯入度 | mm/r |', answer)

    def test_correlation_coverage_and_no_comparison_for_insufficient_overlap(self):
        data = {'total_records': 2, 'comparable_segment_count': 0, 'coverage': {
            'tunneling': {'record_count': 2, 'ring_min': 5, 'ring_max': 5, 'time_min': '2026-01-01', 'time_max': '2026-02-01'},
            'tool_change': {'observation_count': 8, 'ring_min': 15, 'ring_max': 487, 'open_time_min': '2023-01-01', 'open_time_max': '2023-12-01'},
        }, 'segments': [{'ring_range': '1-50', 'avg_penetration': 10}, {'ring_range': '51-100', 'avg_penetration': 20}]}
        answer = render_report('tunneling_correlation', data, self.assistant._answer_table)
        for text in ('5–5 环', '15–487 环', '2026-01-01', '2023-01-01', '掘进数据和换刀数据按环段并列显示，不代表两者有关联或因果。',
                     '掘进数据和换刀数据的环号、年份都不重合，只分别列出。'):
            self.assertIn(text, answer)
        self.assertNotIn('贯入度首个有效段均值', answer)


class CoverageRefreshTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='AI-REFRESH', project_name='范围核对')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='REFRESH', shield_model='REFRESH')
        WarehouseOpeningBasicInfo.objects.bulk_create([
            WarehouseOpeningBasicInfo(warehouse_id=f'REFRESH-{ring}', project=cls.project, shield_model=cls.machine,
                                      ring_no=str(ring), open_time=timezone.now()) for ring in (9, 100)
        ])
        ShieldTunnelingData.objects.bulk_create([
            ShieldTunnelingData(project=cls.project, shield_machine=cls.machine, ring_no=str(ring), record_time=timezone.now())
            for ring in (5, 20)
        ])
        StratumBasicInfo.objects.bulk_create([
            StratumBasicInfo(project=cls.project, ring_no=str(ring)) for ring in (1, 2800)
        ])

    def test_coverage_numeric_order_and_snapshot_labels(self):
        opening = _data_coverage(self.project.project_id, '开仓')
        self.assertEqual((opening['ring_min'], opening['ring_max']), (9, 100))
        snapshot = _build_project_snapshot(self.project.project_id)
        self.assertEqual(snapshot['snapshot_latest_ring'], 100)
        self.assertEqual(snapshot['snapshot_tunneling_coverage']['ring_max'], 20)
        self.assertEqual(snapshot['snapshot_stratum_coverage']['ring_max'], 2800)
        assistant = ToolAssistant.__new__(ToolAssistant)
        assistant.memory = MemoryService(backend='django')
        message = assistant._build_context_message(snapshot)
        self.assertIn('最新开仓第 100 环', message)
        self.assertIn('掘进数据覆盖第 5–20 环', message)
        self.assertIn('地层资料覆盖第 1–2800 环', message)
        self.assertIn('现场观测记录', message)
        self.assertEqual(assistant._recent_ring_range('最近有记录的10环掘进', {'project_id': self.project.project_id}), [11, 20])
        self.assertEqual(assistant._recent_ring_range('最近有记录的10环地层', {'project_id': self.project.project_id}), [91, 100])
