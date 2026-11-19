"""工具 schema、校验观测和项目绑定的固定协议测试。"""

import json
from inspect import Parameter, signature
from typing import Any
from unittest import TestCase
from unittest.mock import Mock

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from application.ai_assistant.tooling import Tool, tool, openai_tool_schema


class TestTool(Tool):
    """仅供测试注入异步阻塞和调用配置的工具。"""
    def invoke(self, tool_input, config=None):
        if "config" in signature(self.func).parameters:
            return self.func(**self.args_schema.model_validate(tool_input).model_dump(), config=config)
        return super().invoke(tool_input, config)

    async def ainvoke(self, tool_input, config=None):
        if self.coroutine:
            return await self.coroutine(**tool_input)
        return await super().ainvoke(tool_input, config)


def make_tool(func, *, name, description, coroutine=None):
    """为测试函数提供简单显式参数模型。"""
    fields = {key: (item.annotation if item.annotation is not Parameter.empty else Any,
                    item.default if item.default is not Parameter.empty else ...)
              for key, item in signature(func).parameters.items() if key != "config"}
    result = TestTool(name, description, create_model(name, **fields), func)
    result.coroutine = coroutine
    return result


class ToolingTests(TestCase):
    def test_schema_bytes_and_validation_are_separate(self):
        class Args(BaseModel):
            model_config = ConfigDict(extra="forbid")
            value: int = Field(description="数值", ge=1)
            label: str = "中文"

        @tool(args_schema=Args)
        def lookup(value, label="中文"):
            """查询数值。"""
            return value, label

        self.assertEqual(json.dumps(openai_tool_schema(lookup), ensure_ascii=False),
            '{"type": "function", "function": {"name": "lookup", "description": "查询数值。", "parameters": '
            '{"properties": {"value": {"description": "数值", "minimum": 1, "type": "integer"}, '
            '"label": {"default": "中文", "type": "string"}}, "required": ["value"], "type": "object"}}}')
        with self.assertRaises(ValidationError):
            lookup.invoke({"value": 0})
        lookup.handle_validation_error = lambda error: "参数错误"
        self.assertEqual(lookup.invoke({"value": 0}), "参数错误")
        self.assertEqual(lookup.invoke({"value": 1, "extra": True}), "参数错误")
        self.assertEqual(lookup.invoke({"value": "2"}), (2, "中文"))
        lookup.func = Mock(side_effect=RuntimeError("query failed"))
        with self.assertRaisesRegex(RuntimeError, "query failed"):
            lookup.invoke({"value": 1})
        lookup.func.assert_called_once_with(value=1)

    def test_binding_keeps_schema_and_request_project(self):
        from application.ai_assistant.llm_service import _bind_tools_to_project, _BOUND_TOOL_PROJECT_ID

        class Args(BaseModel):
            value: int

        original = Tool("lookup", "查询", Args, lambda value: (_BOUND_TOOL_PROJECT_ID.get(), value))
        first, = _bind_tools_to_project([original], "P1")
        second, = _bind_tools_to_project([original], "P2")
        self.assertEqual(json.dumps(openai_tool_schema(first)), json.dumps(openai_tool_schema(original)))
        self.assertEqual(first.invoke({"value": 1}), ("P1", 1))
        self.assertEqual(second.invoke({"value": 2}), ("P2", 2))
        self.assertEqual(_BOUND_TOOL_PROJECT_ID.get(), "")
