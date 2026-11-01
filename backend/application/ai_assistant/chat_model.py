"""通过 OpenAI SDK 保留现有的 LangChain 消息与回调接口。"""

import asyncio
import json
import re
from typing import Any

import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.output_parsers.openai_tools import make_invalid_tool_call, parse_tool_call
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field, PrivateAttr


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
    generations = []
    for choice in data["choices"]:
        raw = choice["message"]
        additional, calls, invalid = {}, [], []
        if raw.get("function_call"):
            additional["function_call"] = raw["function_call"]
        if raw.get("tool_calls"):
            additional["tool_calls"] = raw["tool_calls"]
            for call in raw["tool_calls"]:
                try:
                    calls.append(parse_tool_call(call, return_id=True))
                except Exception as error:
                    invalid.append(make_invalid_tool_call(call, str(error)))
        message = AIMessage(
            content=raw.get("content") or "", name=raw.get("name"), id=raw.get("id"),
            additional_kwargs=additional, tool_calls=calls, invalid_tool_calls=invalid,
            usage_metadata=_usage_metadata(usage) if usage else None,
        )
        info = {"finish_reason": choice.get("finish_reason")}
        if "logprobs" in choice:
            info["logprobs"] = choice["logprobs"]
        generations.append(ChatGeneration(message=message, generation_info=info))
    if generations and hasattr(response.choices[0].message, "refusal"):
        generations[0].message.additional_kwargs["refusal"] = response.choices[0].message.refusal
    output = {
        "token_usage": usage, "model_name": data.get("model", model),
        "system_fingerprint": data.get("system_fingerprint", ""),
    }
    output.update({key: data[key] for key in ("id", "service_tier") if key in data})
    return ChatResult(generations=generations, llm_output=output)


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
        response_metadata={"token_usage": usage} if usage else {},
    )
    return ChatGenerationChunk(message=message, generation_info=info or None)


class ChatCompletionsModel(BaseChatModel):
    """经 openai SDK 调用 Chat Completions 接口的模型。"""

    model: str
    base_url: str
    api_key: str = Field(repr=False, exclude=True)
    temperature: float
    timeout: float
    max_tokens: int
    output_parameter: str = "max_tokens"
    http_client: Any = None
    http_async_client: Any = None

    _client: Any = PrivateAttr(default=None)
    _async_clients: dict = PrivateAttr(default_factory=dict)

    @property
    def _llm_type(self):
        return "chat-completions"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

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
            "messages": [_message_to_dict(message) for message in self._convert_input(input_).to_messages()],
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

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = self._get_client().chat.completions.create(
            **self._get_request_payload(messages, stop=stop, **kwargs),
        )
        return _chat_result(response, self.model)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        response = await self._get_async_client().chat.completions.create(
            **self._get_request_payload(messages, stop=stop, **kwargs),
        )
        return _chat_result(response, self.model)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        kwargs["stream"] = True
        with self._get_client().chat.completions.create(
            **self._get_request_payload(messages, stop=stop, **kwargs),
        ) as response:
            for chunk in response:
                if (generation := _generation_chunk(chunk)) is not None:
                    yield generation

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        kwargs["stream"] = True
        response = await self._get_async_client().chat.completions.create(
            **self._get_request_payload(messages, stop=stop, **kwargs),
        )
        async with response:
            async for chunk in response:
                if (generation := _generation_chunk(chunk)) is not None:
                    yield generation
