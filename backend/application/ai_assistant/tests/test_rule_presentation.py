import json

from django.test import SimpleTestCase

from application.ai_assistant.llm_service import ToolAssistant, _with_analysis_payload


class RulePresentationTests(SimpleTestCase):
    def setUp(self):
        self.assistant = ToolAssistant.__new__(ToolAssistant)

    def test_common_and_recent_summary_use_same_table_and_preserve_zero(self):
        data = {'total_records': 2, 'replaced_count': 0, 'replacement_rate': '0.0%',
                'wear_distribution': [{'wear_condition': None, 'count': 2}], 'top_replaced_positions': []}
        raw = json.dumps(data)
        direct = self.assistant._format_tool_change_answer(raw, [100, 200])
        structured = self.assistant._format_analysis_payload_answer('换刀数据分析', json.loads(_with_analysis_payload(raw, 'tool_change')))
        self.assertEqual(direct, structured)
        self.assertIn('实际更换 **0** 次', direct)
        self.assertIn('| 未填写 | 2 |', direct)
        self.assertNotIn('None', direct)
        self.assertNotIn('优先关注高频', direct)

    def test_empty_summary_has_no_empty_tables_or_generic_advice(self):
        result = self.assistant._format_tool_change_answer(json.dumps({'total_records': 0}))
        self.assertIn('未找到', result)
        self.assertNotIn('|', result)

    def test_ranking_shows_all_requested_fields_without_asserting_risk(self):
        data = {'total_records': 7, 'warnings': ['样本不足'], 'top_positions': [{
            'cutter_position_no': 'S1L', 'replacement_count': 3, 'tool_parent_type': 'SCRAPER',
            'wear_distribution': [{'wear_condition': '崩口', 'count': 2}],
        }]}
        answer = self.assistant._format_analysis_payload_answer('旧风险标题', data)
        self.assertTrue(answer.startswith('## 刀位更换排行'))
        self.assertIn('| S1L | 3 | 刮刀 | 崩口 2次 |', answer)
        self.assertIn('不等同于异常', answer)
        self.assertIn('提示：样本不足', answer)

    def test_opening_keeps_confirmed_and_detail_counts_separate(self):
        data = {'total_openings': 1, 'recent_records': [{
            'ring_no': '100', 'tool_change_total': 20, 'tool_change_replaced': 0,
            'count_source': 'confirmed_summary', 'replacement_rate': '0.0%', 'abnormal_rate': None,
            'detail_record_count': 122, 'detail_checked_count': 18, 'detail_replaced_count': 0,
            'warnings': ['人工确认数量与现场明细不同'],
        }]}
        answer = self.assistant._format_opening_answer(json.dumps(data))
        self.assertIn('| 100 | 暂无 | 暂无 | 暂无 | 20 | 0 | 0.0% | 已确认汇总 |', answer)
        self.assertIn('| 100 | 122 | 18 | 0 | 暂无 |', answer)
        self.assertIn('人工确认数量与现场明细不同', answer)
        self.assertIn('暂无已分类磨损记录', answer)
        self.assertNotIn('None', answer)

    def test_opening_comparison_retains_dates_and_merges_repeated_advice(self):
        records = [{
            'ring_no': str(ring), 'open_time': '2025-01-19 08:30',
            'abnormal_rate': '50.0%', 'detail_record_count': 122,
            'detail_checked_count': 100, 'detail_replaced_count': 50,
            'top_replaced_positions': ['S1L'], 'wear_distribution': {'崩口': 50},
        } for ring in [487, 443, 400]]
        answer = self.assistant._format_opening_answer(json.dumps({'total_openings': 3, 'recent_records': records}))
        self.assertEqual(answer.count('建议结合'), 1)
        self.assertIn('**487、443、400**', answer)
        self.assertEqual(answer.count('2025-01-19 08:30'), 3)
        for ring in [487, 443, 400]:
            self.assertIn(f'| {ring} | 122 | 100 | 50 | 50.0% | 高频刀位：S1L；主要磨损：崩口 50次 |', answer)
        self.assertNotIn('现场记录与核对提示', answer)

    def test_table_cell_escapes_delimiters_without_losing_zero(self):
        rows = self.assistant._answer_table(['刀位', '次数'], [['A|B\\C\n备注', 0]])
        self.assertEqual(rows[-1], '| A\\|B\\\\C 备注 | 0 |')
