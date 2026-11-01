"""使用假模型核对工具循环、单次模型重试和取消边界。"""

import asyncio
import contextvars
import threading
from contextlib import aclosing
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, call, patch

from asgiref.sync import async_to_sync
from django.db import connection
from django.test import SimpleTestCase, TestCase
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.agents.output_parsers.tools import ToolAgentAction
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool

from application.ai_assistant.agent_loop import astream_agent, invoke_agent
from application.ai_assistant.context_budget import ContextBudgetPolicy, GuardedChatModel
from application.ai_assistant.llm_service import ToolAssistant, tool_query_tool_change_data
from application.ai_assistant.memory_service import MemorySnapshot


class _Model(Runnable):
    def __init__(self, responses):
        self.responses = responses
        self.calls, self.bindings, self.closed = [], [], []
        self.waiting = asyncio.Event()

    def bind_tools(self, tools):
        self.bindings.append(list(tools))
        return self

    def invoke(self, input, config=None, **kwargs):
        raise AssertionError("工具循环只调用 stream / astream")

    def stream(self, input, config=None, **kwargs):
        index = len(self.calls)
        self.calls.append((deepcopy(input), config))
        try:
            for item in self.responses[index]:
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.closed.append(index)

    async def astream(self, input, config=None, **kwargs):
        index = len(self.calls)
        self.calls.append((deepcopy(input), config))
        try:
            for item in self.responses[index]:
                if isinstance(item, Exception):
                    raise item
                if isinstance(item, asyncio.Event):
                    self.waiting.set()
                    await item.wait()
                else:
                    yield item
        finally:
            self.closed.append(index)


def _tool_message(*values):
    return AIMessageChunk(content="", tool_calls=[
        {"name": "lookup", "args": {"value": value}, "id": f"call-{value}"} for value in values
    ])


def _setup(responses, function=None, coroutine=None):
    model = _Model(responses)
    guard = GuardedChatModel(model, ContextBudgetPolicy())
    prompt = ChatPromptTemplate.from_messages([
        ("system", "按工具结果回答。"), MessagesPlaceholder("chat_history"),
        ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
    ])

    def lookup(value: int):
        return {"value": value}

    tool = StructuredTool.from_function(
        func=function or lookup, coroutine=coroutine, name="lookup", description="查询数值。",
    )
    return model, guard, prompt, [tool], {"input": "查询", "chat_history": []}


async def _collect(*args, **kwargs):
    async with aclosing(astream_agent(*args, **kwargs)) as events:
        return [event async for event in events]


class AgentLoopTests(SimpleTestCase):
    def test_sync_and_stream_match_reference_messages_and_evidence(self):
        responses = [[_tool_message(1)], [AIMessageChunk(content="共"), AIMessageChunk(content="1条。")]]
        model, *args = _setup(responses)
        result = invoke_agent(*args)
        streamed_model, *streamed_args = _setup(responses)
        events = async_to_sync(_collect)(*streamed_args)
        reference_model, guard, prompt, tools, inputs = _setup(responses)
        executor = AgentExecutor(agent=create_tool_calling_agent(guard, tools, prompt), tools=tools,
                                 return_intermediate_steps=True, handle_parsing_errors=True)
        reference = async_to_sync(executor.ainvoke)(inputs)
        self.assertEqual(result, {key: reference[key] for key in ("output", "intermediate_steps")})
        self.assertEqual(result, {key: events[-1][key] for key in result})
        for other in (streamed_model, reference_model):
            self.assertEqual([item[0] for item in model.calls], [item[0] for item in other.calls])
        action, observation = result["intermediate_steps"][0]
        self.assertIsInstance(action, ToolAgentAction)
        self.assertEqual((action.tool, action.tool_input, action.tool_call_id), ("lookup", {"value": 1}, "call-1"))
        self.assertEqual(action.message_log, [responses[0][0]])
        self.assertEqual(observation, {"value": 1})
        self.assertEqual(len(model.bindings), 2)
        self.assertEqual([e["content"] for e in events if e["type"] == "model_text"], ["", "共", "1条。"])
        self.assertEqual(events[-1]["type"], "final")

    async def test_multiple_tools_execute_in_order_with_complete_message_log(self):
        executed = []

        async def lookup(value: int):
            executed.append(value)
            return {"value": value}

        model, *args = _setup([[_tool_message(1, 2)], [AIMessage(content="完成")]], coroutine=lookup)
        tool_events = []
        async with aclosing(astream_agent(*args)) as events:
            async for event in events:
                if event["type"] == "tool_start":
                    self.assertEqual(executed, [] if event["call_id"] == "call-1" else [1])
                if event["type"] in ("tool_start", "tool_end"):
                    tool_events.append((event["type"], event["call_id"]))
                final = event
        self.assertEqual(tool_events, [(kind, f"call-{value}") for value in (1, 2)
                                       for kind in ("tool_start", "tool_end")])
        self.assertEqual(executed, [1, 2])
        self.assertEqual([action.tool_call_id for action, _ in final["intermediate_steps"]], ["call-1", "call-2"])
        self.assertEqual(len([m for m in model.calls[1][0] if isinstance(m, AIMessage)]), 1)
        self.assertEqual([m.tool_call_id for m in model.calls[1][0] if isinstance(m, ToolMessage)], ["call-1", "call-2"])

    async def test_retry_discards_partial_call_and_never_repeats_completed_tool(self):
        model, *args = _setup([
            [_tool_message(1)],
            [AIMessageChunk(content="", tool_call_chunks=[{
                "name": "lookup", "args": '{"value":', "id": "discard", "index": 0,
            }]), RuntimeError("connection reset")],
            [AIMessage(content="完成")],
        ])
        with patch('application.ai_assistant.agent_loop.asyncio.sleep', new_callable=AsyncMock) as sleep:
            events = await _collect(*args)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(model.calls[1][0], model.calls[2][0])
        self.assertEqual(len(events[-1]["intermediate_steps"]), 1)
        self.assertEqual([e["call_id"] for e in events if e["type"] == "tool_end"], ["call-1"])
        self.assertEqual(events[-1]["output"], "完成")
        sleep.assert_awaited_once_with(1)

    async def test_retry_limit_backoff_and_nonretryable_error(self):
        for error, attempts in (("timeout", 3), ("rate limit", 3), ("overloaded 503", 3),
                                ("502", 3), ("invalid request", 1)):
            with self.subTest(error=error):
                model, *args = _setup([[RuntimeError(error)]] * attempts)
                with patch('application.ai_assistant.agent_loop.asyncio.sleep', new_callable=AsyncMock) as sleep:
                    with self.assertRaisesRegex(RuntimeError, error):
                        await _collect(*args)
                self.assertEqual(len(model.calls), attempts)
                self.assertEqual(sleep.await_args_list, [call(1), call(2)] if attempts == 3 else [])
        model, *args = _setup([[RuntimeError("timeout")]])
        with self.assertRaisesRegex(RuntimeError, 'timeout'):
            await _collect(*args, model_retries=0)
        self.assertEqual(len(model.calls), 1)

    async def test_text_already_emitted_disables_retry(self):
        model, *args = _setup([[AIMessageChunk(content="部分回答"), RuntimeError("timeout")]])
        received = []
        with patch('application.ai_assistant.agent_loop.asyncio.sleep', new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                async for event in astream_agent(*args):
                    received.append(event)
        self.assertEqual(received, [{"type": "model_text", "content": "部分回答", "iteration": 1}])
        self.assertEqual(len(model.calls), 1)
        sleep.assert_not_awaited()

    async def test_tool_error_is_not_retried(self):
        executed = []

        def lookup(value: int):
            executed.append(value)
            raise RuntimeError("database connection timeout")

        model, *args = _setup([[_tool_message(1, 2)]], function=lookup)
        with patch('application.ai_assistant.agent_loop.asyncio.sleep', new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(RuntimeError, 'database connection timeout'):
                await _collect(*args)
        self.assertEqual(executed, [1])
        self.assertEqual(len(model.calls), 1)
        sleep.assert_not_awaited()

    async def test_unknown_tool_observation_matches_reference(self):
        model, *args = _setup([[AIMessage(content="", tool_calls=[{
            "name": "missing", "args": {}, "id": "missing-1",
        }])], [AIMessage(content="完成")]])
        events = await _collect(*args)
        action, observation = events[-1]["intermediate_steps"][0]
        self.assertEqual(observation, "missing is not a valid tool, try one of [lookup].")
        self.assertIsInstance(action, ToolAgentAction)
        self.assertEqual(action.tool_call_id, "missing-1")
        self.assertEqual(model.calls[1][0][-1].content, observation)
        self.assertEqual(model.calls[1][0][-1].tool_call_id, "missing-1")

        # 未选入当前工具组的注册工具仍属于未知工具，不能误作真实查询失败事件。
        model, guard, prompt, _, _ = _setup([[AIMessage(content="", tool_calls=[{
            "name": "tool_query_stratum_data", "args": {}, "id": "unavailable",
        }])], [AIMessage(content="无查询结果")]])
        assistant = ToolAssistant()
        assistant._llm, assistant._prompt = guard, prompt
        assistant._get_tools_for_query = Mock(return_value=[tool_query_tool_change_data])
        assistant._load_memory = Mock(return_value=MemorySnapshot(scope_key="user:1", backend="legacy"))
        assistant._store_turn_and_summarize = Mock()
        events = [event async for event in assistant.chat_stream(
            "查询地层", {"user_id": "1", "project_id": "P", "route_mode": "agent"},
        )]
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("未取得完整的工具查询结果", events[-1]["content"])
        assistant._store_turn_and_summarize.assert_not_called()

    async def test_parser_error_recovery_matches_reference_messages(self):
        malformed = AIMessage(content="", additional_kwargs={"tool_calls": [{
            "id": "bad", "type": "function", "function": {"name": "lookup", "arguments": "invalid JSON"},
        }]})
        responses = [[malformed], [AIMessage(content="已修复")]]
        model, *args = _setup(responses)
        events = await _collect(*args)
        reference_model, guard, prompt, tools, inputs = _setup(responses)
        executor = AgentExecutor(agent=create_tool_calling_agent(guard, tools, prompt), tools=tools,
                                 return_intermediate_steps=True, handle_parsing_errors=True)
        reference = await executor.ainvoke(inputs)
        self.assertEqual(events[-1]["intermediate_steps"], reference["intermediate_steps"])
        self.assertEqual(events[-1]["output"], reference["output"])
        self.assertEqual(model.calls[1][0], reference_model.calls[1][0])
        action, observation = events[-1]["intermediate_steps"][0]
        self.assertEqual(action.tool, "_Exception")
        self.assertEqual(observation, "Invalid or incomplete response")

    async def test_iteration_limit_retains_steps_and_recognizable_output(self):
        for limit in (0, 2, 10):
            with self.subTest(limit=limit):
                model, *args = _setup([[_tool_message(value)] for value in range(limit)])
                events = await _collect(*args, max_iterations=limit)
                self.assertEqual(events[-1]["output"], "Agent stopped due to max iterations.")
                self.assertEqual(len(events[-1]["intermediate_steps"]), limit)
                self.assertEqual(len(model.calls), limit)

    async def test_close_at_model_or_tool_boundary_stops_further_work(self):
        for boundary in ("model_text", "tool_start", "tool_end"):
            with self.subTest(boundary=boundary):
                executed = []

                def lookup(value: int):
                    executed.append(value)
                    return value

                model, *args = _setup([[_tool_message(1, 2)], [AIMessage(content="不应出现")]], function=lookup)
                events = astream_agent(*args)
                while (await anext(events))["type"] != boundary:
                    pass
                await events.aclose()
                self.assertEqual(executed, [1] if boundary == "tool_end" else [])
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(model.closed, [0])

    async def test_cancellation_interrupts_model_tool_and_retry_wait(self):
        for stage in ("model", "tool", "retry"):
            with self.subTest(stage=stage):
                waiting = asyncio.Event()
                executed = []

                async def block(*args):
                    waiting.set()
                    await asyncio.Event().wait()

                async def lookup(value: int):
                    executed.append(value)
                    await block()

                responses = {"model": [[asyncio.Event()]], "tool": [[_tool_message(1, 2)]],
                             "retry": [[RuntimeError("timeout")]]}
                model, *args = _setup(responses[stage], coroutine=lookup)
                with patch('application.ai_assistant.agent_loop.asyncio.sleep', side_effect=block):
                    task = asyncio.create_task(_collect(*args))
                    await asyncio.wait_for((model.waiting if stage == "model" else waiting).wait(), 1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(model.closed, [0])
                self.assertEqual(executed, [1] if stage == "tool" else [])

    async def test_config_is_passed_unchanged_to_guarded_model_and_tool(self):
        model, *args = _setup([[_tool_message(1)], [AIMessage(content="完成")]])
        config = {"tags": ["test"], "metadata": {"request": 1}, "callbacks": []}
        original = StructuredTool.ainvoke
        tool_configs = []

        async def invoke(tool, input, config=None, **kwargs):
            tool_configs.append(config)
            return await original(tool, input, config=config, **kwargs)

        with patch.object(StructuredTool, 'ainvoke', invoke):
            await _collect(*args, config=config)
        self.assertEqual(len(tool_configs), 1)
        self.assertIs(tool_configs[0], config)
        self.assertTrue(all(item[1] is config for item in model.calls))
        self.assertEqual(config, {"tags": ["test"], "metadata": {"request": 1}, "callbacks": []})


class _SyncOnlyModel(_Model):
    async def astream(self, input, config=None, **kwargs):
        raise AssertionError("同步入口不能用异步客户端")
        yield


_REQUEST = contextvars.ContextVar("agent_loop_test_request", default=None)


class SyncEntryTests(TestCase):
    """同步入口：模型和工具回到调用线程走同步接口，沿用调用方的数据库连接、事务和上下文变量。"""

    def test_same_model_serves_consecutive_sync_calls_without_async_client(self):
        model = _SyncOnlyModel([[_tool_message(1)], [AIMessage(content="第一次")],
                                [_tool_message(2)], [AIMessage(content="第二次")]])
        _, guard, prompt, tools, inputs = _setup([])
        guard.model = model
        first = invoke_agent(guard, prompt, tools, inputs)
        second = invoke_agent(guard, prompt, tools, inputs)
        self.assertEqual((first["output"], second["output"]), ("第一次", "第二次"))
        self.assertEqual(len(model.calls), 4)

    def test_tools_run_in_calling_thread_inside_its_transaction(self):
        seen = []

        def lookup(value: int):
            seen.append((threading.get_ident(), connection.in_atomic_block, _REQUEST.get()))
            return {"value": value}

        model, *args = _setup([[_tool_message(1)], [AIMessage(content="完成")]], function=lookup)
        token = _REQUEST.set("项目 P")
        try:
            result = invoke_agent(*args)
        finally:
            _REQUEST.reset(token)
        self.assertEqual(result["output"], "完成")
        # TestCase 把每个用例包在事务里：工具若换了线程（换了数据库连接）就不在这个事务里
        self.assertEqual(seen, [(threading.get_ident(), True, "项目 P")])
