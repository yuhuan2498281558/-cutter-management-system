"""Guard every model call without changing execution evidence or callbacks.

The configured window is an operational limit, not a discovered model capacity.
Preflight counts are estimates; the reserve and margin reduce, but cannot rule out, a
provider tokenizer exceeding its actual window.
"""

from dataclasses import dataclass, field
from contextlib import aclosing, closing
from contextvars import ContextVar
from copy import deepcopy
import json
from hashlib import sha256

from langchain_core.messages import (
    AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage, convert_to_messages, convert_to_openai_messages,
)
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable
from langchain_core.runnables.base import RunnableBinding
from langchain_core.utils.function_calling import convert_to_openai_tool

from .context_compaction import COLUMNAR_FORMAT, compact_tool_content
from .token_estimation import estimate_tokens


class ContextBudgetExceeded(ValueError):
    message = (
        "本轮上下文超过配置预算（估算 {estimated}，输入预算 {budget}）。"
        "请缩小查询范围、增大统计分段或拆分问题后重试；本次未生成完整回答。"
    )

    def __init__(self, estimated_tokens, input_budget):
        self.estimated_tokens = estimated_tokens
        self.input_budget = input_budget
        super().__init__(self.message.format(estimated=estimated_tokens, budget=input_budget))


class HistoryBudgetExceeded(ContextBudgetExceeded):
    """不算本轮查询结果就已超限：缩小本轮范围没用，只能重置对话。"""
    message = "对话历史已超过模型上下文上限，本次未生成回答。请点「重置对话」清空历史后再问。"


class OutputLimitExceeded(ValueError):
    """A provider explicitly stopped on its length cap, not a completed answer."""


def _check_completion(message):
    metadata = getattr(message, "response_metadata", {}) or {}
    if metadata.get("finish_reason") == "length":
        raise OutputLimitExceeded("本次回答达到输出上限，未生成完整回答。请缩小范围或拆分问题后重试。")
    return message


@dataclass(frozen=True)
class ContextBudgetPolicy:
    context_tokens: int = 256000
    output_tokens: int = 8192
    safety_margin_tokens: int = 4096
    compaction_min_tokens: int = 1000
    tool_protocol_tokens: int = 1024
    trigger_ratio: float = 0.8
    retain_ratio: float = 0.16

    def __post_init__(self):
        for name in ("context_tokens", "output_tokens", "safety_margin_tokens", "compaction_min_tokens", "tool_protocol_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.input_budget <= 0:
            raise ValueError("Context budget must exceed output reserve plus safety margin")
        if not 0 < self.retain_ratio < self.trigger_ratio < 1:
            raise ValueError("Ratios must satisfy 0 < retain_ratio < trigger_ratio < 1")

    @property
    def input_budget(self):
        return self.context_tokens - self.output_tokens - self.safety_margin_tokens

    @property
    def trigger_tokens(self):
        return int(self.context_tokens * self.trigger_ratio)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


context_usage = ContextVar("ai_context_usage", default=None)
_PARTS_KEY = "_context_parts"


def mark_context_message(message, **parts):
    message.response_metadata[_PARTS_KEY] = parts
    return message


def request_fingerprint(messages, options, provider, model):
    return sha256(_json({
        "provider": provider, "model": model,
        "system": [message.content for message in messages if isinstance(message, SystemMessage)],
        "tools": options.get("tools"), "functions": options.get("functions"),
    }).encode("utf-8")).hexdigest()


def _paged_lists(content):
    try:
        data = json.loads(content)
        if isinstance(data, dict) and data.get("format") == COLUMNAR_FORMAT:
            data = data.get("data")
        paging = data.get("_paging") if isinstance(data, dict) else None
        return len(paging) if isinstance(paging, dict) else 0
    except (ValueError, TypeError, RecursionError):
        return 0


@dataclass
class ContextUsage:
    model_calls: int = 0
    page_requests: int = 0
    policy: ContextBudgetPolicy | None = None
    peak: dict | None = None
    exceeded: bool = False
    inputs: dict = field(default_factory=dict)
    history: dict = field(default_factory=lambda: dict(
        turns=0, tool_results=0, legacy_qa_turns=0, other_project_turns=0, tokens=0,
    ))
    provider_usage: dict | None = None
    last_prompt_tokens_actual: int | None = None
    last_estimate: int | None = None
    calls: list = field(default_factory=list)
    current: dict | None = None
    measured_peak: dict | None = None
    # 历史整理状态，由回放历史时填写；没有时按“未整理”输出
    compaction: dict | None = None

    def record_response(self, message, messages, options, provider, model):
        self.page_requests += sum(
            isinstance(call["args"].get("page"), (int, float)) and call["args"]["page"] > 1
            for call in getattr(message, "tool_calls", [])
        )
        metadata = getattr(message, "response_metadata", {}) or {}
        raw = metadata.get("token_usage") or {}
        normalized = getattr(message, "usage_metadata", None) or {}
        prompt = raw.get("prompt_tokens", normalized.get("input_tokens"))
        completion = raw.get("completion_tokens", normalized.get("output_tokens"))
        cache = raw.get("prompt_cache_hit_tokens", (normalized.get("input_token_details") or {}).get("cache_read"))
        self.last_prompt_tokens_actual = prompt
        actual_model = metadata.get("model_name") or metadata.get("model") or model
        call = dict(
            prompt_tokens=prompt, completion_tokens=completion, prompt_cache_hit_tokens=cache,
            provider=provider, model=actual_model, requested_model=model,
            fingerprint=request_fingerprint(messages, options, provider, actual_model),
            request_estimate=self.last_estimate,
        )
        self.calls.append(call)
        measured = prompt if prompt is not None else self.last_estimate
        if measured is not None and (not self.measured_peak or measured >= self.measured_peak["used"]):
            self.measured_peak = {"used": measured, "actual": prompt is not None, "parts": self.current}
        if prompt is None:
            return
        self.add_provider_usage(dict(prompt_tokens=prompt, completion_tokens=completion, cache_hit_tokens=cache))

    def add_provider_usage(self, usage):
        """累加接口计费用量；整理历史的摘要调用也计入本轮。"""
        if not usage:
            return
        if self.provider_usage is None:
            self.provider_usage = dict(prompt_tokens=None, completion_tokens=None, cache_hit_tokens=None)
        for key, value in usage.items():
            if value is not None:
                self.provider_usage[key] = (self.provider_usage[key] or 0) + value

    def clear_overflow(self):
        """超限后整理历史重试：失败的那次不再算作本轮峰值。"""
        self.exceeded, self.peak, self.measured_peak, self.current = False, None, None, None

    def event(self):
        if not self.calls:
            return None
        return {**self.calls[-1], "calls": self.calls, "provider_usage": self.provider_usage}

    def record(self, messages, policy, options, count, raw, compacted):
        self.model_calls += 1
        self.last_estimate = count
        exceeded = count > policy.input_budget
        parts = dict.fromkeys(("system", "tools", "memory", "question", "results", "other"), 0)
        estimate_request_tokens(messages, options, policy.tool_protocol_tokens, parts)
        self.history["tokens"] = parts["memory"]
        self.current = {"used": count, "parts": parts, "results_raw": raw,
                     "compacted_results": compacted, "summarized_results": 0,
                     "paged_lists": sum(_paged_lists(message.content) for message in messages
                                        if isinstance(message, ToolMessage))}
        # 超限时显示导致失败的那一次，否则保留估算峰值。
        if not self.exceeded and (exceeded or not self.peak or count > self.peak["used"]):
            self.policy, self.exceeded, self.peak = policy, exceeded, self.current

    def info(self, kind, policy, memory):
        policy = self.policy or policy
        measured = self.measured_peak if kind == "turn" and not self.exceeded else None
        actual = bool(measured and measured["actual"])
        peak = measured["parts"] if measured else self.peak
        return {
            "kind": kind, "window": policy.context_tokens,
            "input_budget": policy.input_budget, "output_reserve": policy.output_tokens,
            "safety_margin": policy.safety_margin_tokens,
            **(peak or {"used": None, "parts": None, "results_raw": None,
                            "compacted_results": 0, "summarized_results": 0}),
            "schema_version": 2, "measurement": "actual" if actual else "estimated",
            "estimated": not actual,
            "used": measured["used"] if measured else (self.peak or {}).get("used"),
            "last_prompt_tokens_actual": self.last_prompt_tokens_actual,
            "trigger_tokens": policy.trigger_tokens, "hard_input_limit": policy.input_budget,
            "provider_usage": self.provider_usage,
            "history": self.history,
            "compaction": self.compaction or {"state": "none", "checkpoints": 0, "pruned_results": 0,
                                              "last_at": None, "last_before": None, "last_after": None},
            "paged_lists": peak["paged_lists"] if kind == "turn" and peak else 0,
            "page_requests": self.page_requests if kind == "turn" else 0,
            "exceeded": self.exceeded, "model_calls": self.model_calls,
            "thresholds": {"compaction_min_tokens": policy.compaction_min_tokens},
            "memory": memory,
        }


def estimate_request_tokens(messages, request_options=None, tool_protocol_tokens=1024, parts=None):
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
    if parts is not None:
        parts["tools"] = count - (8 * len(messages) + 16) + estimate_tokens(_json(options))
    for message in messages:
        before_count = count
        before_parts = dict(parts) if parts is not None else None
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
        if parts is not None:
            text_tokens = estimate_tokens(content) if isinstance(content, str) else sum(
                estimate_tokens(block["text"]) for block in content
            )
            marked = message.response_metadata.get(_PARTS_KEY)
            usage = context_usage.get()
            if marked is None and isinstance(message, HumanMessage) and isinstance(message.content, str) and usage:
                marked = usage.inputs.get(message.content)
            if marked is not None:
                for name, text in marked.items():
                    tokens = min(text_tokens, estimate_tokens(text))
                    parts[name] += tokens
                    text_tokens -= tokens
            elif isinstance(message, (SystemMessage, ToolMessage)):
                parts["system" if isinstance(message, SystemMessage) else "results"] += text_tokens
        calls = [call.get("function", {}) for call in payload.get("tool_calls", [])]
        if "function_call" in payload:
            calls.append(payload["function_call"])
        for call in calls:
            arguments = call.pop("arguments", "")
            tokens = estimate_tokens(arguments if isinstance(arguments, str) else _json(arguments))
            count += tokens
            if parts is not None:
                parts["results"] += tokens
        count += estimate_tokens(_json(payload))
        if parts is not None and "memory" in message.response_metadata.get(_PARTS_KEY, {}):
            parts.update(before_parts)
            parts["memory"] += count - before_count + 8
    count += estimate_tokens(_json(options))
    if parts is not None:
        parts["other"] = count - sum(parts.values())
    return count


def encode_messages(value, policy):
    if isinstance(value, PromptValue):
        messages = value.to_messages()
    elif isinstance(value, str):
        messages = [HumanMessage(content=value)]
    else:
        messages = convert_to_messages(value)
    prepared = []
    raw = compacted = 0
    for message in messages:
        # Copy all fields, including call IDs/status. The executor's raw tool
        # observations and error-recovery inputs must remain unchanged.
        copied = message.model_copy(deep=True)
        if isinstance(copied, ToolMessage):
            raw += estimate_tokens(copied.content if isinstance(copied.content, str) else _json(copied.content))
        if isinstance(copied, ToolMessage) and copied.status != "error":
            copied.content = compact_tool_content(
                copied.content, estimate_tokens, policy.compaction_min_tokens,
            )
            compacted += copied.content != message.content
        if isinstance(copied, AIMessage) and copied.additional_kwargs.get("tool_calls"):
            # SDK 默认重序列化解析后的参数；原文优先以保持历史前缀稳定。
            copied.tool_calls = []
            copied.invalid_tool_calls = []
        # The current tools and assistant are text-only. Do not pretend that
        # image/audio token costs can be estimated from an encoded URL/string.
        if not isinstance(copied.content, str):
            if any(not isinstance(block, str) and (
                not isinstance(block, dict) or block.get("type") != "text"
            ) for block in copied.content):
                raise ValueError("上下文预算目前仅支持文本消息。")
        prepared.append(copied)
    return prepared, raw, compacted


def prepare_messages(value, policy, request_options=None):
    prepared, raw, compacted = encode_messages(value, policy)
    count = estimate_request_tokens(prepared, request_options, policy.tool_protocol_tokens)
    if usage := context_usage.get():
        usage.record(prepared, policy, request_options, count, raw, compacted)
    if count > policy.input_budget:
        parts = dict.fromkeys(("system", "tools", "memory", "question", "results", "other"), 0)
        estimate_request_tokens(prepared, request_options, policy.tool_protocol_tokens, parts)
        history_full = parts["memory"] and count - parts["results"] > policy.input_budget
        error = HistoryBudgetExceeded if history_full else ContextBudgetExceeded
        raise error(count, policy.input_budget)
    for message in prepared:
        message.response_metadata.pop(_PARTS_KEY, None)
    return prepared


class GuardedChatModel(Runnable):
    """Runnable adapter retaining the real model's streaming/callback events."""

    def __init__(self, model, policy, request_options=None, output_parameter="max_tokens",
                 provider="", model_name=""):
        self.model = model
        self.policy = policy
        self.request_options = dict(request_options or {})
        self.output_parameter = output_parameter
        self.provider = provider
        self.model_name = model_name or getattr(model, "model_name", "") or getattr(model, "model", "")

    def bind_tools(self, tools, **kwargs):
        tools = list(tools)
        bound = self.model.bind_tools(tools, **kwargs)
        options = {**self.request_options, **kwargs,
                   "tools": [convert_to_openai_tool(tool) for tool in tools]}
        # Prefer the provider's actual converted schemas, if exposed.
        options.update(getattr(bound, "kwargs", {}))
        if isinstance(bound, RunnableBinding) and not bound.config and not bound.config_factories:
            bound = bound.bound
        return type(self)(bound, self.policy, options, self.output_parameter,
                          self.provider, self.model_name)

    def bind(self, **kwargs):
        return type(self)(self.model, self.policy,
                          {**self.request_options, **kwargs}, self.output_parameter,
                          self.provider, self.model_name)

    def _prepare_call(self, value, kwargs):
        options = {**self.request_options, **kwargs}
        for name in ("max_tokens", "max_completion_tokens"):
            if name in options:
                option_value = options[name]
                if type(option_value) is not int or not 0 < option_value <= self.policy.output_tokens:
                    raise ValueError(f"{name} must be within the configured output reserve")
        if any(name in options for name in ("options", "model_kwargs", "extra_body", "model")):
            raise ValueError("Model overrides cannot bypass context budget settings")
        # Caller may lower the output cap, but can never increase the reserve.
        caps = [options[name] for name in ("max_tokens", "max_completion_tokens")
                if name in options]
        cap = min(caps, default=self.policy.output_tokens)
        options[self.output_parameter] = cap
        if "max_completion_tokens" in options:
            options.pop("max_tokens")
            options["max_completion_tokens"] = cap
        prepared = prepare_messages(value, self.policy, options)
        return prepared, options

    def invoke(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        response = self.model.invoke(prepared, config=config, **options)
        if usage := context_usage.get():
            usage.record_response(response, prepared, options, self.provider, self.model_name)
        return _check_completion(response)

    async def ainvoke(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        response = await self.model.ainvoke(prepared, config=config, **options)
        if usage := context_usage.get():
            usage.record_response(response, prepared, options, self.provider, self.model_name)
        return _check_completion(response)

    def stream(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        usage, response = context_usage.get(), None
        with closing(self.model.stream(prepared, config=config, **options)) as chunks:
            for chunk in chunks:
                if isinstance(chunk, AIMessageChunk):
                    response = chunk if response is None else response + chunk
                else:
                    response = chunk
                yield chunk
        if usage:
            usage.record_response(response, prepared, options, self.provider, self.model_name)
        _check_completion(response)

    async def astream(self, input, config=None, **kwargs):
        prepared, options = self._prepare_call(input, kwargs)
        usage, response = context_usage.get(), None
        async with aclosing(self.model.astream(prepared, config=config, **options)) as chunks:
            async for chunk in chunks:
                if isinstance(chunk, AIMessageChunk):
                    response = chunk if response is None else response + chunk
                else:
                    response = chunk
                yield chunk
        if usage:
            usage.record_response(response, prepared, options, self.provider, self.model_name)
        _check_completion(response)
