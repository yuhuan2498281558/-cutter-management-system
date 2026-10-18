"""模型视图、早前证据摘要和原始记录隔离。"""
import json
import os
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate

from application.ai_assistant import llm_service as service
from application.ai_assistant.agent_views import AGENT_PAGE_SIZE, agent_view
from application.ai_assistant.context_budget import (
    ContextBudgetExceeded, ContextBudgetPolicy, GuardedChatModel,
    estimate_request_tokens, prepare_messages,
)
from application.ai_assistant.llm_provider import LLMProviderError, get_context_policy
from application.ai_assistant.tests.test_context_budget import ToolModel


def _json(value):
    return json.dumps(value, ensure_ascii=False)


_PAGED = {
    'query_cutter_position_stats', 'query_tool_change_trend',
    'query_position_stratum_impact', 'query_tunneling_anomaly',
    'query_tunneling_wear_correlation', 'query_tool_inspections',
    'query_old_tool_repairs', 'query_tool_cost_catalog', 'query_data_catalog',
    'query_opening_records', 'query_tunneling_summary', 'query_tunneling_trend',
    'recommend_tools', 'query_registered_amounts', 'query_stratum_area',
    'compare_manufacturer_service',
}
_MARKER = '【已移出的早前结果】'
_NAME = 'tool_query_tool_inspections'
_LABELS = {_NAME: '现场检查'}


class AgentViewTests(SimpleTestCase):
    def test_nested_pages_preserve_totals_statistics_and_scalar_lists(self):
        data = {
            'scope': {'record_count': 59, 'ring_range': [1, 59]},
            'summary': {'count': 59, 'rate': 0.37},
            '_analysis_payload': {'summary': {'count': 59}},
            'rows': [{'id': i, 'children': [{'id': j} for j in range(27)]} for i in range(59)],
            'nested': {'items': [{'id': i} for i in range(42)]},
            'numbers': list(range(100)), 'strings': [str(i) for i in range(100)],
        }
        result = json.loads(agent_view(_json(data), page=2, page_size=20))
        for key in ('scope', 'summary', '_analysis_payload', 'numbers', 'strings'):
            self.assertEqual(result[key], data[key])
        self.assertEqual([row['id'] for row in result['rows']], list(range(20, 40)))
        self.assertEqual(result['rows'][0]['children'], [{'id': i} for i in range(20, 27)])
        self.assertEqual(result['_paging']['rows'], {'total': 59, 'page': 2, 'page_size': 20, 'has_more': True})
        self.assertEqual(result['_paging']['rows.0.children'], {'total': 27, 'page': 2, 'page_size': 20, 'has_more': False})
        self.assertEqual(result['_paging']['nested.items']['total'], 42)
        self.assertEqual(result['_paging_note'], '列表只给了第2页（每页20条），各列表总数见 _paging。需要后面的记录时，用相同参数加 page=3 再查。')
        self.assertEqual(AGENT_PAGE_SIZE, 50)

    def test_out_of_range_page_and_short_lists(self):
        result = json.loads(agent_view(_json({'rows': [{'id': i} for i in range(21)], 'short': [{'id': 1}]}), page=50, page_size=20))
        self.assertEqual(result['rows'], [])
        self.assertFalse(result['_paging']['rows']['has_more'])
        self.assertEqual(result['short'], [{'id': 1}])
        self.assertNotIn('_paging', json.loads(agent_view(_json({'rows': [{'id': 1}]}))))

    def test_long_text_deduplicates_only_visible_exact_matches(self):
        long = '口径' * 20
        raw = _json({'note': long, 'summary': {'count_basis': long}, 'other': long + '。', 'short': ['说明'] * 2})
        result = json.loads(agent_view(raw))
        self.assertEqual(result['note'], long)
        self.assertEqual(result['summary']['count_basis'], '（同上）')
        self.assertEqual(result['other'], long + '。')
        self.assertEqual(result['short'], ['说明'] * 2)
        rows = [{'note': long} for _ in range(21)]
        self.assertEqual(json.loads(agent_view(_json({'rows': rows}), page=2, page_size=20))['rows'][0]['note'], long)

    def test_error_result_is_byte_for_byte_unchanged(self):
        for error in ('失败', ''):
            raw = json.dumps({'error': error, 'note': '说明' * 30, 'rows': [{'note': '说明' * 30}] * 30}, indent=2)
            self.assertEqual(agent_view(raw), raw)

    def test_no_pagination_keeps_nested_lists_and_still_deduplicates(self):
        rows = [{'id': i} for i in range(31)]
        long = '统计口径' * 20
        result = json.loads(agent_view(_json({
            'rows': rows, 'nested': {'rows': rows}, 'note': long, 'summary': long,
        }), page_size=None))
        self.assertEqual(result['rows'], rows)
        self.assertEqual(result['nested']['rows'], rows)
        self.assertEqual(result['note'], long)
        self.assertEqual(result['summary'], '（同上）')
        self.assertNotIn('_paging', result)
        self.assertNotIn('_paging_note', result)

    def test_wrappers_page_without_forwarding_pagination_or_changing_trace(self):
        raw = _json({'scope': {'record_count': 31}, 'summary': {'count': 31}, 'facts': ['全部31条'], 'rows': [{'id': i} for i in range(31)]})
        for tool in [*service.TOOLS, service.tool_calculate_tool_performance,
                     service.tool_compare_manufacturer_performance]:
            name = tool.name.removeprefix('tool_')
            self.assertEqual('page' in tool.args_schema.model_fields, name in _PAGED)
            self.assertEqual('page_size' in tool.args_schema.model_fields, name in _PAGED)
            params = {'tool_ids': ['UID']} if name == 'trace_tool_lifecycle' else {}
            if name == 'calculate_tool_performance':
                params = {'tool_numbers': ['UID']}
            if name in _PAGED:
                params.update(page=2, page_size=5)
                properties = tool.args_schema.model_json_schema()['properties']
                for key, default, minimum in (('page', 1, 1), ('page_size', 50, 5)):
                    self.assertEqual({field: properties[key][field] for field in ('type', 'default', 'minimum', 'maximum')},
                                     {'type': 'integer', 'default': default, 'minimum': minimum, 'maximum': 50})
                    self.assertNotIn('description', properties[key])

            def _query(params_str):
                forwarded = json.loads(params_str)
                self.assertNotIn('page', forwarded)
                self.assertNotIn('page_size', forwarded)
                self.assertEqual(forwarded['project_id'], 'CTX')
                return raw

            _query.__name__ = name
            service._trace_start()
            try:
                with self.subTest(tool=name), patch.object(service, name, service._traced_tool(_query)):
                    bound = service._bind_tools_to_project([tool], 'CTX')[0]
                    result = json.loads(bound.invoke(params))
                    self.assertEqual(result['rows'], [{'id': i} for i in (range(5, 10) if name in _PAGED else range(31))])
                    if name in _PAGED:
                        self.assertEqual(result['_paging']['rows'], {'total': 31, 'page': 2, 'page_size': 5, 'has_more': True})
                    else:
                        self.assertNotIn('_paging', result)
                        self.assertNotIn('_paging_note', result)
                    self.assertEqual(result['summary'], {'count': 31})
                    self.assertEqual(service._trace_calls(True)[0]['result'], raw)
            finally:
                service._trace_stop()

    def test_pagination_validation_and_prompt_template(self):
        for name in _PAGED:
            tool = getattr(service, 'tool_' + name)
            for params in ({'page': 0}, {'page': 51}, {'page_size': 4}, {'page_size': 51}):
                with self.subTest(name=name, params=params), patch.object(tool, 'func') as execute:
                    self.assertEqual(json.loads(tool.invoke(params))['code'], 'invalid_tool_arguments')
                    execute.assert_not_called()
        self.assertEqual(ChatPromptTemplate.from_messages([('system', service.SYSTEM_PROMPT)]).input_variables, [])


def _evidence(call_id, scope=None, **fields):
    return ToolMessage(content=_json({
        'scope': scope if scope is not None else {'ring_range': [388, 487], 'record_count': 359},
        '_analysis_payload': {'summary': {'现场观测': 359}}, 'details': '详细记录' * 1000, **fields,
    }), tool_call_id=call_id, name=_NAME)


def _call(*ids):
    return AIMessage(content='', tool_calls=[{'id': key, 'name': _NAME, 'args': {}} for key in ids])


class EarlierEvidenceTests(SimpleTestCase):
    def _policy(self, soft=1, **kwargs):
        return ContextBudgetPolicy(context_tokens=65536, evidence_soft_tokens=soft, **kwargs)

    def test_oldest_first_stop_at_soft_limit_preserve_pairs_and_original(self):
        messages = [HumanMessage(content='问题'), _call('first'), _evidence('first'),
                    _call('second'), _evidence('second'), _call('latest'), _evidence('latest')]
        before = [message.model_dump() for message in messages]
        all_old = prepare_messages(messages, self._policy(), source_labels=_LABELS)
        only_first = messages.copy()
        only_first[2] = all_old[2]
        threshold = estimate_request_tokens(only_first)
        result = prepare_messages(messages, self._policy(threshold), source_labels=_LABELS)
        self.assertTrue(result[2].content.startswith(_MARKER + '现场检查：第388–487环 · 359条。要点：现场观测：359。'))
        self.assertLessEqual(len(result[2].content), 300)
        self.assertIn('用相同参数重新查询或翻页。', result[2].content)
        self.assertEqual(result[4].content, messages[4].content)
        self.assertEqual(result[6].content, messages[6].content)
        self.assertLessEqual(estimate_request_tokens(result), threshold)
        for original, copied in zip(messages, result):
            self.assertIsNot(original, copied)
            self.assertEqual(original.model_dump(exclude={'content'}), copied.model_dump(exclude={'content'}))
        self.assertEqual([message.model_dump() for message in messages], before)
        call_ids = [call['id'] for message in result if isinstance(message, AIMessage) for call in message.tool_calls]
        self.assertEqual(call_ids, [message.tool_call_id for message in result if isinstance(message, ToolMessage)])

    def test_latest_batch_errors_and_existing_summaries_are_protected(self):
        error = _evidence('error').model_copy(update={'status': 'error'})
        summary = ToolMessage(content=_MARKER + '现场检查：已有摘要', tool_call_id='summary', name=_NAME)
        messages = [_call('old', 'error', 'summary'), _evidence('old'), error, summary,
                    _call('a', 'b'), _evidence('a'), _evidence('b')]
        result = prepare_messages(messages, self._policy(), source_labels=_LABELS)
        self.assertTrue(result[1].content.startswith(_MARKER))
        for index in (2, 3, 5, 6):
            self.assertEqual(result[index].model_dump(), messages[index].model_dump())

    def test_below_soft_limit_keeps_evidence(self):
        messages = [_call('old'), _evidence('old'), _call('new'), _evidence('new')]
        result = prepare_messages(messages, self._policy(estimate_request_tokens(messages)), source_labels=_LABELS)
        self.assertEqual([m.model_dump() for m in messages], [m.model_dump() for m in result])

    def test_scope_fallback_summary_precedence_and_length(self):
        for scope, expected in (
            ({'ring_range': [1, 2], 'effective_ring_range': [3, 4], 'record_count': 0, 'observation_count': 9}, '第1–2环 · 0条'),
            ({'ring_range': [], 'effective_ring_range': [3, 4], 'observation_count': 9}, '第3–4环 · 9条'),
            ({'ring_min': 5, 'ring_max': 6, 'record_count': 7}, '第5–6环 · 7条'),
            ({}, '范围未注明'),
        ):
            old = _evidence('old', scope, _analysis_payload={}, summary={'text': '统计说明' * 200})
            result = prepare_messages([_call('old'), old, _call('new'), _evidence('new')], self._policy(), source_labels=_LABELS)
            self.assertIn(expected + '。要点：统计说明', result[1].content)
            self.assertEqual(len(result[1].content), 300)
        old = ToolMessage(content='原始文本' * 300, tool_call_id='old', additional_kwargs={'name': _NAME})
        result = prepare_messages([_call('old'), old, _call('new'), _evidence('new')], self._policy(), source_labels=_LABELS)
        self.assertIn('要点：' + old.content[:200] + '。完整结果', result[1].content)

    def test_compaction_before_summary_and_hard_budget_failure(self):
        old = _evidence('old', rows=[{'long_field_name': i, 'another_long_field': i} for i in range(500)], details='')
        messages = [_call('old'), old, _call('new'), _evidence('new')]
        result = prepare_messages(messages, self._policy(), source_labels=_LABELS)
        self.assertIn('第388–487环 · 359条', result[1].content)
        with self.assertRaises(ContextBudgetExceeded):
            prepare_messages(messages, ContextBudgetPolicy(context_tokens=1024, output_tokens=128, safety_margin_tokens=128, evidence_soft_tokens=1), source_labels=_LABELS)

    def test_soft_limit_configuration_and_invalid_values(self):
        with patch.dict(os.environ, {}, clear=True), override_settings(AI_CONTEXT_EVIDENCE_SOFT_TOKENS=12345):
            self.assertEqual(get_context_policy('deepseek').evidence_soft_tokens, 12345)
            with patch.dict(os.environ, {'AI_CONTEXT_EVIDENCE_SOFT_TOKENS': '23456'}):
                self.assertEqual(get_context_policy('deepseek').evidence_soft_tokens, 23456)
            for value in ('0', '-1', 'invalid', '2.5'):
                with patch.dict(os.environ, {'AI_CONTEXT_EVIDENCE_SOFT_TOKENS': value}):
                    with self.assertRaisesRegex(LLMProviderError, 'Invalid AI context budget configuration'):
                        get_context_policy('deepseek')
        self.assertEqual(ContextBudgetPolicy().evidence_soft_tokens, 24000)

    def test_service_passes_source_labels_through_model_bindings(self):
        guard = GuardedChatModel(ToolModel(responses=[AIMessage(content='完成')]), self._policy())
        assistant = service.ToolAssistant()
        with patch.object(service, 'get_llm_config'), patch.object(service, 'create_chat_model', return_value=guard):
            assistant._ensure_llm_runtime()
        bound = guard.bind_tools([service.tool_query_tool_inspections]).bind(stop=['END'])
        messages, _ = bound._prepare_call([_call('old'), _evidence('old'), _call('new'), _evidence('new')], {})
        self.assertTrue(messages[1].content.startswith(_MARKER + '现场检查：'))
