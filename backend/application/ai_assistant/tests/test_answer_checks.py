from django.test import SimpleTestCase

from application.ai_assistant.evaluation.answer_checks import check_answer


TREND = """## 换刀趋势
| 环段 | 观测记录数 | 更换次数 | 更换率 |
| --- | --- | --- | --- |
| 1-100 | 10 | 3 | 30.0% |
| 101-200 | 8 | 4 | 50.0% |
"""
FACTS = {"segments": [{"ring_range": "1-100", "total": 10, "replaced": 3},
                       {"ring_range": "101-200", "total": 8, "replaced": 4}]}


class AnswerEvidenceChecksTests(SimpleTestCase):
    def trend(self, answer, expected=None):
        return check_answer("query_tool_change_trend", answer, expected or FACTS)["failures"]

    def test_correct_independent_counts_and_ratios_pass(self):
        self.assertEqual(self.trend(TREND), [])

    def test_plausible_but_wrong_answer_is_detected(self):
        for wrong in [TREND.replace("| 3 |", "| 4 |"), TREND.replace("30.0%", "50.0%"),
                      TREND.replace("| 10 |", "| 12 |"), TREND.replace("101-200", "201-300")]:
            with self.subTest(answer=wrong):
                self.assertTrue(self.trend(wrong))

    def test_extra_cell_and_omitted_row_fail(self):
        self.assertTrue(self.trend(TREND.replace("| 30.0% |", "| 30.0% | 99 |")))
        self.assertTrue(self.trend(TREND.replace("| 101-200 | 8 | 4 | 50.0% |", "")))

    def test_single_segment_cannot_claim_stability(self):
        one = TREND.replace("| 101-200 | 8 | 4 | 50.0% |", "")
        expected = {"segments": FACTS["segments"][:1]}
        self.assertTrue(self.trend(one + "整体趋势为平稳。", expected))
        self.assertFalse(self.trend(one + "当前仅1段，无法判断跨段趋势。", expected))

    def test_manufacturer_counts_are_checked_by_name_not_number_presence(self):
        answer = "| 厂家 | 更换次数 |\n| --- | --- |\n| A | 3 |\n| B | 7 |"
        expected = {"total_records": 10, "manufacturer_replacements": {"A": 3, "B": 7}}
        self.assertFalse(check_answer("compare_manufacturer_performance", answer, expected)["failures"])
        swapped = answer.replace("A | 3", "A | 7").replace("B | 7", "B | 3")
        self.assertTrue(check_answer("compare_manufacturer_performance", swapped, expected)["failures"])

    def test_empty_result_requires_explicit_explanation(self):
        self.assertTrue(self.trend("更换率为0%，情况稳定。", {"total": 0}))
        self.assertFalse(self.trend("未找到符合条件的换刀记录。", {"total": 0}))

    def test_truncation_is_disclosed_and_first_twelve_are_present(self):
        expected = {"segments": [{"ring_range": f"{i}-{i}", "total": 1, "replaced": 0} for i in range(13)]}
        answer = "| 环段 | 记录数 | 更换次数 | 更换率 |\n| --- | --- | --- | --- |\n"
        answer += "\n".join(f"| {i}-{i} | 1 | 0 | 0.0% |" for i in range(12))
        self.assertTrue(self.trend(answer, expected))
        self.assertFalse(self.trend(answer + "\n共13项，展示前12项。", expected))
