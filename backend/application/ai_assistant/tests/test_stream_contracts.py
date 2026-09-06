import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from application.ai_assistant import views
from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot


class StreamContractTests(SimpleTestCase):
    def make_assistant(self, events=()):
        assistant = ToolAssistant()
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._resolve_memory_slots = Mock(return_value={})
        assistant._direct_route = Mock(return_value=None)
        assistant._needs_tool_call = Mock(return_value=True)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)

        async def stream(*args, **kwargs):
            for event in events:
                yield event

        assistant._get_executor_for_query = Mock(return_value=SimpleNamespace(astream_events=stream))
        return assistant

    async def collect(self, assistant):
        return [event async for event in assistant.chat_stream(
            "查询换刀记录", {"user_id": 1, "project_id": "TEST", "route_mode": "agent"},
        )]

    async def test_agent_without_tool_evidence_is_not_saved_as_success(self):
        assistant = self.make_assistant([
            {"event": "on_chain_start", "run_id": "root", "parent_ids": [], "data": {}},
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="编造的统计")}},
            {"event": "on_chain_end", "run_id": "root", "data": {"output": {"output": "编造的统计", "intermediate_steps": []}}},
        ])
        events = await self.collect(assistant)
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("done", [item["type"] for item in events])
        assistant._store_turn_and_summarize.assert_not_called()

    async def test_agent_stores_final_output_and_corrects_intermediate_text(self):
        observation = json.dumps({"total_records": 3})
        assistant = self.make_assistant([
            {"event": "on_chain_start", "run_id": "root", "parent_ids": [], "data": {}},
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="先查数据")}},
            {"event": "on_tool_end", "name": "tool_query_tool_change_data", "data": {"output": observation}},
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="再检查一下。")}},
            {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="共3条。")}},
            {"event": "on_chain_end", "run_id": "root", "data": {"output": {"output": "共3条。", "intermediate_steps": [(None, observation)]}}},
        ])
        events = await self.collect(assistant)
        self.assertEqual(events[-1]["type"], "done")
        self.assertNotIn("先查数据", "".join(item.get("content", "") for item in events))
        self.assertIn({"type": "answer", "content": "共3条。"}, events)
        self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], "共3条。")

    async def test_tool_failure_cannot_become_successful_answer(self):
        observation = json.dumps({"error": "query failed"})
        assistant = self.make_assistant([
            {"event": "on_chain_start", "run_id": "root", "parent_ids": [], "data": {}},
            {"event": "on_tool_end", "name": "tool_query_tool_change_data", "data": {"output": observation}},
            {"event": "on_chain_end", "run_id": "root", "data": {"output": {"output": "没有数据", "intermediate_steps": [(None, observation)]}}},
        ])
        events = await self.collect(assistant)
        self.assertEqual(events[-1]["type"], "error")
        assistant._store_turn_and_summarize.assert_not_called()

    async def test_http_stream_is_async_and_delivers_before_producer_finishes(self):
        release = asyncio.Event()
        closed = []

        async def tokens(*args):
            try:
                yield {"type": "chunk", "content": "first"}
                await release.wait()
                yield {"type": "done"}
            finally:
                closed.append(True)

        assistant = SimpleNamespace(chat_stream=tokens, llm_runtime_ready=False, agent_runtime_ready=False)
        request = RequestFactory().post("/api/ai/chat/stream/", data={"query": "hello"}, content_type="application/json")
        user = SimpleNamespace(id=1, username="test")
        with patch.object(views, "_auth_user", return_value=user), patch.object(views, "_resolve_request_project_id", return_value=""), patch.object(views, "get_assistant", return_value=assistant):
            response = await views.chat_stream(request)
            self.assertTrue(response.is_async)
            iterator = response.streaming_content
            self.assertIn(b"connected", await asyncio.wait_for(anext(iterator), 1))
            self.assertIn(b"first", await asyncio.wait_for(anext(iterator), 1))
            release.set()
            self.assertIn(b"done", await asyncio.wait_for(anext(iterator), 1))
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)
        self.assertEqual(closed, [True])

    def test_health_does_not_invoke_model(self):
        with patch.object(views, "get_assistant") as get_assistant:
            response = views.health_check(RequestFactory().get("/api/ai/health/"))
        self.assertEqual(response.status_code, 200)
        get_assistant.assert_not_called()

    def test_no_openings_has_explicit_no_data_answer(self):
        assistant = self.make_assistant()
        with patch.object(assistant, "_recent_ring_range", return_value=[]):
            answer = assistant._format_recent_abnormal_wear_cause_answer("近期异常磨损原因", {"project_id": "TEST"})
        self.assertIn("未找到", answer)

    async def test_request_body_must_be_object(self):
        request = RequestFactory().post("/api/ai/chat/stream/", data='[]', content_type="application/json")
        with patch.object(views, "_auth_user", return_value=SimpleNamespace(id=1, username="test")):
            response = await views.chat_stream(request)
        self.assertEqual(response.status_code, 400)

    async def test_actual_langchain_executor_preserves_tool_evidence_and_final_answer(self):
        class ToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        assistant = ToolAssistant()
        assistant._llm = ToolModel(responses=[
            AIMessage(content='', tool_calls=[{'name': 'tool_query_tool_change_data', 'args': {}, 'id': 'call-1'}]),
            AIMessage(content='实际查询到3条记录。'),
        ])
        snapshot = MemorySnapshot(scope_key='user:1', backend='legacy')
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        with patch('application.ai_assistant.llm_service.query_tool_change_data', return_value=json.dumps({'total_records': 3})) as query:
            events = await self.collect(assistant)
        self.assertEqual(events[-1]['type'], 'done', events)
        self.assertEqual(json.loads(query.call_args.args[0])['project_id'], 'TEST')
        self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], '实际查询到3条记录。')

    async def test_close_rule_stream_before_completion_does_not_save_turn(self):
        assistant = self.make_assistant()
        assistant._direct_route.return_value = {'type': 'analysis', 'rule_branch': 'test', 'answer': '规则回答'}
        events = assistant.chat_stream('查询换刀记录', {'user_id': 1, 'project_id': 'TEST', 'route_mode': 'rule'})
        self.assertEqual((await anext(events))['type'], 'meta')
        self.assertEqual((await anext(events))['type'], 'chunk')
        await events.aclose()
        assistant._store_turn_and_summarize.assert_not_called()

    async def test_missing_http_project_never_runs_data_tools(self):
        assistant = self.make_assistant()
        events = [event async for event in assistant.chat_stream('查询换刀记录', {'user_id': 1, 'require_project': True})]
        self.assertEqual(events[-1]['type'], 'error')
        assistant._get_executor_for_query.assert_not_called()
        assistant._direct_route.assert_not_called()

    def test_cleared_slots_are_not_restored_from_snapshot(self):
        assistant = self.make_assistant()
        snapshot = MemorySnapshot(scope_key='user:1', slots={'ring_range': [100, 200]})
        self.assertEqual(assistant._memory_messages(snapshot, {'memory_slots': {}}), [])

    def test_background_summary_does_not_hold_up_saved_answer(self):
        assistant = self.make_assistant()
        snapshot = MemorySnapshot(scope_key='user:1', backend='django')
        assistant._store_turn = Mock(return_value=snapshot)
        assistant.memory.summary_due = Mock(return_value=True)
        assistant._summarize_memory = Mock()
        with patch('application.ai_assistant.llm_service.schedule_summary') as schedule:
            result = ToolAssistant._store_turn_and_summarize(assistant, '1', 'query', 'answer', {})
        self.assertIs(result, snapshot)
        schedule.assert_called_once()
        assistant._summarize_memory.assert_not_called()

    def test_sync_agent_still_requires_evidence_after_retry(self):
        assistant = self.make_assistant()
        assistant._invoke_with_retry = Mock(return_value={'output': '没有查询依据的统计', 'intermediate_steps': []})
        result = assistant.chat('查询换刀记录', {'user_id': 1, 'project_id': 'TEST', 'route_mode': 'agent'})
        self.assertFalse(result['success'])
        self.assertEqual(assistant._invoke_with_retry.call_count, 2)
        assistant._store_turn_and_summarize.assert_not_called()

    def test_empty_answer_is_not_persisted(self):
        assistant = self.make_assistant()
        with patch.object(assistant.memory, 'append_turn') as append:
            with self.assertRaisesRegex(RuntimeError, '完整回答'):
                assistant._store_turn('1', 'question', '   ')
        append.assert_not_called()

    def test_opening_formatter_distinguishes_missing_wear_and_count_sources(self):
        assistant = self.make_assistant()
        answer = assistant._format_opening_answer(json.dumps({
            'total_openings': 1,
            'recent_records': [{'ring_no': '100', 'tool_change_total': 0, 'tool_change_replaced': 0,
                                'replacement_rate': None, 'abnormal_rate': None, 'count_source': 'detail_draft',
                                'detail_record_count': 122, 'detail_checked_count': 0, 'detail_replaced_count': 0}],
        }))
        self.assertNotIn('None', answer)
        self.assertIn('现场明细（未确认）', answer)
        self.assertIn('暂无已分类磨损记录', answer)

    async def test_cancellation_reaches_agent_generator_without_persisting(self):
        waiting = asyncio.Event()
        closed = []

        async def stalled(*args, **kwargs):
            try:
                yield {'event': 'on_chain_start', 'run_id': 'root', 'parent_ids': [], 'data': {}}
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.append(True)

        assistant = self.make_assistant()
        assistant._get_executor_for_query.return_value = SimpleNamespace(astream_events=stalled)
        consumer = asyncio.create_task(self.collect(assistant))
        await asyncio.wait_for(waiting.wait(), 1)
        consumer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await consumer
        self.assertEqual(closed, [True])
        assistant._store_turn_and_summarize.assert_not_called()

    def test_opening_scope_does_not_claim_unsupported_tool_filters(self):
        assistant = self.make_assistant()
        params = assistant._opening_params('滚刀最近3次开仓情况', {
            'project_id': 'TEST', 'memory_slots': {'tool_type': 'DISC', 'cutter_position_no': 'S1L'},
        })
        self.assertIsNone(params['tool_type'])
        self.assertIsNone(params['cutter_position_no'])
        self.assertEqual(params['project_id'], 'TEST')
        self.assertNotIn('刀具类型', assistant._prepend_query_scope('整仓记录', params))

    def test_inferred_lifecycle_does_not_display_none_as_lifetime(self):
        assistant = self.make_assistant()
        answer = assistant._format_tool_performance_answer(json.dumps({'tools': [{
            'tool_number': '100-S1L-01', 'status': '已拆下', 'service_rings': None,
            'install_ring_no': 100, 'removal_ring_no': 200, 'removal_inferred': True,
        }]}))
        self.assertNotIn('None 环', answer)
        self.assertIn('暂不给出数值', answer)

    def test_unknown_lifecycle_is_not_formatted_as_installed(self):
        assistant = self.make_assistant()
        answer = assistant._format_tool_performance_answer(json.dumps({'tools': [{
            'tool_number': '100-S1L-01', 'status': '状态待核实', 'install_ring_no': 100,
        }]}))
        self.assertIn('当前状态：待核实', answer)
        self.assertNotIn('当前状态：在役', answer)

    async def test_keyword_free_data_intents_also_require_project(self):
        for query in ('推荐合适的滚刀', '487-S14R-01寿命', '检查一把刀多久', 'torque'):
            with self.subTest(query=query):
                assistant = self.make_assistant()
                events = [event async for event in assistant.chat_stream(query, {'user_id': 1, 'require_project': True})]
                self.assertEqual(events[-1]['type'], 'error')
                assistant._direct_route.assert_not_called()
                assistant._get_executor_for_query.assert_not_called()

    def test_agent_iteration_stop_is_not_a_successful_answer(self):
        assistant = self.make_assistant()
        for placeholder in ('Agent stopped due to max iterations.', 'Agent stopped due to iteration limit or time limit.'):
            with self.subTest(placeholder=placeholder):
                with self.assertRaisesRegex(RuntimeError, '执行上限'):
                    assistant._validated_agent_answer({
                        'output': placeholder, 'intermediate_steps': [(None, {'total_records': 1})],
                    })
