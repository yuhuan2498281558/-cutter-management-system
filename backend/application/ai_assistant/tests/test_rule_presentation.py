import json

from django.test import SimpleTestCase

from application.ai_assistant.llm_service import ToolAssistant, _with_analysis_payload
from application.ai_assistant.answer_reporting import render_report, requested_sections


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
            'top_replaced_positions': [{'cutter_position_no': 'S1L', 'count': 2}], 'wear_distribution': {'崩口': 50},
        } for ring in [487, 443, 400]]
        answer = self.assistant._format_opening_answer(json.dumps({'total_openings': 3, 'recent_records': records}))
        self.assertEqual(answer.count('建议结合'), 1)
        self.assertIn('**487、443、400**', answer)
        self.assertEqual(answer.count('2025-01-19 08:30'), 3)
        for ring in [487, 443, 400]:
            self.assertIn(f'| {ring} | 122 | 100 | 50 | 50.0% | 更换较多的刀位：S1L（2）；主要磨损：崩口 50次 |', answer)
        self.assertNotIn('现场记录与核对提示', answer)
        records[0]['revolutions_since_previous'] = 1200
        answer = self.assistant._format_opening_answer(json.dumps({'total_openings': 3, 'recent_records': records}))
        self.assertIn('刀盘圈数（距上次读数）', answer)
        self.assertIn('| 1200 |', answer)

    def test_table_cell_escapes_delimiters_without_losing_zero(self):
        rows = self.assistant._answer_table(['刀位', '次数'], [['A|B\\C\n备注', 0]])
        self.assertEqual(rows[-1], '| A\\|B\\\\C 备注 | 0 |')

    def test_narrow_opening_count_sources_and_relevant_warnings(self):
        difference = '人工汇总数和明细统计数不同：人工汇总按整仓填写，明细只统计 122 个有效刀位上已检查或已更换的记录。'
        incomplete = '检查数或更换数不完整或不一致，暂不计算更换率'
        draft_warning = '开仓汇总尚未确认，当前明细统计可能继续变化'
        confirmed = {'ring_no': '100', 'count_source': 'confirmed_summary', 'tool_change_total': 20,
                     'tool_change_replaced': None, 'warnings': [difference, incomplete]}
        draft = {'ring_no': '200', 'count_source': 'detail_draft', 'tool_change_total': 2,
                 'tool_change_replaced': 1, 'warnings': [draft_warning]}
        cases = [([confirmed], '整仓检查、更换数采用确认汇总；异常率以有效刀位已分类观测数为分母。'),
                 ([draft], '检查、更换数取现场明细（开仓汇总尚未确认）；异常率以有效刀位已分类观测数为分母。'),
                 ([confirmed, draft], '检查、更换数按各仓的数量来源取值，见"数量来源"列；异常率以有效刀位已分类观测数为分母。')]
        for records, note in cases:
            with self.subTest(note=note):
                data = {'total_openings': len(records), 'recent_records': records}
                sections = requested_sections('opening', '最近5次草稿开仓的检查数和更换数')
                answer = render_report('opening', data, self.assistant._answer_table, {'sections': sections})
                self.assertIn(note, answer)
                for row in records:
                    for warning in row['warnings']:
                        self.assertIn(f"环号 {row['ring_no']}：{warning}", answer)
                if len(records) == 2:
                    self.assertIn('| 数量来源 |', answer)
                    self.assertIn('| 已确认汇总 |', answer)
                    self.assertIn('| 现场明细（未确认） |', answer)
                else:
                    self.assertNotIn('| 数量来源 |', answer)
        answer = render_report('opening', data, self.assistant._answer_table, {'sections': {'interval'}})
        for warning in (difference, incomplete, draft_warning):
            self.assertNotIn(warning, answer)
        # 几仓共有的提示只写一次，环号并在一起
        data = {'total_openings': 2, 'recent_records': [confirmed, {**confirmed, 'ring_no': '300', 'warnings': [difference]}]}
        answer = render_report('opening', data, self.assistant._answer_table, {'sections': requested_sections('opening', '最近2次开仓的检查数和更换数')})
        self.assertEqual(answer.count(difference), 1)
        self.assertIn(f"环号 100、300：{difference}", answer)

    def test_repair_status_and_scrap_sections_are_independent(self):
        data = {'status_counts': {'PENDING_VENDOR_FEEDBACK': 7, 'CONFIRMED': 5, 'CLOSED': 3},
                'scrapped_count': 2, 'scrap_suggestion_count': 1}
        for question, show_status in [('旧刀返修待厂家反馈、已确认、已归档和报废各多少', True),
                                      ('统计已经报废了多少把刀，另列待厂家确认的报废建议', False)]:
            with self.subTest(question=question):
                answer = render_report('old_tool_repairs', data, self.assistant._answer_table, {'question': question})
                self.assertIn('已报废：2 把。', answer)
                self.assertIn('报废建议：1 把，仍待厂家反馈。', answer)
                if show_status:
                    self.assertIn('返修状态：待厂家反馈 7 条；已确认 5 条；已归档 3 条。', answer)
                else:
                    self.assertNotIn('返修状态：', answer)

    def test_manufacturer_unconfirmed_and_in_service_sections_keep_their_basis(self):
        warnings = ['在役数量按当前末次安装统计，不受拆下环段限制。',
                    '待反馈及无法组成确认配对的数量按整个候选范围统计，无法可靠按原安装厂家筛选。',
                    '缺确认身份数量也包括安装记录不完整或配对冲突的记录，不能计入平均寿命。']
        data = {'unconfirmed': {'pending_feedback_count': 7, 'no_confirmed_identity_count': 2, 'in_service_count': 5},
                'warnings': warnings}
        for keyword in ('待反馈', '未确认', '缺确认', '身份', '在役', '完整报告'):
            with self.subTest(keyword=keyword):
                answer = render_report('manufacturer_service', data, self.assistant._answer_table,
                                       {'question': f'统计各厂家刀具{keyword}'})
                self.assertIn('未确认：待厂家反馈 7 条；缺确认身份或配对不完整 2 条。', answer)
                self.assertIn('当前在役：5 把。', answer)
                for warning in warnings:
                    self.assertIn(warning, answer)
        for question in ('对比各厂家刀具的使用寿命和异常磨损率', '分析主要厂家的异常磨损类型'):
            answer = render_report('manufacturer_service', data, self.assistant._answer_table, {'question': question})
            self.assertNotIn('未确认：', answer)
            self.assertNotIn('当前在役：', answer)
            for warning in warnings:
                self.assertNotIn(warning, answer)

    def test_table_cell_rounds_float_tails(self):
        rows = self.assistant._answer_table(['参数', '平均值', '最大值'], [['总推力', 11918.614430000001, 12787.1351]])
        self.assertEqual(rows[-1], '| 总推力 | 11918.614 | 12787.135 |')

    def test_narrow_change_opening_manufacturer_and_repair_reports(self):
        query = '统计换刀更换率，并列出主要更换刀位'
        answer = self.assistant._format_tool_change_answer(json.dumps({'total_records': 10, 'replaced_count': 2,
            'wear_distribution': [{'wear_condition': '偏磨', 'count': 3}],
            'top_replaced_positions': [{'cutter_position_no': '1', 'replacement_count': 2}]}), sections=requested_sections('tool_change', query))
        self.assertIn('实际更换 **2** 次', answer)
        self.assertIn('| 1 | 2 |', answer)
        self.assertNotIn('磨损分布', answer)
        data = {'total_openings': 15, 'avg_rings_between_openings': 32.5, 'avg_opening_duration_hours': 7.5,
                'recent_avg_rings_between_openings': 34, 'recent_avg_opening_duration_hours': 7.7,
                'recent_records': [{'ring_no': 487, 'last_ring_no': 443, 'rings_between_openings': 44, 'revolutions_since_previous': 100}]}
        for query in ('统计平均多少环开一次仓，并列出最近开仓间隔', '列出最近10次开仓中已分类异常率较高的开仓'):
            answer = render_report('opening', data, self.assistant._answer_table, {'sections': requested_sections('opening', query)})
            self.assertIn('最近 1 次：平均间隔 34 环，平均开仓时长 7.7 小时。', answer)
            self.assertIn('全部 15 次：平均间隔 32.5 环，平均开仓时长 7.5 小时。', answer)
            self.assertIn('刀盘圈数（距上次读数）', answer)
            self.assertNotIn('数据核对', answer)
        data['efficiency_all'] = {'opening_count': 15, 'check_minutes_per_tool': 3.1, 'replace_minutes_per_tool': 3.8}
        data['efficiency_recent'] = {'opening_count': 1, 'check_minutes_per_tool': 5, 'replace_minutes_per_tool': 10}
        for recent, count, minutes in ((False, 15, '3.1'), (True, 1, '5.0')):
            answer = self.assistant._format_opening_efficiency_answer(json.dumps(data), recent)
            self.assertIn(f"按{'最近' if recent else '全部'} {count} 次开仓统计", answer)
            self.assertIn(f'平均检查一把刀约 {minutes} 分钟', answer)
        manufacturer = {'service_by_install_manufacturer': [{'manufacturer': '甲厂', 'confirmed_segment_count': 5,
                         'avg_service_rings': 10, 'classified_count': 5, 'abnormal_rate_pct': 20, 'abnormal_types': {'偏磨': 1}}],
                        'supply_by_new_manufacturer': [{'manufacturer': '甲厂', 'install_count': 10, 'registered_amount_yuan': 1000}]}
        answers = [render_report('manufacturer_service', manufacturer, self.assistant._answer_table, {'question': q})
                   for q in ('对比各厂家刀具的使用寿命和异常磨损率', '分析主要厂家的异常磨损类型')]
        self.assertIn('平均服役环数', answers[0])
        self.assertIn('各厂家异常类型分布', answers[1])
        self.assertNotEqual(*answers)
        for answer in answers:
            self.assertNotIn('供货次数', answer)
        repairs = {'scrapped_count': 2, 'scrap_suggestion_count': 3, 'registered_repair_amount': {'confirmed_yuan': 10, 'pending_yuan': 99},
                   'failure_reasons': [{'component': c, 'label': '损坏', 'record_count': 1} for c in ('轴承', '刀圈', '刀毂')],
                   'records': [{'old_tool_number': 'SCRAP-1', 'disposition': 'SCRAP'}, {'old_tool_number': 'REPAIR-1', 'disposition': 'REPAIRABLE'}]}
        for query in ('统计旧刀返修进度，列出待厂家反馈、已确认、已归档的数量', '统计已经报废了多少把刀，还有待厂家确认的报废建议', '统计已确认的返修登记了多少钱'):
            answer = render_report('old_tool_repairs', repairs, self.assistant._answer_table, {'question': query})
            self.assertNotIn('返修明细', answer)
            if '已确认的返修' in query:
                self.assertNotIn('99', answer)
        answer = render_report('old_tool_repairs', repairs, self.assistant._answer_table, {'question': '列出报废旧刀名单'})
        self.assertIn('SCRAP-1', answer)
        self.assertNotIn('REPAIR-1', answer)
        answer = render_report('old_tool_repairs', repairs, self.assistant._answer_table, {'question': '统计旧刀的部件失效原因，列出轴承、刀圈等损坏数量'})
        for component in ('轴承', '刀圈', '刀毂'):
            self.assertIn(component, answer)
        self.assertIn('原因计数不等于刀数', answer)
        inspections = {'attention_not_replaced': {'record_count': 1, 'records': [{'ring_no': 10, 'cutter_position_no': 'S1L'}]}}
        answer = render_report('tool_inspections', inspections, self.assistant._answer_table, {'question': '统计需关注未更换的数量'})
        self.assertNotIn('需关注未更换明细', answer)
        answer = render_report('tool_inspections', inspections, self.assistant._answer_table, {'question': '列出需关注未更换的名单'})
        self.assertIn('需关注未更换明细', answer)
