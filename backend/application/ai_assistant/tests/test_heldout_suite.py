"""持出题评分器：只测纯文本规则，不连数据库、不调模型。"""

from django.test import SimpleTestCase

from application.ai_assistant.evaluation.heldout_suite import _fact, score_turn, untraceable_numbers


class HeldoutScoringTests(SimpleTestCase):
    def test_rounding_follows_decimals_written_in_answer(self):
        gold = {"facts": [_fact("更换率", 49.66), _fact("登记金额", 291768.31, "模拟厂家01")]}
        self.assertTrue(score_turn("更换率 49.7%\n| 模拟厂家01 | 29.18万元 |", gold)["correct"])
        self.assertTrue(score_turn("更换率约 50%\n模拟厂家01 登记 291,768.31 元", gold)["correct"])
        self.assertFalse(score_turn("更换率 49.5%\n模拟厂家01 登记 291,768.31 元", gold)["correct"])

    def test_anchor_must_share_line_and_is_removed_before_matching(self):
        gold = {"facts": [_fact("10号刀位异常次数", 10, "10")], "objects": ["10"]}
        self.assertTrue(score_turn("| 10 | 10 次 |", gold)["correct"])
        self.assertFalse(score_turn("10号刀位异常 8 次", gold)["correct"])
        self.assertFalse(score_turn("| 10 | 8 |\n| 12 | 10 |", gold)["correct"])

    def test_longer_wear_label_does_not_count_as_shorter_one(self):
        gold = {"facts": [_fact("崩刃", 5, "崩刃"), _fact("刀圈崩刃", 8, "刀圈崩刃")]}
        self.assertTrue(score_turn("崩刃 5 条\n刀圈崩刃 8 条", gold)["correct"])
        self.assertFalse(score_turn("刀圈崩刃 5 条\n刀圈崩刃 8 条", gold)["correct"])

    def test_alternative_reading_and_missing_objects(self):
        gold = {"facts": [_fact("平均更换", 60.33, also=[73.67])], "objects": ["S4L", "S5L"]}
        self.assertTrue(score_turn("平均 73.7 把，S4L、S5L", gold)["correct"])
        self.assertEqual(score_turn("平均 60.3 把，S4L", gold)["missing_objects"], ["S5L"])

    def test_integer_count_in_table_is_not_taken_as_average(self):
        gold = {"facts": [_fact("平均每次更换把数", 58.6, also=[73.6])]}
        table = "| 环号 | 检查数 | 更换数 |\n| --- | --- | --- |\n| 487 | 147 | 74 |"
        self.assertFalse(score_turn(table, gold)["correct"])
        self.assertTrue(score_turn("最近 5 次平均每次更换约 74 把", gold)["correct"])
        self.assertTrue(score_turn("| 口径 | 平均每次 |\n|---|---|\n| 明细 | 59 |", gold)["correct"])

    def test_order_requires_one_block_listing_all_objects_in_sequence(self):
        gold = {"facts": [_fact("A报价", 100, "甲厂"), _fact("B报价", 200, "乙厂"), _fact("C报价", 200, "丙厂")],
                "order": [["甲厂"], ["乙厂", "丙厂"]]}
        table = "| 厂家 | 报价 |\n| --- | --- |\n| 甲厂 | 100 |\n| 丙厂 | 200 |\n| 乙厂 | 200 |"
        self.assertTrue(score_turn(table, gold)["correct"])
        self.assertTrue(score_turn("最贵的是乙厂 200 元。\n" + table, gold)["correct"])
        result = score_turn("| 厂家 | 报价 |\n| --- | --- |\n| 乙厂 | 200 |\n| 甲厂 | 100 |\n| 丙厂 | 200 |", gold)
        self.assertFalse(result["correct"])
        self.assertFalse(result["order_ok"])
        self.assertNotIn("order_ok", score_turn("甲厂 100", {"facts": [_fact("A报价", 100, "甲厂")]}))

    def test_unanchored_fact_needs_indicator_word_on_line_or_header(self):
        gold = {"facts": [_fact("异常记录数", 7)]}
        self.assertFalse(score_turn("实际更换 7 次", gold)["correct"])
        self.assertTrue(score_turn("实际更换 7 次\n异常磨损 7 次", gold)["correct"])
        self.assertTrue(score_turn("| 刀位 | 异常 |\n|---|---|\n| Y3 | 7 |", gold)["correct"])

    def test_name_variants_spacing_and_short_manufacturer(self):
        gold = {"facts": [_fact("异常率", 48.68, "模拟厂家06·澄岩"), _fact("样本数", 59, "可更换式刮刀H=389")],
                "objects": ["模拟厂家06·澄岩"]}
        self.assertTrue(score_turn("| 澄岩 | 76 | 48.7% |\n| 可更换式刮刀 H=389 | 59 |", gold)["correct"])
        self.assertFalse(score_turn("| 澄岩 | 76 | 40.4% |\n| 可更换式刮刀 H=389 | 59 |", gold)["correct"])

    def test_no_data_requires_explicit_statement(self):
        gold = {"facts": [], "no_data": True}
        self.assertTrue(score_turn("库里没有库存台账，无法给出备件数量。", gold)["correct"])
        self.assertFalse(score_turn("备件还有 35 把。", gold)["correct"])

    def test_untraceable_numbers_compare_with_sources(self):
        found, missing = untraceable_numbers("更换 215 次，更换率 49.7%，平均 63.2 环", ['{"replaced": 215, "rate": 0.4966}'])
        self.assertEqual((found, missing), (3, [63.2]))
