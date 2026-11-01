"""同步和流式共用的工具调用循环。"""

import asyncio
import logging
from contextlib import aclosing

from asgiref.sync import async_to_sync, sync_to_async
from langchain.agents.agent import ExceptionTool
from langchain.agents.format_scratchpad.tools import format_to_tool_messages
from langchain.agents.output_parsers.tools import parse_ai_message_to_tool_action
from langchain.agents.tools import InvalidTool
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.exceptions import OutputParserException


logger = logging.getLogger(__name__)
_RETRYABLE_ERRORS = ("timeout", "connection", "rate limit", "overloaded", "503", "502")


def astream_agent(model, prompt, tools, inputs, *, max_iterations=10, model_retries=2, config=None):
    """逐轮调用模型并顺序执行工具，产出文字、工具起止和最终结果事件。"""
    return _agent_events(model, prompt, tools, inputs, max_iterations, model_retries, config, in_calling_thread=False)


def _stream_reply(bound_model, messages, config):
    response = None
    for chunk in bound_model.stream(messages, config=config):
        response = chunk if response is None else response + chunk
    return response


async def _call_model(bound_model, messages, config, in_calling_thread):
    """同步入口在调用线程里用同步接口取完整回复；流式入口逐片产出。"""
    if in_calling_thread:
        yield await sync_to_async(_stream_reply, thread_sensitive=True)(bound_model, messages, config)
        return
    async with aclosing(bound_model.astream(messages, config=config)) as chunks:
        async for chunk in chunks:
            yield chunk


async def _call_tool(tool, tool_input, config, in_calling_thread):
    if in_calling_thread:
        return await sync_to_async(tool.invoke, thread_sensitive=True)(tool_input, config=config)
    return await tool.ainvoke(tool_input, config=config)


async def _agent_events(model, prompt, tools, inputs, max_iterations, model_retries, config, in_calling_thread):
    # 同步入口（in_calling_thread）的模型和工具都回到调用线程走同步接口：async_to_sync 每次用完就关掉临时事件循环，
    # 缓存的模型若用异步客户端，连接池会挂在已关闭的循环上；工具也要沿用调用方的数据库连接和事务。
    steps = []
    tools_by_name = {tool.name: tool for tool in tools}
    for iteration in range(1, max_iterations + 1):
        # 沿用消息还原函数，保证模型上下文与落库回放使用相同的工具协议。
        messages = prompt.format_messages(**inputs, agent_scratchpad=format_to_tool_messages(steps))
        bound_model = model.bind_tools(tools)
        for attempt in range(model_retries + 1):
            response = None
            emitted_text = False
            try:
                async with aclosing(_call_model(bound_model, messages, config, in_calling_thread)) as chunks:
                    async for chunk in chunks:
                        response = chunk if response is None else response + chunk
                        content = chunk.content if isinstance(chunk.content, str) else ""
                        emitted_text = emitted_text or bool(content)
                        # 工具调用的空文字片段也携带轮次，用于区分同轮调用与后续参数修复。
                        yield {"type": "model_text", "content": content, "iteration": iteration}
                break
            except Exception as error:
                retryable = any(keyword in str(error).lower() for keyword in _RETRYABLE_ERRORS)
                if emitted_text or not retryable or attempt == model_retries:
                    raise
                # 只重试尚未输出文字的这次模型调用，已完成的工具步骤保持不变。
                wait = 2 ** attempt
                logger.warning(f"模型调用可重试错误（第{attempt + 1}次），{wait}s 后重试：{error}")
                await asyncio.sleep(wait)

        try:
            parsed = parse_ai_message_to_tool_action(response)
        except OutputParserException as error:
            observation = str(error.observation) if error.send_to_llm else "Invalid or incomplete response"
            text = str(error.llm_output) if error.send_to_llm else str(error)
            # 解析错误没有合法的工具调用 ID，沿用特殊动作以保持原来的错误回放消息。
            action = AgentAction("_Exception", observation, text)
            call = {"call_id": f"_Exception-{iteration}", "name": action.tool, "args": {"query": observation}}
            yield {"type": "tool_start", **call}
            observation = await ExceptionTool().ainvoke(action.tool_input, config=config)
            steps.append((action, observation))
            yield {"type": "tool_end", **call, "observation": observation}
            continue

        if isinstance(parsed, AgentFinish):
            yield {"type": "final", "output": parsed.return_values["output"], "intermediate_steps": steps}
            return

        for action in parsed:
            arguments = action.tool_input if isinstance(action.tool_input, dict) else {"__arg1": action.tool_input}
            call = {"call_id": action.tool_call_id, "name": action.tool, "args": arguments}
            yield {"type": "tool_start", **call}
            tool = tools_by_name.get(action.tool)
            if tool is None:
                observation = await InvalidTool().ainvoke({
                    "requested_tool_name": action.tool,
                    "available_tool_names": list(tools_by_name),
                }, config=config)
            else:
                observation = await _call_tool(tool, action.tool_input, config, in_calling_thread)
            steps.append((action, observation))
            yield {"type": "tool_end", **call, "observation": observation}
            if len(parsed) == 1 and tool is not None and tool.return_direct:
                yield {"type": "final", "output": observation, "intermediate_steps": steps}
                return

    yield {"type": "final", "output": "Agent stopped due to max iterations.", "intermediate_steps": steps}


async def _ainvoke_agent(model, prompt, tools, inputs, max_iterations, model_retries, config):
    events = _agent_events(model, prompt, tools, inputs, max_iterations, model_retries, config, in_calling_thread=True)
    async with aclosing(events):
        async for event in events:
            if event["type"] == "final":
                return {"output": event["output"], "intermediate_steps": event["intermediate_steps"]}


def invoke_agent(model, prompt, tools, inputs, *, max_iterations=10, model_retries=2, config=None) -> dict:
    """同步运行同一个工具循环，返回回答和完整工具步骤。"""
    return async_to_sync(_ainvoke_agent)(model, prompt, tools, inputs, max_iterations, model_retries, config)
