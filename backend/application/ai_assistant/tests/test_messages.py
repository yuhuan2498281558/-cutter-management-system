"""固定序列化、分段合并和提示用量协议。"""
import json
from unittest import TestCase

from application.ai_assistant.agent_loop import AgentPrompt
from application.ai_assistant.chat_model import UsageCollector
from application.ai_assistant.messages import (
    AIMessage, AIMessageChunk, HumanMessage, ToolMessage, message_to_dict,
    messages_from_dict, message_chunk_to_message,
)


class MessageTests(TestCase):
    def test_history_json_defaults_order_and_equality(self):
        fixtures = [
            '{"type": "human", "data": {"content": "问题", "additional_kwargs": {}, "response_metadata": {}, "type": "human", "name": null, "id": null, "example": false}}',
            '{"type": "ai", "data": {"content": "答复", "additional_kwargs": {}, "response_metadata": {}, "type": "ai", "name": null, "id": null, "example": false, "tool_calls": [], "invalid_tool_calls": [], "usage_metadata": null}}',
            '{"type": "tool", "data": {"content": "结果", "additional_kwargs": {}, "response_metadata": {}, "type": "tool", "name": null, "id": null, "tool_call_id": "call", "artifact": null, "status": "success"}}',
        ]
        messages = [HumanMessage("问题"), AIMessage("答复"), ToolMessage("结果", tool_call_id="call")]
        self.assertEqual([json.dumps(message_to_dict(item), ensure_ascii=False) for item in messages], fixtures)
        self.assertEqual(messages_from_dict([json.loads(item) for item in fixtures]), messages)
        self.assertNotEqual(messages[0], HumanMessage("问题", id="other"))
        self.assertNotEqual(messages[0], AIMessage("问题"))

    def test_chunks_preserve_raw_calls_invalid_json_and_nested_usage(self):
        first = AIMessageChunk("答", tool_call_chunks=[{"name": "look", "args": '{"value":', "index": 0, "id": "c"}],
            usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3, "input_token_details": {"cache_read": 1}}, id="run--local")
        last = AIMessageChunk("复", tool_call_chunks=[{"name": "up", "args": '2}', "index": 0},
            {"name": "bad", "args": "oops", "index": 1, "id": "bad"}], id="provider",
            response_metadata={"finish_reason": "stop", "model_name": "model"},
            usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5, "input_token_details": {"cache_read": 2}})
        combined = first + last
        self.assertEqual((combined.content, combined.id), ("答复", "provider"))
        self.assertEqual(combined.tool_calls, [{"name": "lookup", "args": {"value": 2}, "id": "c", "type": "tool_call"}])
        self.assertEqual(combined.invalid_tool_calls, [{"name": "bad", "args": "oops", "id": "bad", "error": None, "type": "invalid_tool_call"}])
        self.assertEqual(combined.usage_metadata, {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8, "input_token_details": {"cache_read": 3}})
        message = message_chunk_to_message(combined)
        self.assertNotIn("tool_call_chunks", message_to_dict(message)["data"])
        self.assertEqual(message.tool_calls, combined.tool_calls)
        collector = UsageCollector()
        collector.record(message)
        collector.record(message)
        self.assertEqual(collector.usage_metadata, {"model": {"input_tokens": 10, "output_tokens": 6, "total_tokens": 16, "input_token_details": {"cache_read": 6}}})

    def test_prompt_escaping_and_history_are_preserved(self):
        messages = AgentPrompt('系统 {{"a": 1}} {input}').format_messages(
            input="问题 {原样}", chat_history=[HumanMessage("旧问"), AIMessage("旧答")],
            agent_scratchpad=[ToolMessage("结果", tool_call_id="c")])
        self.assertEqual([item.content for item in messages], ['系统 {"a": 1} 问题 {原样}', '旧问', '旧答', '问题 {原样}', '结果'])
