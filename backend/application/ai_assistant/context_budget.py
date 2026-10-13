"""Guard every model call without changing execution evidence or callbacks.

The configured window is an operational limit, not a discovered model capacity.
Counts are estimates; the reserve and margin reduce, but cannot rule out, a
provider tokenizer exceeding its actual window. No evidence is silently dropped.
"""

from dataclasses import dataclass
from contextlib import aclosing, closing
from copy import deepcopy
import json

from langchain_core.messages import (
    AIMessage, HumanMessage, ToolMessage, convert_to_messages, convert_to_openai_messages,
)
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable
from langchain_core.runnables.base import RunnableBinding
from langchain_core.utils.function_calling import convert_to_openai_tool

from .context_compaction import compact_tool_content
from .token_estimation import estimate_tokens


class ContextBudgetExceeded(ValueError):
    def __init__(self, estimated_tokens, input_budget):
        self.estimated_tokens = estimated_tokens
        self.input_budget = input_budget
        super().__init__(
            f"本轮上下文超过配置预算（估算 {estimated_tokens}，输入预算 {input_budget}）。"
            "请缩小查询范围、增大统计分段或拆分问题后重试；本次未生成完整回答。"
        )


class OutputLimitExceeded(ValueError):
    """A provider explicitly stopped on its length cap, not a completed answer."""


def _check_completion(message):
    metadata = getattr(message, "response_metadata", {}) or {}
    if metadata.get("finish_reason") == "length" or metadata.get("done_reason") == "length":
        raise OutputLimitExceeded("本次回答达到输出上限，未生成完整回答。请缩小范围或拆分问题后重试。")
    return message


@dataclass(frozen=True)
class ContextBudgetPolicy:
    context_tokens: int = 16384
    output_tokens: int = 2048
    safety_margin_tokens: int = 1024
    compaction_min_tokens: int = 1000
    tool_protocol_tokens: int = 1024

    def __post_init__(self):
        for name in ("context_tokens", "output_tokens", "safety_margin_tokens", "compaction_min_tokens", "tool_protocol_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.input_budget <= 0:
            raise ValueError("Context budget must exceed output reserve plus safety margin")

    @property
    def input_budget(self):
        return self.context_tokens - self.output_tokens - self.safety_margin_tokens


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def estimate_request_tokens(messages, request_options=None, tool_protocol_tokens=1024):
    """Estimate text components once, without tokenizing transport escaping.

    This is still a heuristic, not a provider tokenizer. Schemas are counted
    even for tool_choice=none: providers differ in whether they inject them.
    Unknown message types retain the conservative serialized fallback.
    """
    options = request_options or {}
    count = 8 * len(messages) + 16
    # Provider tool templates are not represented by the schema JSON alone.
    # This is an explicit engineering reserve, not a fitted token multiplier.
    if options.get("tools") or options.get("functions"):
        count += tool_protocol_tokens
    for message in messages:
        if message.additional_kwargs.get("audio"):
            raise ValueError("上下文预算目前仅支持文本消息。")
        try:
            payload = convert_to_openai_messages(message, text_format="block")
        except (TypeError, ValueError):
            count += estimate_tokens(_json(message.model_dump(
                exclude={"response_metadata", "usage_metadata", "artifact"},
            )))
            continue
        # The SDK prefers parsed calls over their duplicate additional_kwargs.
        if isinstance(message, AIMessage):
            if message.tool_calls or message.invalid_tool_calls:
                payload["tool_calls"] = [
                    {"id": call["id"], "type": "function", "function": {
                        "name": call["name"], "arguments": json.dumps(call["args"]),
                    }} for call in message.tool_calls
                ] + [
                    {"id": call["id"], "type": "function", "function": {
                        "name": call["name"], "arguments": call["args"],
                    }} for call in message.invalid_tool_calls
                ]
            elif "tool_calls" in message.additional_kwargs:
                payload["tool_calls"] = message.additional_kwargs["tool_calls"]
            elif "function_call" in message.additional_kwargs:
                payload["function_call"] = message.additional_kwargs["function_call"]
        if not payload.get("name") and message.additional_kwargs.get("name"):
            payload["name"] = message.additional_kwargs["name"]
        if message.additional_kwargs.get("__openai_role__"):
            payload["role"] = message.additional_kwargs["__openai_role__"]
        # Work on a copy: provider-native raw calls can share nested objects.
        payload = deepcopy(payload)
        content = payload.pop("content", "")
        if isinstance(content, str):
            count += estimate_tokens(content)
        else:
            for block in content:
                count += estimate_tokens(block["text"])
                count += estimate_tokens(_json({key: val for key, val in block.items() if key != "text"}))
        calls = [call.get("function", {}) for call in payload.get("tool_calls", [])]
        if "function_call" in payload:
            calls.append(payload["function_call"])
        for call in calls:
            arguments = call.pop("arguments", "")
            count += estimate_tokens(arguments if isinstance(arguments, str) else _json(arguments))
        count += estimate_tokens(_json(payload))
    return count + estimate_tokens(_json(options))


def prepare_messages(value, policy, request_options=None):
    if isinstance(value, PromptValue):
        messages = value.to_messages()
    elif isinstance(value, str):
        messages = [HumanMessage(content=value)]
    else:
        messages = convert_to_messages(value)
    prepared = []
    for message in messages:
        # Copy all fields, including call IDs/status. The executor's raw tool
        # observations and error-recovery inputs must remain unchanged.
        copied = message.model_copy(deep=True)
        if isinstance(copied, ToolMessage) and copied.status != "error":
            copied.content = compact_tool_content(
                copied.content, estimate_tokens, policy.compaction_min_tokens,
            )
        # The current tools and assistant are text-only. Do not pretend that
        # image/audio token costs can be estimated from an encoded URL/string.
        if not isinstance(copied.content, str):
            if any(not isinstance(block, str) and (
                not isinstance(block, dict) or block.get("type") != "text"
            ) for block in copied.content):
                raise ValueError("上下文预算目前仅支持文本消息。")
        prepared.append(copied)
    count = estimate_request_tokens(prepared, request_options, policy.tool_protocol_tokens)
    if count > policy.input_budget:
        raise ContextBudgetExceeded(count, policy.input_budget)
    return prepared


class GuardedChatModel(Runnable):
    """Runnable adapter retaining the real model's streaming/callback events."""

    def __init__(self, model, policy, request_options=None, output_parameter="max_tokens"):
        self.model = model
        self.policy = policy
        self.request_options = dict(request_options or {})
        self.output_parameter = output_parameter

    def bind_tools(self, tools, **kwargs):
        tools = list(tools)
        bound = self.model.bind_tools(tools, **kwargs)
        options = {**self.request_options, **kwargs,
                   "tools": [convert_to_openai_tool(tool) for tool in tools]}
        # Prefer the provider's actual converted schemas, if exposed.
        options.update(getattr(bound, "kwargs", {}))
        if isinstance(bound, RunnableBinding) and not bound.config and not bound.config_factories:
            bound = bound.bound
        return type(self)(bound, self.policy, options, self.output_parameter)

    def bind(self, **kwargs):
        return type(self)(self.model, self.policy,
                          {**self.request_options, **kwargs}, self.output_parameter)

    def _prepare_call(self, value, kwargs):
        options = {**self.request_options, **kwargs}
        for name in ("max_tokens", "max_completion_tokens", "num_predict"):
            if name in options:
                option_value = options[name]
                if type(option_value) is not int or not 0 < option_value <= self.policy.output_tokens:
                    raise ValueError(f"{name} must be within the configured output reserve")
        if "num_ctx" in options:
            raise ValueError("num_ctx cannot override the configured context budget")
        if any(name in options for name in ("options", "model_kwargs", "extra_body", "model")):
            raise ValueError("Model overrides cannot bypass context budget settings")
        # Caller may lower the output cap, but can never increase the reserve.
        caps = [options[name] for name in ("max_tokens", "max_completion_tokens", "num_predict")
                if name in options]
        cap = min(caps, default=self.policy.output_tokens)
        if self.output_parameter == "num_predict":
            # langchain-ollama 0.3 accepts this only in constructor/options;
            # a top-level invocation kwarg leaks into Client.chat and fails.
            # The factory fixes the cap at construction. Runtime overrides
            # cannot safely replace the provider's entire options dictionary.
            if cap != self.policy.output_tokens or any(
                name in options for name in ("max_tokens", "max_completion_tokens")
            ):
                raise ValueError("Set Ollama output limit through AI_CONTEXT_OUTPUT_TOKENS")
            options.pop("num_predict", None)
        else:
            if "num_predict" in options:
                raise ValueError("num_predict is only supported by Ollama")
            options[self.output_parameter] = cap
            if "max_completion_tokens" in options:
                options.pop("max_tokens")
                options["max_completion_tokens"] = cap
        prepared = prepare_messages(value, self.policy, options)
        return prepared, options

    def invoke(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        return _check_completion(self.model.invoke(prepared, config=config, **options))

    async def ainvoke(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        return _check_completion(await self.model.ainvoke(prepared, config=config, **options))

    def stream(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        with closing(self.model.stream(prepared, config=config, **options)) as chunks:
            for chunk in chunks:
                yield _check_completion(chunk)

    async def astream(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        async with aclosing(self.model.astream(prepared, config=config, **options)) as chunks:
            async for chunk in chunks:
                yield _check_completion(chunk)
