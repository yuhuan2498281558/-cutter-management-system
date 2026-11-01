"""逐字保留工具 schema，保证已落库历史的回放和供应商前缀缓存不变。"""

from dataclasses import dataclass
from textwrap import dedent

from asgiref.sync import sync_to_async
from pydantic import ConfigDict, ValidationError, create_model
from pydantic.fields import FieldInfo


@dataclass
class Tool:
    """校验参数后执行项目工具，保留校验观测和异常传播。"""
    name: str
    description: str
    args_schema: type
    func: object
    handle_validation_error: object = False
    return_direct: bool = False

    def invoke(self, tool_input, config=None):
        """只传入调用方提供且通过校验的参数。"""
        try:
            if isinstance(tool_input, str):
                self.args_schema.model_validate({next(iter(self.args_schema.model_fields)): tool_input})
                return self.func(tool_input)
            parsed = self.args_schema.model_validate(tool_input)
            return self.func(**{key: getattr(parsed, key) for key in parsed.model_dump() if key in tool_input})
        except ValidationError as error:
            if not self.handle_validation_error:
                raise
            return self.handle_validation_error(error)

    async def ainvoke(self, tool_input, config=None):
        """在线程中执行同步工具并传递请求上下文。"""
        return await sync_to_async(self.invoke, thread_sensitive=False)(tool_input, config=config)


def tool(*, args_schema):
    """用显式参数模型包装业务工具函数。"""
    def decorate(func):
        return Tool(func.__name__, dedent(func.__doc__).strip(), args_schema, func)
    return decorate


def _without_titles(value, parent=""):
    return {key: _without_titles(item, key) if isinstance(item, dict) else item
            for key, item in value.items() if key != "title" or (parent == "properties" and isinstance(item, dict))}


def openai_tool_schema(tool):
    """导出与原子集模型一致的 OpenAI 工具 schema。"""
    if isinstance(tool, dict):
        return tool
    fields = {}
    for name, field in tool.args_schema.model_fields.items():
        info = FieldInfo(description=field.description, default=field.default)
        info.metadata = field.metadata
        fields[name] = (field.annotation, info)
    model = create_model(tool.name, **fields, __config__=ConfigDict(arbitrary_types_allowed=True))
    model.__doc__ = dedent(tool.description or tool.args_schema.__doc__ or "")
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    return {"type": "function", "function": {"name": tool.name, "description": tool.description,
                                               "parameters": _without_titles(schema)}}
