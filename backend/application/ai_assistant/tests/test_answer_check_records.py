"""用同条件实验留存记录回放回答核对的"列全对象"误报。

问句原样取自第二至四轮记录（第四轮 U22–U32，第二、三轮 N26、T26、N50、T49），工具结果只保留核对规则会读的字段，
回答保留原来的表格或列举写法。每组同时留一个真阳性：真的漏列或写错时仍要报出。
"""
from django.test import SimpleTestCase

from application.ai_assistant.answer_check import answer_requirements, check_final_answer


def positions(spec, matched=None):
    """刀位统计工具的结果。spec 写成"刀位 更换次数 观测数"，逗号分隔，顺序同工具返回（按更换次数降序）。"""
    rows = [{"cutter_position_no": no, "replacement_count": int(replaced), "observation_count": int(observed)}
            for no, replaced, observed in (item.split() for item in spec.split(","))]
    matched = matched or len(rows)
    return {"top_positions": rows, "matched_position_count": matched, "returned_position_count": len(rows),
            "truncated": len(rows) < matched, "sort_by": "replaced"}


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(lines + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


class RecordedFalseAlarmTests(SimpleTestCase):
    def check(self, question, answer, data):
        tools = [{"result": data}]
        return check_final_answer(question, answer, answer_requirements(question, {}, tools), tools)

    def test_replaced_positions_only_count_positions_with_replacements(self):
        # 第四轮 U24：第258环刮刀观测 32 个刀位，实际更换的是左侧 S4L–S19L 16 个。
        question = "请问第258环开仓时，依据有效刀位上的换刀明细，刮刀实际更换了哪些刀位？请全部列出并给出总数。"
        left = [f"S{n}L" for n in range(4, 20)]
        data = positions(", ".join([f"{no} 1 1" for no in left] + [f"S{n}R 0 1" for n in range(4, 20)]))
        wear = "断裂 崩刃 崩刃 脱落 正常 崩刃 严重磨损 正常 正常 严重磨损 正常 正常 脱落 正常 正常 脱落".split()
        note = ("\n\n**总数：16个刀位，16次更换。**\n\n- 右侧 S4R–S19R 这16个刀位在第258环都有观测记录，但更换次数为0。"
                "右侧记录中，S5R、S9R、S19R 为偏磨，S16R、S18R 为中度磨损。")
        answer = table(["序号", "刀位", "该刀位记录中的磨损描述"], [(i + 1, no, w) for i, (no, w) in enumerate(zip(left, wear))])
        self.assertEqual(self.check(question, answer + note, data), [])
        # 只列了一半的更换刀位，正文提到的右侧未更换刀位不能顶数。
        half = table(["序号", "刀位", "该刀位记录中的磨损描述"], [(i + 1, no, w) for i, (no, w) in enumerate(zip(left[:8], wear))])
        self.assertEqual(self.check(question, half + note, data), ["刀位只列出 8 个，查询结果共有 16 个。"])
        # 问未更换的刀位仍不查列全。
        self.assertEqual(self.check("第258环开仓时，刮刀没有更换的刀位全部列出。", half, data), [])
        # 回答把 32 个刀位都列上、用一列标是否更换时，漏掉的更换刀位不能靠未更换的刀位顶数（第四轮 U24 补全后的写法）。
        everything = table(["序号", "刀位", "是否更换"], [(i + 1, no, "是" if no in left else "否")
                                                       for i, no in enumerate(left[:-1] + [f"S{n}R" for n in range(4, 20)])])
        self.assertEqual(self.check(question, everything, data), ["刀位只列出 15 个，查询结果共有 16 个。"])
        self.assertEqual(self.check(question, everything.replace("| 1 | S4L |", "| 1 | 第 S4L 号 |"), data),
                         ["刀位只列出 15 个，查询结果共有 16 个。"])

    def test_replaced_positions_listed_in_cells_or_prose(self):
        # 第四轮 U22：第151环观测 106 个刀位，更换 52 个；回答在单元格或正文里用顿号列举。
        question = "第151环那次开仓，按有效刀位上的换刀明细看，实际换了哪些刀位？全部列出来，总共几个。"
        disc = [str(n) for n in range(1, 44, 2)] + [str(n) for n in range(61, 80, 2)] + ["80B"]
        scraper = [f"S{n}R" for n in range(1, 20)]
        # 未更换的 54 个刀位只影响全集大小，按回答的说明补齐：左侧刮刀、80A、中心刀位和其余滚刀刀位。
        kept = [f"S{n}L" for n in range(1, 20)] + ["80A", "Y1", "Y3", "Y5"] + [str(n) for n in range(2, 63, 2)]
        data = positions(", ".join([f"{no} 1 1" for no in disc + scraper] + [f"{no} 0 1" for no in kept]))
        cells = table(["刀型", "更换刀位", "数量"], [("DISC", "、".join(disc), 33), ("SCRAPER", "、".join(scraper), 19),
                                                   ("合计", "—", "**52**")])
        prose = ("**结论**：第151环这次开仓在有效刀位上**实际更换了52个刀位**，每个刀位各更换1次。\n\n"
                 f"DISC（33个）：  \n{'、'.join(disc)}\n\nSCRAPER（19个）：  \n{'、'.join(scraper)}\n\n"
                 "- 本次未更换的包括左侧刮刀 S1L–S19L 全部、中心刀位 80A 及 Y1/Y3/Y5 等。")
        replaced = disc + scraper
        side_by_side = table(["刀位", "记录磨损"] * 3,
                             [sum(([no, "正常"] for no in replaced[row::18]), []) + ["", ""] * (3 - len(replaced[row::18]))
                              for row in range(18)])
        for answer in (cells, prose, side_by_side):
            with self.subTest(answer=answer[:12]):
                self.assertEqual(self.check(question, answer, data), [])
        missing = table(["刀型", "更换刀位", "数量"], [("DISC", "、".join(disc), 33)])
        self.assertEqual(self.check(question, missing, data), ["刀位只列出 33 个，查询结果共有 52 个。"])

    def test_side_by_side_tables_are_read_block_by_block(self):
        # 第四轮 U31：38 个刮刀刀位，回答把表并排成两到三组。
        question = "请统计第200环至第487环期间刮刀每个刀位各更换了几次，全部刀位均需列出。"
        counts = {"S4L": (5, 8), "S5L": (5, 8), "S6L": (5, 8), "S15L": (5, 8), "S16L": (5, 8), "S17L": (5, 8),
                  "S1L": (4, 8), "S2L": (4, 7), "S3L": (4, 7), "S7L": (4, 7), "S8L": (4, 7), "S9L": (4, 7),
                  "S9R": (4, 8), "S10L": (4, 8), "S10R": (4, 8), "S11L": (4, 8), "S11R": (4, 8), "S12L": (4, 8),
                  "S13L": (4, 7), "S14L": (4, 7), "S18L": (4, 7), "S19L": (4, 7), "S1R": (3, 7), "S2R": (3, 7),
                  "S3R": (3, 7), "S4R": (3, 8), "S5R": (3, 8), "S6R": (3, 8), "S7R": (3, 7), "S8R": (3, 7),
                  "S12R": (3, 7), "S13R": (3, 7), "S14R": (3, 7), "S15R": (3, 8), "S16R": (3, 8), "S17R": (3, 8),
                  "S18R": (3, 7), "S19R": (3, 7)}
        data = positions(", ".join(f"{no} {r} {o}" for no, (r, o) in counts.items()))
        names = [f"S{n}{side}" for n in range(1, 20) for side in "LR"]
        blocks = [names[:16], names[16:32], names[32:]]
        three = table(["刀位", "更换次数"] * 3, [sum(([b[i], counts[b[i]][0]] if i < len(b) else ["", ""] for b in blocks), [])
                                              for i in range(16)])
        pairs = [(f"S{n}L", f"S{n}R") for n in range(1, 20)]
        two = table(["刀位", "更换次数", "观测数"] * 2, [(left, *counts[left], right, *counts[right]) for left, right in pairs])
        self.assertEqual(self.check(question, three, data), [])
        self.assertEqual(self.check(question, two, data), [])
        # 右侧一格写错、少一行，仍按各自的刀位报出。
        self.assertEqual(self.check(question, two.replace("| S9R | 4 | 8 |", "| S9R | 5 | 8 |"), data),
                         ["“更换次数”写的是 5，查询结果是 4。"])
        self.assertEqual(self.check(question, two.rsplit("\n", 1)[0], data), ["刀位只列出 36 个，查询结果共有 38 个。"])

    def test_old_tools_of_one_named_position(self):
        # 第四轮 U26–U28：问一个刀位换下的旧刀，要列全的是旧刀，问句点名的刀位只是查询条件。
        tools = [("GGD-TEST-1049", 400), ("GGD-TEST-0641", 339), ("GGD-TEST-0441", 218),
                 ("GGD-TEST-0241", 151), ("GGD-TEST-0041", 67), ("BASE-GGD-S5R", 15)]
        for position, question in (
            ("S5R", "S5R刀位换下的旧刀总共几把？逐把列出旧刀编号和换下时的环号。"),
            ("12", "设备这边要追溯一下，12号刀位前前后后换下来的旧刀一共几把？每把的旧刀编号和啥时候、第几环换下来的，逐把列一下。"),
            ("Y3", "麻烦查一下Y3号刀位，所有换下来的旧刀一共有几把？每一把的旧刀编号、在第几环换下来的，一把一把列出来。"),
        ):
            with self.subTest(position=position):
                records = [{"ring_no": ring, "cutter_position_no": position, "old_tool_number": number} for number, ring in tools]
                data = {"scope": {"cutter_position_no": position, "record_count": 6}, "records": records,
                        "position_counts": [{"cutter_position_no": position, "count": 6,
                                             "records": [{"old_tool_number": n, "ring_no": r} for n, r in tools]}]}
                rows = [(i + 1, number, ring) for i, (number, ring) in enumerate(reversed(tools))]
                self.assertEqual(self.check(question, table(["序号", "旧刀编号", "换下环号"], rows), data), [])
                self.assertEqual(self.check(question, table(["序号", "旧刀编号", "换下环号"], rows[:4]), data),
                                 ["旧刀只列出 4 个，查询结果共有 6 个。"])

    def test_tied_top_positions_only_require_the_tie(self):
        # 第二轮 N26、第三轮 T26：问并列更换最多的刀位，要列全的是并列第一的 6 个，不是全部 38 个。
        top = "S4L S5L S6L S15L S16L S17L".split()
        rest = ("S1L 4 7, S2L 4 6, S3L 4 6, S7L 4 6, S8L 4 6, S9L 4 6, S10L 4 7, S11L 4 7, S12L 4 7, S13L 4 6, "
                "S14L 4 6, S18L 4 6, S19L 4 6, S9R 3 7, S10R 3 7, S11R 3 7, S1R 2 6, S2R 2 6, S3R 2 6, S4R 2 7, "
                "S5R 2 7, S6R 2 7, S7R 2 6, S8R 2 6, S12R 2 6, S13R 2 6, S14R 2 6, S15R 2 7, S16R 2 7, S17R 2 7, "
                "S18R 2 6, S19R 2 6")
        data = positions(", ".join(f"{no} 5 7" for no in top) + ", " + rest)
        question = "第250至487环，刮刀更换次数最多的是哪些刀位？如有并列请全部列出，并注明各自更换次数。"
        note = "\n\n其余刀位均不超过4次：有13个刀位各4次（S1L、S2L、S3L、S7L–S14L、S18L、S19L），3个刀位各3次（S9R、S10R、S11R）。"
        answer = table(["刀位", "更换次数", "观测次数"], [(no, 5, 7) for no in top])
        self.assertEqual(self.check(question, answer + note, data), [])
        self.assertEqual(self.check(question, table(["刀位", "更换次数", "观测次数"], [(no, 5, 7) for no in top[:4]]) + note, data),
                         ["刀位只列出 4 个，查询结果共有 6 个。"])
        # 第二轮 N26 hybrid 的写法：排名表顺带列了第 7 名以后的刀位，并列第一少一个仍要报出。
        ranked = table(["排名", "刀位", "更换次数"], [("并列第1", no, 5) for no in top[:5]] +
                       [("并列第7", no, 4) for no in "S1L S2L S3L S7L S8L S9L".split()])
        self.assertEqual(self.check(question, ranked, data), ["刀位只列出 5 个，查询结果共有 6 个。"])
        # 倒装问法"哪些刀位……最多"同样只要求并列第一的刀位。
        inverted = "第250至487环，哪些刮刀刀位更换次数最多？有并列请全部列出。"
        self.assertEqual(self.check(inverted, answer + note, data), [])
        self.assertEqual(self.check(inverted, table(["刀位", "更换次数"], [(no, 5) for no in top[:4]]), data),
                         ["刀位只列出 4 个，查询结果共有 6 个。"])
        # T26：只返回了前 20 个刀位（共 38 个），并列第一同样是 6 个。
        truncated = positions(", ".join(f"{no} 8 14" for no in top) + ", " + rest.replace(" 4 ", " 7 "), matched=38)
        truncated["top_positions"] = truncated["top_positions"][:20]
        question = "请列出第1环至第487环范围内刮刀更换次数最多的刀位，如有并列请全部列出，并注明各自的更换次数。"
        self.assertEqual(self.check(question, table(["刀位", "更换次数"], [(no, 8) for no in top]), truncated), [])

    def test_count_questions_do_not_require_listing(self):
        # 第二轮 N50、第三轮 T49："所有/全部"只是限定范围，问的是把数或金额。
        bearing = {"scope": {"components": ["轴承"], "record_count": 24},
                   "records": [{"old_tool_number": f"GD-TEST-{n:04d}", "cutter_position_no": "14"} for n in range(20)]}
        answer = table(["部件", "旧刀记录数", "失效原因分布"], [("轴承失效", "**24 把**", "疲劳损坏 24")])
        self.assertEqual(self.check("所有旧刀里面，轴承失效的有几把？刀圈有损坏的有几把？", answer, bearing), [])
        scraper = {"scope": {"tool_type": "SCRAPER", "record_count": 256},
                   "records": [{"old_tool_number": "GGD-TEST-1344", "cutter_position_no": "S1L"}]}
        amount = "厂家已确认与已归档的旧刀返修登记金额合计 **327,492.70 元**，对应 **549 条**返修记录。"
        self.assertEqual(self.check("全部刀具的旧刀返修，厂家已确认的连同已归档的一起，登记金额总共是多少？", amount, scraper), [])
        # 第一轮 H50、第二轮 N45：按状态分别计数，"各/分别"指前面列举的状态。
        status = table(["状态", "旧刀数"], [("待厂家反馈", 274), ("已确认", 274), ("已归档", 275)])
        for question in ("看下全部旧刀返修的进度，待厂家反馈、已确认、已归档分别有多少？",
                         "所有刀具的旧刀返修按状态统计一下：待厂家反馈、已确认、已归档各多少把？"):
            with self.subTest(question=question):
                self.assertEqual(self.check(question, status, scraper), [])
        # 要逐把列出、或"全部刀位分别换了多少次"这样按对象分别给数时照样查。
        self.assertEqual(self.check("所有轴承失效的旧刀逐把列出编号", answer, bearing), ["旧刀只列出 0 个，查询结果共有 24 个。"])
        self.assertEqual(self.check("全部刀位分别更换了多少次？", table(["刀位", "更换次数"], [("S4L", 1)]),
                                    positions("S4L 1 1, S5L 1 1")), ["刀位只列出 1 个，查询结果共有 2 个。"])
        # 单说"是多少"问的是每个对象的值，不是个数。
        self.assertEqual(self.check("全部轴承失效旧刀的编号是多少？", table(["旧刀编号", "刀位"], [("GD-TEST-0000", "14")]), bearing),
                         ["旧刀只列出 1 个，查询结果共有 24 个。"])
        models = {"service_by_model": [{"tool_type_name": f"型号{n}", "avg_service_rings": 100 + n} for n in range(5)]}
        self.assertEqual(self.check("所有型号的平均服役环数是多少？", table(["型号", "平均服役环数"], [("型号0", 100), ("型号1", 101)]),
                                    models), ["型号只列出 2 个，查询结果共有 5 个。"])
