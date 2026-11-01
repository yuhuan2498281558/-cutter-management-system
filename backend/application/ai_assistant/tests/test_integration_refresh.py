"""接入、规则答案和请求契约验收；模型使用桩，数据库仅使用隔离测试库。"""
import inspect
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asgiref.sync import sync_to_async
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from application.ai_assistant import llm_service as service, tools, views
from application.ai_assistant.answer_reporting import render_report
from application.ai_assistant.memory_service import MemorySnapshot
from application.shield.models import (
    ProjectInfo, ShieldMachineBasicInfo, ShieldTunnelingData, StratumBasicInfo,
    ToolChangeDetail, WarehouseOpeningBasicInfo,
)


_NEW_TOOLS = {
    'tool_query_tool_inspections': ('query_tool_inspections', {'recent_openings': 0}),
    'tool_query_old_tool_repairs': ('query_old_tool_repairs', {'inspection_status': 'UNKNOWN'}),
    'tool_trace_tool_lifecycle': ('trace_tool_lifecycle', {'tool_ids': [' ']}),
    'tool_compare_manufacturer_service': ('compare_manufacturer_service', {'min_samples': 0}),
    'tool_query_stratum_area': ('query_stratum_area', {'basis': 'label'}),
    'tool_query_opening_stratum': ('query_opening_stratum', {'ring_no': 1, 'recent_openings': 2}),
    'tool_query_tool_cost_catalog': ('query_tool_cost_catalog', {'cost_type': 'UNKNOWN'}),
    'tool_query_registered_amounts': ('query_registered_amounts', {'group_by': 'price'}),
    'tool_query_data_catalog': ('query_data_catalog', {'unexpected': True}),
    'tool_query_tool_mileage': ('query_tool_mileage', {'manufacturers': [' ']}),
}


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _assistant():
    assistant = service.ToolAssistant()
    snapshot = MemorySnapshot(scope_key='user:1', backend='legacy')
    assistant._load_memory = Mock(return_value=snapshot)
    assistant._store_turn_and_summarize = Mock(return_value=snapshot)
    assistant._ensure_llm_runtime = Mock(side_effect=AssertionError('禁止调用模型'))
    return assistant


class IntegrationContractsTests(SimpleTestCase):
    def test_tool_list_groups_and_signatures(self):
        names = {tool.name for tool in service.TOOLS}
        self.assertEqual(len(service.TOOLS), 22)
        self.assertTrue(set(_NEW_TOOLS) <= names)
        self.assertTrue(names.isdisjoint({'tool_calculate_tool_performance', 'tool_compare_manufacturer_performance'}))
        for group in service.TOOL_GROUPS.values():
            self.assertIn(service.tool_query_data_catalog, group)
            self.assertTrue({tool.name for tool in group} <= names)
        for tool in service.TOOLS:
            self.assertEqual(set(inspect.signature(tool.func).parameters), set(tool.args_schema.model_fields), tool.name)

    def test_new_wrappers_reject_invalid_arguments_and_project_injection(self):
        for name, (_, invalid) in _NEW_TOOLS.items():
            tool = getattr(service, name)
            base = {'tool_ids': ['UID-1']} if name == 'tool_trace_tool_lifecycle' else {}
            for value in (invalid, {**base, 'project_id': 'OTHER'}):
                with self.subTest(name=name, value=value), patch.object(tool, 'func') as execute:
                    self.assertEqual(json.loads(tool.invoke(value))['code'], 'invalid_tool_arguments')
                    execute.assert_not_called()
        for tool, value in ((service.tool_query_tool_inspections, {'ring_range': [1, 5], 'recent_openings': 2}),
                            (service.tool_query_old_tool_repairs, {'list_limit': 201}),
                            (service.tool_query_stratum_area, {'rings': [1, 1]}),
                            (service.tool_query_stratum_area, {'rings': [1], 'ring_range': [1, 5]})):
            self.assertEqual(json.loads(tool.invoke(value))['code'], 'invalid_tool_arguments')

    def test_new_wrappers_bind_project_and_omit_empty_filters(self):
        for name, (function, _) in _NEW_TOOLS.items():
            bound = service._bind_tools_to_project([getattr(service, name)], 'TEST')[0]
            params = {'tool_ids': ['UID-1']} if name == 'tool_trace_tool_lifecycle' else {}
            with self.subTest(name=name), patch.object(service, function, return_value='{}') as query:
                bound.invoke(params)
            forwarded = json.loads(query.call_args.args[0])
            self.assertEqual(forwarded['project_id'], 'TEST')
            self.assertFalse(any(value in (None, '', []) for value in forwarded.values()))

    def test_existing_parameters_forward_and_stratum_codes_validate(self):
        cases = [
            ('tool_query_opening_records', 'query_opening_records', {'summary_status': 'CONFIRMED'}),
            ('tool_query_cutter_position_stats', 'query_cutter_position_stats',
             {'top_n': 122, 'cutter_position_no': 'S1L', 'include_all': True, 'sort_by': 'abnormal'}),
            ('tool_recommend_tools', 'recommend_tools', {'stratum_types': ['AREA_BOULDER'], 'stratum_basis': 'longitudinal_area', 'min_samples': 5}),
        ]
        for name, function, params in cases:
            with patch.object(service, function, return_value='{}') as query:
                getattr(service, name).invoke(params)
            forwarded = json.loads(query.call_args.args[0])
            for key, value in params.items():
                self.assertEqual(forwarded[key], value)
        # 模型只给默认参数时，空的筛选值不能传给工具（工具会当成无效值报错，整题中断）。
        for name, function, empty in [('tool_query_opening_records', 'query_opening_records', 'summary_status'),
                                      ('tool_query_cutter_position_stats', 'query_cutter_position_stats', 'cutter_position_no')]:
            with patch.object(service, function, return_value='{}') as query:
                getattr(service, name).invoke({})
            self.assertNotIn(empty, json.loads(query.call_args.args[0]))
        for basis, code in [('label', 'AREA_BOULDER'), ('longitudinal_area', 'BOULDER'), ('label', 'UNKNOWN')]:
            result = json.loads(service.tool_recommend_tools.invoke({'stratum_basis': basis, 'stratum_types': [code]}))
            self.assertEqual(result['code'], 'invalid_tool_arguments')

    def test_iteration_limit_and_multi_source_tools(self):
        assistant = _assistant()
        assistant._llm, assistant._prompt = Mock(), Mock()
        assistant._ensure_agent_runtime = Mock()
        for query in ('综合返修、报价和掘进参数给出风险分析', '结合检查、地层、厂家和费用分析'):
            self.assertEqual(assistant._tool_group_for_query(query), 'all')
            selected = assistant._get_tools_for_query(query, project_id='TEST')
            self.assertEqual(len(selected), 22)
        with patch.object(service, 'invoke_agent', return_value={
            'output': '已查到数据。', 'intermediate_steps': [(None, {'total_records': 2})],
        }) as invoke:
            result = assistant.chat('综合返修、报价和掘进参数给出风险分析',
                                    {'project_id': 'TEST', 'route_mode': 'agent'})
        self.assertTrue(result['success'], result)
        self.assertEqual(invoke.call_args.kwargs['max_iterations'], 10)
        self.assertEqual(len(invoke.call_args.args[2]), 22)


class IntegrationRoutingTests(SimpleTestCase):
    def setUp(self):
        self.assistant = _assistant()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.calls = {function: self.stack.enter_context(patch.object(service, function, return_value='{}'))
                      for function, _ in _NEW_TOOLS.values()}
        self.stack.enter_context(patch.object(self.assistant, '_named_manufacturers', return_value=[]))
        self.stack.enter_context(patch('application.shield.models.ToolInfo.objects'))

    def ask(self, query):
        return self.assistant._direct_route(query, {'project_id': 'TEST'})

    def test_nine_rule_branches_and_forwarded_parameters(self):
        cases = [
            ('第2199环孤石占多少', 'stratum_area', 'query_stratum_area', {'rings': [2199], 'basis': 'longitudinal_area'}),
            ('第317环开仓位置是什么地层，上次开仓以来经过了哪些地层', 'opening_stratum', 'query_opening_stratum', {'ring_no': 317}),
            ('最近3次开仓哪些刀需要关注但还没换', 'tool_inspections', 'query_tool_inspections', {'recent_openings': 3}),
            ('还有多少旧刀在等厂家反馈', 'old_tool_repairs', 'query_old_tool_repairs', {'inspection_status': 'PENDING_VENDOR_FEEDBACK'}),
            ('追溯 GD-TEST-0001 和 DEMO-15-17-001', 'tool_lifecycle', 'trace_tool_lifecycle', {'tool_ids': ['GD-TEST-0001', 'DEMO-15-17-001']}),
            ('各厂家刀具寿命和异常率对比', 'manufacturer_service', 'compare_manufacturer_service', {}),
            ('可更换式刮刀H=400新刀多少钱', 'tool_cost_catalog', 'query_tool_cost_catalog', {'cost_type': 'NEW_TOOL', 'tool_type': 'SCRAPER'}),
            ('项目一共登记了多少金额，按厂家分', 'registered_amounts', 'query_registered_amounts', {'group_by': 'manufacturer'}),
            ('现在有哪些数据可以查', 'data_catalog', 'query_data_catalog', {}),
        ]
        for query, branch, function, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.ask(query)['rule_branch'], branch)
                params = json.loads(self.calls[function].call_args.args[0])
                self.assertEqual(params['project_id'], 'TEST')
                for key, value in expected.items():
                    self.assertEqual(params[key], value)

    def test_area_ranges_basis_and_discrete_rings(self):
        for question, expected in [('统计100环到300环各地层面积占比', {'ring_range': [100, 300]}),
                                   ('第317环横断面岩性占比', {'rings': [317], 'basis': 'cross_section'}),
                                   ('第100环和第200环孤石占多少', {'rings': [100, 200]})]:
            self.assertEqual(self.ask(question)['rule_branch'], 'stratum_area')
            params = json.loads(self.calls['query_stratum_area'].call_args.args[0])
            for key, value in expected.items():
                self.assertEqual(params[key], value)

    def test_priority_and_retained_branches(self):
        self.assertEqual(self.ask('推荐 GD-TEST-0001 的厂家刀具，追溯寿命')['rule_branch'], 'tool_lifecycle')
        self.assertEqual(self.ask('旧刀编号 OLD-A 的去向')['rule_branch'], 'tool_lifecycle')
        self.assertEqual(json.loads(self.calls['trace_tool_lifecycle'].call_args.args[0])['tool_ids'], ['OLD-A'])
        self.assertEqual(self.ask('库存有多少')['rule_branch'], 'inventory')
        with patch.object(service, 'recommend_tools', return_value='{}'):
            self.assertEqual(self.ask('推荐刮刀型号，比较报价')['rule_branch'], 'tool_recommendation')
        with patch.object(service, 'query_tool_change_data', return_value='{}') as query:
            self.assertEqual(self.ask('追溯S1L')['rule_branch'], 'position_point_query')
            self.assertEqual(json.loads(query.call_args.args[0])['cutter_position_no'], 'S1L')
        with patch.object(service, 'query_stratum_data', return_value='{}'):
            self.assertEqual(self.ask('第100环地层标签有哪些')['rule_branch'], 'stratum_distribution')

    def test_actual_spending_notice_precedes_registered_amounts(self):
        self.calls['query_registered_amounts'].return_value = _json({'total_registered_cost_yuan': 123.45,
            'new_install': {'amount_yuan': 100}, 'confirmed_repair': {'amount_yuan': 23.45}, 'pending_repair': {'amount_yuan': 50}})
        for query in ('项目实际支出多少钱', '项目实际采购与付款金额', '当前项目实际刀具采购加返修总成本是多少'):
            result = self.ask(query)
            self.assertEqual(result['rule_branch'], 'registered_amounts')
            self.assertTrue(result['answer'].startswith('系统里没有实际采购和付款台账，下面是登记金额，不是实际支出。'))
            self.assertIn('登记合计：123.45 元', result['answer'])

    def test_repair_scrap_and_detail_limit(self):
        self.calls['query_old_tool_repairs'].return_value = _json({'scope': {'record_count': 25},
            'scrapped_count': 2, 'scrap_suggestion_count': 3, 'records': [{'old_tool_number': f'OLD-{i}'} for i in range(25)]})
        answer = self.ask('已经报废了多少把刀')['answer']
        self.assertLess(answer.index('已报废：2'), answer.index('报废建议：3'))
        self.assertNotIn('返修明细', answer)
        self.calls['query_old_tool_repairs'].return_value = _json({'scope': {'record_count': 25},
            'scrapped_count': 2, 'scrap_suggestion_count': 3,
            'records': [{'old_tool_number': f'OLD-{i}', 'disposition': 'SCRAP'} for i in range(25)]})
        answer = self.ask('列出报废旧刀名单')['answer']
        self.assertIn('共 25 条，显示前 20 条', answer)
        self.assertNotIn('OLD-20', answer)

    def test_repair_status_and_scrap_filters_follow_question(self):
        cases = [
            ('待厂家反馈的旧刀共有多少把', {'inspection_status': 'PENDING_VENDOR_FEEDBACK'}),
            ('已归档的旧刀返修登记金额是多少', {'inspection_status': 'CLOSED'}),
            ('统计旧刀返修进度，列出待厂家反馈、已确认、已归档的数量', {}),
            ('旧刀已报废多少，报废建议多少', {}),
            ('列出报废的旧刀', {'disposition': 'SCRAP'}),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.ask(query)['rule_branch'], 'old_tool_repairs')
                params = json.loads(self.calls['query_old_tool_repairs'].call_args.args[0])
                for key in ('inspection_status', 'disposition'):
                    self.assertEqual(params.get(key), expected.get(key))

    def test_new_install_amounts_go_to_registered_amounts(self):
        self.assertEqual(self.ask('滚刀新装和返修登记金额分别多少')['rule_branch'], 'registered_amounts')
        self.assertEqual(json.loads(self.calls['query_registered_amounts'].call_args.args[0])['tool_type'], 'DISC')

    def test_confirmed_openings_exclude_drafts(self):
        with patch.object(service, 'query_opening_records', return_value='{}') as query:
            self.assertEqual(self.ask('只统计已确认开仓，排除草稿')['rule_branch'], 'opening')
            self.assertEqual(json.loads(query.call_args.args[0])['summary_status'], 'CONFIRMED')
            self.ask('只看草稿状态的开仓记录')
            self.assertEqual(json.loads(query.call_args.args[0])['summary_status'], 'DRAFT')

    def test_how_many_openings_colloquial_goes_to_opening(self):
        with patch.object(service, 'query_opening_records', return_value='{}'):
            self.assertEqual(self.ask('开了几次仓？')['rule_branch'], 'opening')

    def test_ripper_observation_question_stays_on_rules(self):
        # 模型工具不接受 RIPPER，交给模型会因参数校验失败而整段报错；规则查询直接返回 0 条。
        with patch.object(service, 'query_tool_change_data', return_value='{}') as query:
            self.assertEqual(self.ask('当前有效刀位范围内有没有撕裂刀刀型的现场观测记录')['rule_branch'], 'tool_change_summary')
            self.assertEqual(json.loads(query.call_args.args[0])['tool_type'], 'RIPPER')

    def test_lifecycle_basis_and_missing_steps(self):
        data = {'results': [{'query': 'UID-1', 'missing_steps': ['厂家尚未确认'], 'service_segments': [
            {'install_ring': 10, 'removal_ring': 20, 'removal_basis': basis, 'service_rings': 10}
            for basis in ('confirmed', 'suggested', 'inferred', 'in_service')]}]}
        answer = render_report('tool_lifecycle', data, self.assistant._answer_table)
        self.assertIn('厂家尚未确认', answer)
        self.assertIn('| 确认 | 10 |', answer)
        for label in ('建议身份', '推断', '在役'):
            self.assertIn(f'| {label} | 暂无 |', answer)

    def test_component_list_filters_before_limiting(self):
        def result(params):
            self.assertEqual(json.loads(params)['components'], ['轴承'])
            record = {'ring_no': 2, 'old_tool_number': 'BEARING-1', 'failure_reasons': [{'component': '轴承', 'label': '疲劳损坏'}]}
            return _json({'scope': {'record_count': 1, 'data_ring_range': [2, 2]}, 'records': [record]})
        self.calls['query_old_tool_repairs'].side_effect = result
        answer = self.ask('轴承失效的旧刀有哪些')['answer']
        self.assertIn('BEARING-1', answer)
        self.assertNotIn('不能视为全量名单', answer)
        self.assertEqual(self.calls['query_old_tool_repairs'].call_count, 1)


class IntegrationRequestTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=1, username='integration-user', is_authenticated=True)

    async def test_invalid_focus_sources_returns_400_from_both_entries(self):
        message = 'focus_sources 只能包含：tool_change、opening、inspection、position、stratum、tunneling、manufacturer、cost、repair、lifecycle'
        for value in ('cost', ['unknown'], [1], ['cost'] * 11, None):
            body = {'query': '金额', 'focus_sources': value}
            request = APIRequestFactory().post('/', body, format='json')
            force_authenticate(request, self.user)
            response = await sync_to_async(views.chat)(request)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['msg'], message)
            request = RequestFactory().post('/', _json(body), content_type='application/json')
            with patch.object(views, '_auth_user', return_value=self.user):
                response = await views.chat_stream(request)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(json.loads(response.content)['msg'], message)

    def test_focus_sources_deduplicate_and_inject_context_without_clipping_tools(self):
        with patch.object(views, '_resolve_request_project_id', return_value='TEST'), patch.object(views, '_build_project_snapshot', return_value={}):
            context = views._context_for_user(self.user, {'focus_sources': ['repair', 'cost', 'repair'], 'route_mode': 'agent'})
        self.assertEqual(context['focus_sources'], ['repair', 'cost'])
        assistant = _assistant()
        self.assertIn('用户在界面上选择了这些数据：旧刀返修、报价与登记金额。优先用这些数据回答；问题确实需要其他数据时也可以查询。', assistant._build_context_message(context))
        self.assertNotIn('用户在界面上', assistant._build_context_message({**context, 'route_mode': 'rule'}))

    def _traced_catalog(self):
        def query_data_catalog(params):
            return _json({'scope': {'project_id': json.loads(params)['project_id']}, 'count': 2})
        return service._traced_tool(query_data_catalog)

    def test_sync_response_trace_labels_scope_and_hidden_result(self):
        assistant = _assistant()
        with patch.object(service, 'query_data_catalog', self._traced_catalog()), patch.dict('os.environ', {'AI_TRACE_TOOL_RESULTS': '0'}):
            result = assistant.chat('现在有哪些数据可以查', {'project_id': 'TEST', 'route_mode': 'rule'})
        self.assertTrue(result['success'], result)
        self.assertEqual(result['tool_calls'][0]['source_label'], '可查数据')
        self.assertEqual(result['tool_calls'][0]['scope'], {'project_id': 'TEST'})
        self.assertNotIn('result', result['tool_calls'][0])

    async def test_stream_done_contains_tool_calls_for_rule_and_agent(self):
        for mode in ('rule', 'agent'):
            assistant = _assistant()
            bound = service._bind_tools_to_project([service.tool_query_data_catalog], 'TEST')[0]

            async def events(*args, **kwargs):
                observation = await bound.ainvoke({})
                yield {'type': 'tool_end', 'call_id': 'call-1', 'name': bound.name, 'args': {}, 'observation': observation}
                yield {'type': 'final', 'output': '已查到数据。',
                       'intermediate_steps': [(SimpleNamespace(tool=bound.name, tool_input={}), observation)]}

            assistant._get_tools_for_query = Mock(return_value=[bound])
            with (patch.object(service, 'query_data_catalog', self._traced_catalog()),
                  patch.object(service, 'astream_agent', side_effect=events) as stream,
                  patch.dict('os.environ', {'AI_TRACE_TOOL_RESULTS': '0'})):
                result = [item async for item in assistant.chat_stream('现在有哪些数据可以查', {
                    'project_id': 'TEST', 'route_mode': mode, 'focus_sources': ['cost']})]
            if mode == 'agent':
                self.assertEqual(stream.call_args.kwargs['max_iterations'], 10)
            self.assertEqual(result[-1]['type'], 'done', result)
            self.assertEqual(result[-1]['tool_calls'][0]['source_label'], '可查数据')
            self.assertEqual(result[-1]['tool_calls'][0]['scope'], {'project_id': 'TEST'})
            self.assertNotIn('result', result[-1]['tool_calls'][0])
            self.assertFalse(any('tool_calls' in item for item in result[:-1]))

    def test_missing_scope_is_null_and_trace_result_flag_still_works(self):
        def query_data_catalog(params):
            return 'not JSON'
        service._trace_start()
        try:
            service._traced_tool(query_data_catalog)('{}')
            self.assertIsNone(service._trace_calls()[0]['scope'])
            self.assertEqual(service._trace_calls(include_results=True)[0]['result'], 'not JSON')
        finally:
            service._trace_stop()

    def test_efficiency_minutes_and_weighted_average(self):
        answer = _assistant()._format_opening_efficiency_answer(_json({'recent_records': [
            {'ring_no': 10, 'opening_duration': 2, 'tool_change_duration_hours': 1, 'tool_change_total': 5, 'tool_change_replaced': 2},
            {'ring_no': 20, 'opening_duration': 4, 'tool_change_duration_hours': 2, 'tool_change_total': 15, 'tool_change_replaced': 8}],
            'efficiency_all': {'opening_count': 2, 'check_minutes_per_tool': 18, 'replace_minutes_per_tool': 18}}))
        self.assertIn('平均检查一把刀约 18.0 分钟；平均更换一把刀约 18.0 分钟', answer)
        self.assertIn('检查效率（分钟/把）', answer)
        self.assertIn('更换效率（分钟/把）', answer)
        self.assertIn('不是每把刀的实际作业工时', answer)


class IntegrationCoverageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = ProjectInfo.objects.create(project_id='INTEGRATION', project_name='接入验收')
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id='INTEGRATION', shield_model='A')
        cls.now = timezone.now()
        opening = WarehouseOpeningBasicInfo(warehouse_id='I-100', project=cls.project, shield_model=cls.machine, ring_no='100', open_time=cls.now)
        WarehouseOpeningBasicInfo.objects.bulk_create([opening])
        ToolChangeDetail.objects.bulk_create([ToolChangeDetail(warehouse=opening, cutter_position_no='1', tool_parent_type='DISC', is_checked=True, manufacturer='厂家甲')])
        ShieldTunnelingData.objects.bulk_create([ShieldTunnelingData(project=cls.project, shield_machine=cls.machine, ring_no='5', record_time=cls.now, torque=10)])
        StratumBasicInfo.objects.bulk_create([StratumBasicInfo(project=cls.project, ring_no=str(ring)) for ring in (5, 100, 300)])

    def test_full_project_coverage_and_union_default_window(self):
        for params, window, counts in [({}, [5, 100], {'tunneling': 1, 'tool_change': 1, 'stratum': 2}),
                                       ({'ring_range': [1, 10]}, [1, 10], {'tunneling': 1, 'tool_change': 0, 'stratum': 1})]:
            data = json.loads(tools.query_tunneling_wear_correlation(_json({'project_id': 'INTEGRATION', **params})))
            self.assertNotIn('error', data)
            self.assertEqual(data['ring_range'], window)
            self.assertEqual(data['window_counts'], counts)
            self.assertEqual(data['coverage']['tool_change']['observation_count'], 1)
            self.assertEqual(data['coverage']['tool_change']['ring_max'], 100)
            self.assertEqual(data['coverage']['stratum']['ring_max'], 300)
            self.assertIsNotNone(data['coverage']['tool_change']['open_time_min'])
            answer = render_report('tunneling_correlation', data, service.ToolAssistant._answer_table)
            self.assertIn('记录数 1（全项目）', answer)
            self.assertIn(f"现场观测记录 {counts['tool_change']} 条", answer)

    def test_named_manufacturer_uses_site_names_and_forwards_filter(self):
        assistant = _assistant()
        self.assertEqual(assistant._named_manufacturers('对比厂家甲和厂家乙的寿命', 'INTEGRATION'), ['厂家甲'])
        with patch.object(service, 'compare_manufacturer_service', return_value='{}') as query:
            result = assistant._direct_route('厂家甲的刀具寿命和异常率对比', {'project_id': 'INTEGRATION'})
        self.assertEqual(result['rule_branch'], 'manufacturer_service')
        self.assertEqual(json.loads(query.call_args.args[0])['manufacturers'], ['厂家甲'])
        self.assertNotIn('现在还不能只看指定厂家', result['answer'])
