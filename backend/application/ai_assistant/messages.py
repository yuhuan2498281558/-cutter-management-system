"""逐字保留消息格式，保证已落库历史的回放和供应商前缀缓存不变。"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict


class ToolCall(TypedDict):
    """一次工具调用的名称、参数和配对标识。"""
    name: str
    args: dict
    id: str | None
    type: NotRequired[str]


def _merge(left, right):
    if isinstance(left, list):
        merged = left.copy()
        for value in right:
            matches = [i for i, old in enumerate(merged) if old["index"] == value["index"]] if (
                isinstance(value, dict) and isinstance(value.get("index"), int)) else []
            if matches:
                merged[matches[0]] = _merge(merged[matches[0]], {k: v for k, v in value.items() if k != "type"})
            else:
                merged.append(value)
        return merged
    merged = left.copy()
    for key, value in right.items():
        if key not in merged or (value is not None and merged[key] is None):
            merged[key] = value
        elif value is None:
            continue
        elif type(merged[key]) is not type(value):
            raise TypeError(f'additional_kwargs["{key}"] already exists in this message, but with a different type.')
        elif isinstance(value, str):
            merged[key] += value
        elif isinstance(value, (dict, list)):
            merged[key] = _merge(merged[key], value)
        elif merged[key] != value:
            raise TypeError(f"Additional kwargs key {key} already exists in left dict and value has unsupported type {type(merged[key])}.")
    return merged


def _add_usage(left, right, *, nested=False):
    if not (left and right):
        return left or right or ({} if nested else {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    return {key: (_add_usage(left.get(key, {}), right.get(key, {}), nested=True) if isinstance(value, dict)
                  else left.get(key, 0) + right.get(key, 0)) for key, value in {**left, **right}.items()}


def _partial_json(text):
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass
    chars, stack, inside, escaped = [], [], False, False
    for char in text:
        new = char
        if inside:
            if char == '"' and not escaped:
                inside = False
            elif char == "\n" and not escaped:
                new = "\\n"
            elif char == "\\":
                escaped = not escaped
            else:
                escaped = False
        elif char == '"':
            inside, escaped = True, False
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or stack.pop() != char:
                return None
        chars.append(new)
    if inside:
        if escaped:
            chars.pop()
        chars.append('"')
    while chars:
        try:
            return json.loads("".join(chars + stack[::-1]), strict=False)
        except json.JSONDecodeError:
            chars.pop()
    return json.loads(text, strict=False)


def _call(kind, **values):
    keys = {"tool_call": ("name", "args", "id"), "invalid_tool_call": ("name", "args", "id", "error"),
            "tool_call_chunk": ("name", "args", "id", "index")}[kind]
    return {**{key: values.get(key) for key in keys}, "type": kind}


class BaseMessage(BaseModel):
    """保留字段顺序、默认值、额外字段和消息相等语义。"""
    content: str | list[str | dict]
    additional_kwargs: dict = Field(default_factory=dict)
    response_metadata: dict = Field(default_factory=dict)
    type: str
    name: str | None = None
    id: str | None = Field(default=None, coerce_numbers_to_str=True)
    model_config = ConfigDict(extra="allow")

    def __init__(self, content, **kwargs):
        super().__init__(content=content, **kwargs)


class SystemMessage(BaseMessage):
    """系统提示消息。"""
    type: str = "system"


class HumanMessage(BaseMessage):
    """用户消息。"""
    type: str = "human"
    example: bool = False


class AIMessage(BaseMessage):
    """模型回复及其工具调用和用量。"""
    type: str = "ai"
    example: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)
    invalid_tool_calls: list[dict] = Field(default_factory=list)
    usage_metadata: dict | None = None

    def __init__(self, content, **kwargs):
        if not any(kwargs.get(key) for key in ("tool_calls", "invalid_tool_calls", "tool_call_chunks")):
            raw = kwargs.get("additional_kwargs", {}).get("tool_calls", [])
            calls, invalid = [], []
            try:
                for call in raw:
                    function = call.get("function", {})
                    if isinstance(self, AIMessageChunk):
                        calls.append(_call("tool_call_chunk", name=function.get("name"), args=function.get("arguments"),
                                           id=call.get("id"), index=call.get("index")))
                    elif function:
                        try:
                            calls.append(_call("tool_call", name=function["name"] or "",
                                               args=json.loads(function["arguments"]) or {}, id=call.get("id")))
                        except json.JSONDecodeError:
                            invalid.append(_call("invalid_tool_call", name=function["name"],
                                                 args=function["arguments"], id=call.get("id")))
                if raw:
                    kwargs["tool_call_chunks" if isinstance(self, AIMessageChunk) else "tool_calls"] = calls
                    kwargs["invalid_tool_calls"] = invalid
            except (KeyError, TypeError):
                pass
        for field, kind in (("tool_calls", "tool_call"), ("invalid_tool_calls", "invalid_tool_call"),
                            ("tool_call_chunks", "tool_call_chunk")):
            if kwargs.get(field):
                kwargs[field] = [_call(kind, **call) for call in kwargs[field]]
        if usage := kwargs.get("usage_metadata"):
            usage = {key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens",
                     "input_token_details", "output_token_details") if key in usage}
            for key, fields in (("input_token_details", ("audio", "cache_creation", "cache_read")),
                                ("output_token_details", ("audio", "reasoning"))):
                if key in usage:
                    usage[key] = {name: usage[key][name] for name in fields if name in usage[key]}
            kwargs["usage_metadata"] = usage
        super().__init__(content, **kwargs)


class ToolMessage(BaseMessage):
    """与工具调用标识配对的结果。"""
    type: str = "tool"
    tool_call_id: str
    artifact: Any = None
    status: str = "success"

    def __init__(self, content, **kwargs):
        if isinstance(content, (list, tuple)):
            content = [value if isinstance(value, (str, dict)) else str(value) for value in content]
        elif not isinstance(content, str):
            content = str(content)
        super().__init__(content, **{**kwargs, "tool_call_id": str(kwargs["tool_call_id"])})


class AIMessageChunk(AIMessage):
    """可合并文字、分段工具参数和用量的模型片段。"""
    type: str = "AIMessageChunk"
    tool_call_chunks: list[dict] = Field(default_factory=list)

    def __init__(self, content, **kwargs):
        super().__init__(content, **kwargs)
        if not self.tool_call_chunks:
            self.tool_call_chunks = [_call("tool_call_chunk", name=call["name"], id=call["id"],
                args=json.dumps(call["args"]) if call["type"] == "tool_call" else call["args"])
                for call in self.tool_calls + self.invalid_tool_calls]
            return
        self.tool_calls, self.invalid_tool_calls = [], []
        for chunk in self.tool_call_chunks:
            try:
                args = _partial_json(chunk["args"]) if chunk["args"] != "" else {}
                if not isinstance(args, dict):
                    raise ValueError
                self.tool_calls.append(_call("tool_call", name=chunk["name"] or "", args=args, id=chunk["id"]))
            except (ValueError, TypeError):
                self.invalid_tool_calls.append(_call("invalid_tool_call", **chunk))

    def __add__(self, other):
        if self.example != other.example:
            raise ValueError("Cannot concatenate AIMessageChunks with different example values.")
        ids = [value for value in (self.id, other.id) if value]
        return type(self)(self.content + other.content, example=self.example,
            additional_kwargs=_merge(self.additional_kwargs, other.additional_kwargs),
            response_metadata=_merge(self.response_metadata, other.response_metadata),
            tool_call_chunks=_merge(self.tool_call_chunks, other.tool_call_chunks),
            usage_metadata=_add_usage(self.usage_metadata, other.usage_metadata) if (
                self.usage_metadata or other.usage_metadata is not None) else None,
            id=next((value for value in ids if not value.startswith("run-")), next(iter(ids), None)))


def message_to_dict(message):
    """按历史协议的字段顺序序列化消息。"""
    return {"type": message.type, "data": message.model_dump()}


def messages_from_dict(messages):
    """读取协议历史和旧组件保存的消息。"""
    types = {cls.model_fields["type"].default: cls for cls in
             (SystemMessage, HumanMessage, AIMessage, ToolMessage, AIMessageChunk)}
    return [types[item["type"]](**item["data"]) for item in messages]


def message_chunk_to_message(chunk):
    """去除片段字段，生成落库用的完整模型消息。"""
    return AIMessage(**{key: value for key, value in chunk.__dict__.items()
                        if key not in {"type", "tool_call_chunks"}}) if isinstance(chunk, AIMessageChunk) else chunk


def convert_to_openai_messages(messages, *, text_format="string"):
    """转换本项目的文本消息，供上下文预算和协议核对使用。"""
    single = isinstance(messages, BaseMessage)
    results = []
    for message in [messages] if single else messages:
        result = {"role": {"system": "system", "human": "user", "ai": "assistant",
                           "AIMessageChunk": "assistant", "tool": "tool"}[message.type]}
        if message.name:
            result["name"] = message.name
        if isinstance(message, AIMessage) and message.tool_calls:
            result["tool_calls"] = [{"type": "function", "id": call["id"], "function": {
                "name": call["name"], "arguments": json.dumps(call["args"])}} for call in message.tool_calls]
        if message.additional_kwargs.get("refusal"):
            result["refusal"] = message.additional_kwargs["refusal"]
        if isinstance(message, ToolMessage):
            result["tool_call_id"] = message.tool_call_id
        content = message.content
        blocks = ([content] if content else []) if isinstance(content, str) else content
        blocks = [{"type": "text", "text": block if isinstance(block, str) else block["text"]} for block in blocks]
        result["content"] = "\n".join(block["text"] for block in blocks) if text_format == "string" else blocks
        results.append(result)
    return results[0] if single else results
