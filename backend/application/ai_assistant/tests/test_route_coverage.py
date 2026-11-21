"""规则直答覆盖检查：只看问句和模板回答的文字，不连数据库、不调模型。"""

from django.test import SimpleTestCase

from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot, StoredMessage
from application.ai_assistant.route_coverage import coverage_gaps


class RouteCoverageTests(SimpleTestCase):
    def test_metric_missing_from_template_is_reported(self):
        answer = "## 换刀统计\n\n共 584 条现场观测记录，实际更换 293 次，更换率 50.2%。\n\n| 异常类型 | 数量 | 占已分类观测记录 |"
        self.assertEqual(coverage_gaps("339到487环异常磨损多少条，已分类异常率多少？", answer), ["已分类异常率"])
        self.assertEqual(coverage_gaps("339到487环观测多少条、更换率多少？", answer), [])

    def test_superlative_needs_explicit_answer_but_top_n_ranking_is_enough(self):
        ranking = "## 刀位更换排行\n\n| 刀位 | 更换次数 |\n| --- | --- |\n| 8 | 8 |"
        self.assertEqual(coverage_gaps("更换次数最多的滚刀刀位是哪几个？有并列就全部列出", ranking), ["最值"])
        self.assertEqual(coverage_gaps("列出更换次数最多的前10个刀位", ranking), [])
        self.assertEqual(coverage_gaps("统计换刀更换率，并列出主要更换刀位", "更换率 50.0%"), [])
        self.assertEqual(coverage_gaps("最近5次开仓的间隔", "最近 5 次：平均间隔 34 环"), [])

    def test_single_ring_is_not_the_range_since_last_opening(self):
        question = "218环开仓，从上次开仓到这次之间经过的地层，各类面积占比是多少？"
        self.assertEqual(coverage_gaps(question, "查询范围：第 218 环；实际覆盖：218–218 环。"), ["上次开仓以来的区间"])
        self.assertEqual(coverage_gaps(question, "查询范围：第 193–218 环。"), [])

    def test_followup_keeps_metrics_asked_in_previous_question(self):
        snapshot = MemorySnapshot(scope_key="user:1", messages=[
            StoredMessage(1, "human", "100到300环的滚刀，已分类异常率多少？", 5), StoredMessage(2, "ai", "旧答案", 5)])
        followup = {"resolved_context_mode": "continue", "memory_snapshot": snapshot}
        question = ToolAssistant._coverage_question("那刮刀呢？", followup)
        self.assertEqual(coverage_gaps(question, "共 251 条现场观测记录，实际更换 125 次。"), ["已分类异常率"])
        self.assertEqual(ToolAssistant._coverage_question("那刮刀呢？", {**followup, "resolved_context_mode": "new"}), "那刮刀呢？")

    def test_named_model_status_filter_and_unsupported_data(self):
        models = ["19寸常压双联正滚刀240"]
        self.assertEqual(coverage_gaps("19寸常压双联正滚刀240 这个型号哪家服役最长？", "| 厂家 | 平均服役环数 |\n最长为模拟厂家08", models),
                         ["型号 19寸常压双联正滚刀240"])
        self.assertEqual(coverage_gaps("厂家已经确认的旧刀返修（含已归档）登记金额多少？", "查询范围：全项目；厂家反馈状态：已归档；"),
                         ["反馈状态筛选"])
        self.assertEqual(coverage_gaps("S1L刀位这把刀还能用多少环？", "共 14 条现场观测记录"), ["库中没有的数据"])
