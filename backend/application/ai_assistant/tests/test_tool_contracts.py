"""Tool-boundary and model-routing regressions; never call a real provider."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from pydantic import ValidationError

from application.ai_assistant import llm_service
from application.ai_assistant.llm_service import ToolAssistant, TOOLS, _bind_tools_to_project
from application.ai_assistant.memory_service import MemorySnapshot
from application.ai_assistant.prompts import ANSWER_POLICY, SYSTEM_PROMPT
from application.ai_assistant.tool_contracts import (
    ChangeQuery, RecommendationQuery, PerformanceQuery, AnomalyQuery,
)


class ToolContractTests(SimpleTestCase):
    def test_all_public_tools_reject_project_injection_and_malformed_ranges(self):
        for tool in TOOLS:
            base = {'tool_numbers': ['100-S1L-01']} if tool.name == 'tool_calculate_tool_performance' else {}
            invalid = [{'project_id': 'OTHER'}, {'user_id': 999}]
            if 'ring_range' in tool.args_schema.model_fields:
                invalid += [{'ring_range': value} for value in ([100], [200, 100], [True, 200],
                           ['100', '200'], [1, 2, 3], [0, 2], [1, 1_000_000_000])]
            for extra in invalid:
                with self.subTest(tool=tool.name, extra=extra), patch.object(tool, 'func') as execute:
                    observation = json.loads(tool.invoke({**base, **extra}))
                    self.assertEqual(observation['code'], 'invalid_tool_arguments')
                    execute.assert_not_called()

    def test_normalized_values_reach_request_bound_tool(self):
        tool = _bind_tools_to_project([llm_service.tool_query_tool_change_data], 'PROJECT-A')[0]
        with patch.object(llm_service, 'query_tool_change_data', return_value='{}') as query:
            tool.invoke({'tool_type': ' disc ', 'cutter_position_no': '046', 'ring_range': [100, 200]})
        params = json.loads(query.call_args.args[0])
        self.assertEqual(params['project_id'], 'PROJECT-A')
        self.assertEqual(params['tool_type'], 'DISC')
        self.assertEqual(params['cutter_position_no'], '46')
        self.assertEqual(params['ring_range'], [100, 200])

    def test_invalid_identity_and_controls_are_not_silently_widened(self):
        cases = [
            (ChangeQuery, {'tool_type': 'RIPPER'}),
            (ChangeQuery, {'cutter_position_no': 'MF10L'}),
            (ChangeQuery, {'tool_type': 'DISC', 'cutter_position_no': 'S1L'}),
            (ChangeQuery, {'last_n_openings': -1}),
            (RecommendationQuery, {'max_unit_price': float('nan')}),
            (RecommendationQuery, {'max_unit_price': -1}),
            (RecommendationQuery, {'top_n': 51}),
            (PerformanceQuery, {'tool_numbers': []}),
            (PerformanceQuery, {'tool_numbers': [' ']}),
            (AnomalyQuery, {'threshold_k': float('inf')}),
            (AnomalyQuery, {'threshold_k': 0}),
        ]
        for schema, values in cases:
            with self.subTest(schema=schema.__name__, values=values), self.assertRaises(ValidationError):
                schema.model_validate(values)

    def test_model_selection_exposes_all_tools_without_keyword_clipping(self):
        assistant = ToolAssistant()
        assistant._ensure_agent_runtime = Mock()
        assistant._create_executor = Mock(return_value='executor')
        assistant._get_executor_for_query('对照不同供货商与施工参数',
                                          project_id='PROJECT-A', model_selects_tools=True)
        selected = assistant._create_executor.call_args.args[0]
        self.assertEqual({item.name for item in selected}, {item.name for item in TOOLS})
        self.assertTrue(all('project_id' not in item.args for item in selected))

    def test_model_business_queries_do_not_depend_on_legacy_keyword_list(self):
        assistant = ToolAssistant()
        context = {'route_mode': 'agent'}
        for query in ('本项目费用构成', '目前成本最高的品牌', '本工程刀圈崩口分布', '统计最近100环换刀情况',
                      '正常磨损是什么意思，顺便统计更换次数', '换刀最多的厂家是什么',
                      '正常磨损是什么意思，哪个品牌最多'):
            self.assertTrue(assistant._model_needs_tools(query, context), query)
        for query in ('正常磨损是什么意思', '滚刀是什么', '什么是滚刀？', '滚刀和刮刀有什么区别', '你好'):
            self.assertFalse(assistant._model_needs_tools(query, context), query)

    def test_corrected_tool_error_can_complete_but_unresolved_error_cannot(self):
        assistant = ToolAssistant()
        action = SimpleNamespace(tool='tool_query_tool_change_data', tool_input={'ring_range': [200, 100]},
                                 message_log=[llm_service.AIMessage(content='', tool_calls=[
                                     {'name': 'tool_query_tool_change_data', 'args': {}, 'id': 'bad'},
                                 ])])
        corrected = SimpleNamespace(tool=action.tool, tool_input={'ring_range': [100, 200]},
                                    message_log=[llm_service.AIMessage(content='', tool_calls=[
                                        {'name': action.tool, 'args': {}, 'id': 'corrected'},
                                    ])])
        other = SimpleNamespace(tool='tool_query_stratum_data')
        error = {'error': 'invalid arguments', 'code': 'invalid_tool_arguments', 'fields': ['ring_range']}
        success = {'total_records': 1}
        self.assertEqual(assistant._validated_agent_answer({
            'output': '有1条记录', 'intermediate_steps': [(action, error), (corrected, success)],
        }), '有1条记录')
        with self.assertRaises(RuntimeError):
            assistant._validated_agent_answer({
                'output': '不完整结论', 'intermediate_steps': [(action, error), (other, success)],
            })
        with self.assertRaises(RuntimeError):
            assistant._validated_agent_answer({
                'output': '不能用另一查询掩盖失败',
                'intermediate_steps': [(action, {'error': 'database timeout'}), (action, success)],
            })

    def test_bound_tool_returns_actionable_error_without_executing_query(self):
        tool = _bind_tools_to_project([llm_service.tool_query_tool_change_data], 'PROJECT-A')[0]
        with patch.object(llm_service, 'query_tool_change_data') as query:
            error = json.loads(tool.invoke({'ring_range': [200, 100]}))
        self.assertEqual(error['fields'], ['ring_range'])
        query.assert_not_called()

    def test_opening_unknown_rate_is_excluded_from_comparison(self):
        unknown = {'ring_no': '100', 'abnormal_rate': None, 'abnormal_rate_denominator': 0}
        zero = {'ring_no': '200', 'abnormal_rate': '0.0%', 'abnormal_rate_denominator': 3}
        for rows, expected in (([unknown], []), ([unknown, zero], ['200'])):
            result = json.loads(llm_service._with_analysis_payload(json.dumps({'recent_records': rows}), 'opening'))
            self.assertEqual(len(result['highlights']), len(expected))
            if expected:
                self.assertIn('环号 200', result['highlights'][0])

    def test_agent_prompt_and_polish_share_evidence_policy(self):
        assistant = ToolAssistant()
        self.assertIn(ANSWER_POLICY, SYSTEM_PROMPT)
        self.assertIn(ANSWER_POLICY, assistant._build_polish_messages('厂家对比', '结果')[0].content)
        for old in ('排名第一的厂家质量最好', '间隔越短说明刀具磨损越快', '不存在其他地层类型', '传入JSON字符串参数'):
            self.assertNotIn(old, SYSTEM_PROMPT)
        # The actual LangChain template remains renderable after prompt changes.
        template = llm_service.ChatPromptTemplate.from_messages([
            ('system', SYSTEM_PROMPT), ('human', '{input}'),
        ])
        self.assertEqual(template.input_variables, ['input'])
        self.assertTrue(template.format_messages(input='厂家对比'))

    def test_capability_and_general_explanations_do_not_require_irrelevant_tools(self):
        assistant = ToolAssistant()
        context = {'route_mode': 'agent'}
        for query in ('项目实际总支出', '你可以帮我修改换刀记录吗', '为什么滚刀会偏磨'):
            self.assertFalse(assistant._model_needs_tools(query, context), query)
        for query in ('项目实际总支出，并统计换刀次数', '本项目为什么滚刀会偏磨'):
            self.assertTrue(assistant._model_needs_tools(query, context), query)
        message = assistant._build_direct_messages('项目实际总支出')[0].content
        self.assertIn('不具备业务数据修改、库存台账', message)
        self.assertIn('不宣称已查询、已修改', message)

    def make_assistant(self):
        assistant = ToolAssistant()
        snapshot = MemorySnapshot(scope_key='user:1', backend='legacy')
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._prepare_query_context = Mock(return_value={
            'user_id': '1', 'project_id': 'PROJECT-A', 'route_mode': 'agent',
            'effective_query': '统计最近100环换刀情况', 'memory_slots': {'ring_range': [101, 200]},
            'query_spec': {}, 'resolved_context_mode': 'new',
        })
        assistant._direct_route = Mock(side_effect=AssertionError('Model mode used rule fallback'))
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._get_executor_for_query = Mock()
        return assistant

    def test_sync_model_mode_does_not_fall_back_for_recent_ring_query(self):
        assistant = self.make_assistant()
        assistant._invoke_with_retry = Mock(return_value={
            'output': '已查询所选范围', 'intermediate_steps': [(None, {'total_records': 2})],
        })
        result = assistant.chat('统计最近100环换刀情况', {'user_id': 1, 'route_mode': 'agent'})
        self.assertTrue(result['success'])
        self.assertEqual(result['tool_group'], 'all')
        assistant._direct_route.assert_not_called()
        self.assertTrue(assistant._get_executor_for_query.call_args.kwargs['model_selects_tools'])

    async def test_stream_model_mode_matches_sync_tool_selection(self):
        assistant = self.make_assistant()

        async def events(*args, **kwargs):
            yield {'event': 'on_chain_start', 'run_id': 'root', 'parent_ids': []}
            yield {'event': 'on_tool_end', 'name': TOOLS[0].name, 'data': {'output': {'total_records': 2}}}
            yield {'event': 'on_chain_end', 'run_id': 'root', 'data': {'output': {
                'output': '已查询所选范围', 'intermediate_steps': [(None, {'total_records': 2})],
            }}}

        assistant._get_executor_for_query.return_value = SimpleNamespace(astream_events=events)
        result = [item async for item in assistant.chat_stream('统计最近100环换刀情况', {'user_id': 1})]
        self.assertEqual(result[0]['tool_group'], 'all')
        self.assertEqual(result[-1]['type'], 'done')
        assistant._direct_route.assert_not_called()
        self.assertTrue(assistant._get_executor_for_query.call_args.kwargs['model_selects_tools'])

    async def test_stream_can_recover_parameter_error_without_saving_partial_turn(self):
        assistant = self.make_assistant()
        name = TOOLS[0].name
        invalid_args, valid_args = {'ring_range': [200, 100]}, {'ring_range': [100, 200]}
        action = SimpleNamespace(tool=name, tool_input=invalid_args,
                                 message_log=[llm_service.AIMessage(content='', tool_calls=[
                                     {'name': name, 'args': invalid_args, 'id': 'bad'},
                                 ])])
        corrected = SimpleNamespace(tool=name, tool_input=valid_args,
                                    message_log=[llm_service.AIMessage(content='', tool_calls=[
                                        {'name': name, 'args': valid_args, 'id': 'corrected'},
                                    ])])
        error = {'error': 'invalid arguments', 'code': 'invalid_tool_arguments', 'fields': ['ring_range']}
        success = {'total_records': 2}

        async def events(*args, **kwargs):
            yield {'event': 'on_chain_start', 'run_id': 'root', 'parent_ids': []}
            yield {'event': 'on_chat_model_start', 'run_id': 'model1'}
            yield {'event': 'on_tool_start', 'run_id': 'bad', 'name': name, 'data': {'input': invalid_args}}
            yield {'event': 'on_tool_end', 'run_id': 'bad', 'name': name, 'data': {'output': error}}
            yield {'event': 'on_chat_model_start', 'run_id': 'model2'}
            yield {'event': 'on_tool_start', 'run_id': 'corrected', 'name': name, 'data': {'input': valid_args}}
            yield {'event': 'on_tool_end', 'run_id': 'corrected', 'name': name, 'data': {'output': success}}
            yield {'event': 'on_chain_end', 'run_id': 'root', 'data': {'output': {
                'output': '已查询所选范围', 'intermediate_steps': [(action, error), (corrected, success)],
            }}}

        assistant._get_executor_for_query.return_value = SimpleNamespace(astream_events=events)
        result = [item async for item in assistant.chat_stream('统计最近100环换刀情况', {'user_id': 1})]
        self.assertEqual(result[-1]['type'], 'done')
        assistant._store_turn_and_summarize.assert_called_once()

    def test_manufacturer_payload_does_not_rank_missing_evidence(self):
        raw = json.dumps({'total_records': 2, 'manufacturers': [{
            'manufacturer': 'Unknown', 'replaced_count': 2,
            'abnormal_rate_pct': None, 'abnormal_rate_denominator': 0,
        }]})
        payload = json.loads(llm_service._with_analysis_payload(raw, 'manufacturer'))
        self.assertEqual(payload['highlights'], [])
        self.assertIn('暂无', payload['facts'][-1])
        self.assertNotIn('None%', payload['facts'][-1])
