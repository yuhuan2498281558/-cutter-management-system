import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from langchain_core.messages import AIMessage, ToolMessage

from application.ai_assistant.context_budget import ContextBudgetPolicy, estimate_request_tokens
from application.ai_assistant.context_events import (
    CHECKPOINT_HEADER, PRUNED_HEADER, ContextEventStore, prune_tool_content,
)
from application.ai_assistant.llm_service import _history_turns, _unsupported_numbers
# 只引用模块：把测试类导入到本模块会让测试运行器把它的用例再跑一遍
from application.ai_assistant.tests import test_context_events as events_module

# 一次查询返回的大结果：汇总加 300 行明细
LARGE = json.dumps({
    "summary": {"total_records": 300, "unit": "把", "ring_range": [100, 399]},
    "rows": [{"ring_no": 100 + i, "cutter_position_no": f"S{i % 19 + 1}L", "count": i % 7} for i in range(300)],
}, ensure_ascii=False)
CONTEXT = {"project_id": "P1"}


class HistoryCompactionTests(SimpleTestCase):
    setUp = events_module.ContextEventTests.setUp
    snapshot = events_module.ContextEventTests.snapshot
    ask = events_module.ContextEventTests.ask

    def three_large_turns(self):
        self.model.with_usage = False
        with patch.object(events_module, "RAW", LARGE):
            for index in range(3):
                self.ask(f"查询第{index + 1}项")

    def trigger_just_below_next_turn(self):
        """把触发线定在下一问的预计量下方，保留比例正好装下最近一轮。"""
        _, history, before = self.assistant._compaction_check(self.snapshot(), CONTEXT, "查询第4项")
        newest = estimate_request_tokens(_history_turns(history)[-1][1])
        window = int((before - 300) / 0.8)
        self.guard.policy = ContextBudgetPolicy(window, 1024, 512, retain_ratio=(newest + 100) / window)
        return before

    def test_older_large_results_are_pruned_and_the_newest_turn_stays_verbatim(self):
        self.three_large_turns()
        sequences = [answer.sequence for _, answer in self.memory._complete_turns(self.snapshot().messages)]
        before = self.trigger_just_below_next_turn()
        with patch.object(events_module, "RAW", LARGE):
            result = self.ask("查询第4项")
        [record] = ContextEventStore.compactions(self.snapshot().context_events)
        self.assertEqual((record["mode"], record["through_sequence"]), ("prune", sequences[1]))
        self.assertLess(record["after"], record["before"])
        self.assertGreater(record["before"], before - 1000)
        request = self.model.seen[-2]
        tool_contents = [message.content for message in request if isinstance(message, ToolMessage)]
        self.assertEqual([content.startswith(PRUNED_HEADER) for content in tool_contents], [True] * 4 + [False] * 2)
        compaction = result["context"]["compaction"]
        self.assertEqual((compaction["state"], compaction["auto"], compaction["through_sequence"]), ("pruned", True, None))
        self.assertEqual(compaction["pruned_results"], 4)
        self.assistant.reset_memory("event-test")
        self.assertEqual(ContextEventStore.compactions(self.snapshot().context_events), [])

    async def test_stream_reports_compaction_before_answering(self):
        self.three_large_turns()
        self.trigger_just_below_next_turn()
        with patch.object(events_module, "RAW", LARGE):
            events = [event async for event in self.assistant.chat_stream("查询第4项", self.options)]
        types = [event["type"] for event in events]
        self.assertEqual(types[-1], "done", events)
        self.assertEqual([event["stage"] for event in events if event["type"] == "status"], ["compacting", "done"])
        self.assertLess(types.index("status"), types.index("meta"))

    def test_checkpoint_replaces_older_turns_and_the_page_learns_where_it_ends(self):
        self.three_large_turns()
        snapshot = self.snapshot()
        sequences = [answer.sequence for _, answer in self.memory._complete_turns(snapshot.messages)]
        # 保留比例正好装下最近一轮：前两轮整理成摘要，第三轮保留原文
        newest = estimate_request_tokens(_history_turns(self.assistant._memory_messages(snapshot, CONTEXT))[-1][1])
        self.guard.policy = ContextBudgetPolicy(retain_ratio=(newest + 100) / 256000)
        self.model.mode = "answer"
        compacted, history = self.assistant._compact_history(snapshot, CONTEXT, "下一问", force=True)
        [record] = ContextEventStore.compactions(compacted.context_events)
        self.assertEqual((record["mode"], record["through_sequence"]), ("checkpoint", sequences[1]))
        self.assertEqual(record["summary"], "根据已有结果，共3条，缺失值未知。")
        self.assertEqual(history[0].content, CHECKPOINT_HEADER + record["summary"])
        self.assertEqual([item[0] for item in _history_turns(history)], [None, sequences[2]])
        self.assertEqual(sum(isinstance(message, ToolMessage) for message in history), 2)
        context = self.assistant.get_history("event-test", project_id="P1")["context"]["compaction"]
        self.assertEqual((context["state"], context["through_sequence"], context["checkpoints"]),
                         ("checkpoint", record["through_sequence"], 1))
        self.assertEqual((context["last_before"], context["last_after"]), (record["before"], record["after"]))

    def test_summary_numbers_must_come_from_the_material(self):
        self.assertEqual(_unsupported_numbers("共 1,234 把，占 46.2%，第 3 环", "1234 把，46.2%"), [])
        self.assertEqual(_unsupported_numbers("共 5678 把，第 12 环", "共 1234 把"), ["12", "5678"])
        self.three_large_turns()
        history = self.assistant._memory_messages(self.snapshot(), CONTEXT)
        material = _history_turns(history)[:2]
        llm = Mock(policy=ContextBudgetPolicy())
        llm.invoke.side_effect = [AIMessage(content="共换刀 5678 把"), AIMessage(content="共换刀 9999 把")]
        self.assistant._llm = llm
        summary = self.assistant._write_checkpoint(material, self.snapshot())
        self.assertTrue(summary.startswith("（自动节选，未经整理）"), summary)
        self.assertIn("问：查询第1项", summary)
        retry = llm.invoke.call_args_list[1].args[0][-1].content
        self.assertIn("5678", retry)

    def test_provider_overflow_compacts_once_and_retries(self):
        self.three_large_turns()
        original = events_module.ConversationModel._response
        failures = ["Error code: 400 - This model's maximum context length is 65536 tokens"]

        def overflow_once(model, messages):
            if failures:
                raise RuntimeError(failures.pop())
            return original(model, messages)

        with patch.object(events_module.ConversationModel, "_response", overflow_once), patch.object(events_module, "RAW", LARGE):
            result = self.ask("查询第4项")
        self.assertFalse(result["context"]["exceeded"])
        [record] = ContextEventStore.compactions(self.snapshot().context_events)
        self.assertEqual(record["mode"], "checkpoint")
        self.assertEqual(self.snapshot().message_count, 8)

    def test_compaction_is_not_saved_after_a_reset(self):
        self.three_large_turns()
        old = self.snapshot()
        self.assistant.reset_memory("event-test")
        payload = {"mode": "prune", "through_sequence": old.messages[1].sequence, "before": 1, "after": 1}
        self.assertIsNone(self.memory.append_compaction(old, "P1", payload))
        self.assertEqual(ContextEventStore.compactions(self.snapshot().context_events), [])

    def test_pruning_keeps_scalars_and_counts_long_lists(self):
        pruned = prune_tool_content(LARGE)
        self.assertTrue(pruned.startswith(PRUNED_HEADER))
        kept = json.loads(pruned.removeprefix(PRUNED_HEADER))
        self.assertEqual(kept["summary"]["total_records"], 300)
        self.assertEqual(kept["summary"]["ring_range"], [100, 399])
        self.assertEqual(kept["rows"], "（300 条明细已移出上下文）")
        self.assertTrue(prune_tool_content("不是 JSON 的长文本" * 500).startswith(PRUNED_HEADER))
