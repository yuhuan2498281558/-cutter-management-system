"""通过 OpenAI SDK 调用模型并保留消息和用量协议。"""

import asyncio
import json
import re
from typing import Any
from dataclasses import dataclass, field
from functools import partial
from threading import Lock
from uuid import uuid4

import openai
from .agent_loop import OutputParserException
from .messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage, _add_usage, _call
from .tooling import openai_tool_schema


class UsageCollector:
    """按实际模型名累加普通和嵌套 token 用量。"""
    def __init__(self):
        self.usage_metadata, self._lock = {}, Lock()

    def record(self, message):
        """只记录同时具有模型名和用量的完整回复。"""
        name = message.response_metadata.get("model_name")
        if name and message.usage_metadata:
            with self._lock:
                self.usage_metadata[name] = _add_usage(self.usage_metadata.get(name), message.usage_metadata)


@dataclass
class _BoundModel:
    bound: Any
    kwargs: dict

    def __getattr__(self, name):
        return partial(getattr(self.bound, name), **self.kwargs)


def _message_to_dict(message):
    result = {"content": message.content}
    if (name := message.name or message.additional_kwargs.get("name")) is not None:
        result["name"] = name
    if isinstance(message, SystemMessage):
        result["role"] = message.additional_kwargs.get("__openai_role__", "system")
    elif isinstance(message, HumanMessage):
        result["role"] = "user"
    elif isinstance(message, ToolMessage):
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}
    elif isinstance(message, AIMessage):
        result["role"] = "assistant"
        if message.tool_calls or message.invalid_tool_calls:
            result["tool_calls"] = [
                {"type": "function", "id": call["id"], "function": {
                    "name": call["name"], "arguments": json.dumps(call["args"]),
                }} for call in message.tool_calls
            ] + [
                {"type": "function", "id": call["id"], "function": {
                    "name": call["name"], "arguments": call["args"],
                }} for call in message.invalid_tool_calls
            ]
        elif "tool_calls" in message.additional_kwargs:
            result["tool_calls"] = [
                {key: value for key, value in call.items() if key in {"id", "type", "function"}}
                for call in message.additional_kwargs["tool_calls"]
            ]
        elif "function_call" in message.additional_kwargs:
            result["function_call"] = message.additional_kwargs["function_call"]
        if "tool_calls" in result or "function_call" in result:
            result["content"] = result["content"] or None
    else:
        raise TypeError(f"Got unknown type {message}")
    return result


def _usage_metadata(usage):
    input_tokens = usage.get("prompt_tokens") or 0
    output_tokens = usage.get("completion_tokens") or 0
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("total_tokens") or input_tokens + output_tokens,
        "input_token_details": {
            key: prompt_details[source] for key, source in
            (("audio", "audio_tokens"), ("cache_read", "cached_tokens"))
            if prompt_details.get(source) is not None
        },
        "output_token_details": {
            key: completion_details[source] for key, source in
            (("audio", "audio_tokens"), ("reasoning", "reasoning_tokens"))
            if completion_details.get(source) is not None
        },
    }


def _chat_result(response, model):
    data = response.model_dump()
    if data.get("error"):
        raise ValueError(data["error"])
    usage = data.get("usage")
    messages = []
    for choice in data["choices"]:
        raw = choice["message"]
        additional, calls, invalid = {}, [], []
        if raw.get("function_call"):
            additional["function_call"] = raw["function_call"]
        if raw.get("tool_calls"):
            additional["tool_calls"] = raw["tool_calls"]
            for call in raw["tool_calls"]:
                try:
                    try:
                        args = json.loads(call["function"]["arguments"], strict=False)
                    except json.JSONDecodeError as error:
                        raise OutputParserException(
                            f"Function {call['function']['name']} arguments:\n\n"
                            f"{call['function']['arguments']}\n\nare not valid JSON. Received JSONDecodeError {error}"
                        ) from error
                    calls.append(_call("tool_call", name=call["function"]["name"] or "", args=args or {}, id=call.get("id")))
                except Exception as error:
                    invalid.append(_call("invalid_tool_call", name=call["function"]["name"],
                                         args=call["function"]["arguments"], id=call.get("id"), error=str(error)))
        message = AIMessage(
            content=raw.get("content") or "", name=raw.get("name"), id=raw.get("id"),
            additional_kwargs=additional, tool_calls=calls, invalid_tool_calls=invalid,
            usage_metadata=_usage_metadata(usage) if usage else None,
        )
        info = {"finish_reason": choice.get("finish_reason")}
        if "logprobs" in choice:
            info["logprobs"] = choice["logprobs"]
        message.response_metadata = info
        messages.append(message)
    if messages and hasattr(response.choices[0].message, "refusal"):
        messages[0].additional_kwargs["refusal"] = response.choices[0].message.refusal
    output = {
        "token_usage": usage, "model_name": data.get("model", model),
        "system_fingerprint": data.get("system_fingerprint", ""),
    }
    output.update({key: data[key] for key in ("id", "service_tier") if key in data})
    if len(messages) == 1:
        messages[0].response_metadata = {**output, **messages[0].response_metadata}
    return messages[0]


def _generation_chunk(response):
    data = response.model_dump()
    usage = data.get("usage")
    choices = data.get("choices") or []
    info, additional, calls = {}, {}, []
    delta = {}
    if choices:
        choice = choices[0]
        delta = choice["delta"]
        if delta is None:
            return None
        if raw_calls := delta.get("tool_calls"):
            additional["tool_calls"] = raw_calls
            calls = [
                {"index": call["index"], "id": call.get("id"),
                 "name": call["function"].get("name"), "args": call["function"].get("arguments")}
                for call in raw_calls
            ]
        if function_call := delta.get("function_call"):
            additional["function_call"] = {**function_call, "name": function_call.get("name") or ""}
        if finish := choice.get("finish_reason"):
            info["finish_reason"] = finish
            for source, key in (("model", "model_name"), ("system_fingerprint", "system_fingerprint"),
                                ("service_tier", "service_tier")):
                if data.get(source):
                    info[key] = data[source]
        if choice.get("logprobs"):
            info["logprobs"] = choice["logprobs"]
    message = AIMessageChunk(
        content=delta.get("content") or "", id=delta.get("id"),
        additional_kwargs=additional, tool_call_chunks=calls,
        usage_metadata=_usage_metadata(usage) if usage else None,
        response_metadata={**info, **({"token_usage": usage} if usage else {})},
    )
    return message


@dataclass
class ChatCompletionsModel:
    """经 openai SDK 调用 Chat Completions 接口的模型。"""

    model: str
    base_url: str
    api_key: str = field(repr=False)
    temperature: float
    timeout: float
    max_tokens: int
    output_parameter: str = "max_tokens"
    http_client: Any = None
    http_async_client: Any = None

    _client: Any = field(default=None, init=False, repr=False)
    _async_clients: dict = field(default_factory=dict, init=False, repr=False)

    def bind_tools(self, tools, **kwargs):
        """绑定工具 schema，复用当前模型客户端。"""
        return _BoundModel(self, {"tools": [openai_tool_schema(tool) for tool in tools], **kwargs})

    def _get_client(self):
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout,
                http_client=self.http_client,
            )
        return self._client

    def _get_async_client(self):
        # async_to_sync 会关闭临时事件循环，连接池不能跨循环复用；客户端引用着自己的循环，
        # 弱引用回收不掉，所以在这里丢掉已关闭循环的客户端。
        loop = asyncio.get_running_loop()
        for closed in [item for item in self._async_clients if item.is_closed()]:
            del self._async_clients[closed]
        if loop not in self._async_clients:
            self._async_clients[loop] = openai.AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout,
                http_client=self.http_async_client,
            )
        return self._async_clients[loop]

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        cap = kwargs.pop("max_tokens", kwargs.pop("max_completion_tokens", self.max_tokens))
        payload = {
            "model": self.model, "temperature": self.temperature, "stream": False,
            **kwargs, self.output_parameter: cap,
            "messages": [_message_to_dict(message) for message in
                         ([HumanMessage(input_)] if isinstance(input_, str) else input_)],
        }
        if stop is not None:
            payload["stop"] = stop
        if payload["stream"]:
            payload["stream_options"] = {"include_usage": True}
        if re.match(r"^o\d", self.model):
            for message in payload["messages"]:
                if message["role"] == "system":
                    message["role"] = "developer"
        return payload

    def _record(self, message, config):
        if collector := (config or {}).get("usage"):
            collector.record(message)
        return message

    def invoke(self, input, config=None, *, stop=None, **kwargs):
        """同步请求完整回复并记录用量。"""
        response = self._get_client().chat.completions.create(
            **self._get_request_payload(input, stop=stop, **kwargs),
        )
        message = _chat_result(response, self.model)
        message.id = message.id or f"run--{(config or {}).get('run_id') or uuid4()}-0"
        return self._record(message, config)

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        """异步请求完整回复并记录用量。"""
        response = await self._get_async_client().chat.completions.create(
            **self._get_request_payload(input, stop=stop, **kwargs),
        )
        message = _chat_result(response, self.model)
        message.id = message.id or f"run--{(config or {}).get('run_id') or uuid4()}-0"
        return self._record(message, config)

    def stream(self, input, config=None, *, stop=None, **kwargs):
        """同步逐片输出，流结束后记录合并用量。"""
        kwargs["stream"] = True
        run_id, combined = f"run--{(config or {}).get('run_id') or uuid4()}", None
        with self._get_client().chat.completions.create(
            **self._get_request_payload(input, stop=stop, **kwargs),
        ) as response:
            for chunk in response:
                if (message := _generation_chunk(chunk)) is not None:
                    message.id = message.id or run_id
                    combined = message if combined is None else combined + message
                    yield message
        if combined is None:
            raise ValueError("No generation chunks were returned")
        self._record(combined, config)

    async def astream(self, input, config=None, *, stop=None, **kwargs):
        """异步逐片输出，流结束后记录合并用量。"""
        kwargs["stream"] = True
        run_id, combined = f"run--{(config or {}).get('run_id') or uuid4()}", None
        response = await self._get_async_client().chat.completions.create(
            **self._get_request_payload(input, stop=stop, **kwargs),
        )
        async with response:
            async for chunk in response:
                if (message := _generation_chunk(chunk)) is not None:
                    message.id = message.id or run_id
                    combined = message if combined is None else combined + message
                    yield message
        if combined is None:
            raise ValueError("No generation chunks were returned")
        self._record(combined, config)
