import json

from django.test import SimpleTestCase

from application.ai_assistant.answer_reporting import render_abnormal_cause, render_report
from application.ai_assistant.llm_service import ToolAssistant


class AnswerReportingTests(SimpleTestCase):
    def setUp(self):
        self.assistant = ToolAssistant.__new__(ToolAssistant)
        self.table = self.assistant._answer_table

    def test_change_trend_keeps_counts_and_does_not_call_one_sample_stable(self):
        answer = self.assistant._format_trend_answer(json.dumps({
            'interval': 100, 'ring_range': '100-199', 'trend': '平稳',
            'segments': [{'ring_range': '100-199', 'total': 8, 'replaced': 2, 'replacement_rate': '25.0%'},
                         {'ring_range': '200-299', 'total': 0, 'replaced': 0, 'replacement_rate': '0%'}],
            'warnings': ['须核对停机记录'],
        }))
        self.assertIn('| 100-199 | 8 | 2 | 25.0% |', answer)
        self.assertIn('| 200-299 | 0 | 0 | 暂无（无有效样本） |', answer)
        self.assertIn('有效分段不足 2 个', answer)
        self.assertNotIn('整体趋势为平稳', answer)
        self.assertIn('不是每百环换刀频率', answer)
        self.assertIn('须核对停机记录', answer)

    def test_more_than_twelve_segments_declares_display_limit(self):
        answer = self.assistant._format_trend_answer(json.dumps({'interval': 50, 'segments': [
            {'ring_range': f'{i * 50}-{i * 50 + 49}', 'total': 4, 'replaced': i % 4, 'replacement_rate': f'{i % 4 * 25}%'}
            for i in range(13)
        ]}))
        self.assertIn('共 13 项，展示前 12 项', answer)
        self.assertNotIn('| 600-649 |', answer)
        self.assertIn('末个有效段（600-649）', answer)

    def test_manufacturer_unknown_denominator_is_not_zero_risk_and_no_quality_claim(self):
        data = {'total_records': 12, 'manufacturer_count': 2, 'manufacturers': [
            {'manufacturer': '甲', 'replaced_count': 3, 'normal_wear_count': 0, 'abnormal_wear_count': 0, 'unclassified_wear_count': 3, 'abnormal_rate_denominator': 0, 'abnormal_rate_pct': 0.0, 'avg_cost_per_change_yuan': None},
            {'manufacturer': '乙', 'replaced_count': 4, 'normal_wear_count': 4, 'abnormal_wear_count': 0, 'unclassified_wear_count': 0, 'abnormal_rate_denominator': 4, 'abnormal_rate_pct': 0.0, 'avg_cost_per_change_yuan': 0},
        ], 'highlights': ['甲综合表现相对更好'], 'warnings': [f'限制{i}' for i in range(6)]}
        answer = self.assistant._format_analysis_payload_answer('厂家性能对比', data, {'ring_range': [100, 300], 'tool_type': 'DISC'})
        self.assertIn('| 甲 | 3 | 0 | 0 | 3 | 暂无（无有效样本） | 暂无 |', answer)
        self.assertIn('| 乙 | 4 | 4 | 0 | 0 | 0% | 0 |', answer)
        self.assertNotIn('综合表现相对更好', answer)
        self.assertIn('100–300 环 · 滚刀', answer)
        self.assertTrue(all(f'限制{i}' in answer for i in range(6)))

    def test_stratum_overlap_is_not_a_distinct_change_count_or_cause(self):
        data = {'top_positions': [{'position': '30', 'total': 5, 'by_stratum': {'地层甲': 3, '地层乙': 2}}]}
        answer = self.assistant._format_position_stratum_answer(json.dumps(data), {'ring_range': [100, 300]})
        self.assertIn('| 30 | 5 | 地层甲 3次、地层乙 2次 |', answer)
        self.assertIn('合计不一定等于', answer)
        self.assertNotIn('total越高', answer)
        distribution = self.assistant._format_stratum_distribution_answer(json.dumps({'total_rings': 2, 'stratum_distribution': {'甲': 2, '乙': 2}}))
        self.assertIn('各类计数可以重叠', distribution)

    def test_tunneling_missing_metrics_do_not_crash_or_claim_normal(self):
        for method in ('_format_tunneling_summary_answer', '_format_tunneling_anomaly_answer'):
            answer = getattr(self.assistant, method)(json.dumps({'total_records': 2, 'ring_range': [4, 9], 'metrics': {
                'thrust': {'avg': 0, 'min': 0, 'max': 0}, 'torque': {'avg': None, 'min': None, 'max': None},
            }, 'anomaly_fields': [], 'recent_records': []}))
            self.assertIn('| 总推力 | kN | 0 | 0 | 0 |', answer)
            self.assertIn('| 刀盘扭矩 | kNm | 暂无 | 暂无 | 暂无 |', answer)
            self.assertNotIn('None', answer)
            self.assertNotIn('未发现明显突出的掘进参数峰值', answer)

    def test_single_ring_time_rows_label_sample_points_and_preserve_missing_data(self):
        answer = self.assistant._format_tunneling_trend_answer(json.dumps({'total_records': 2, 'interval': 50, 'trend': '稳定', 'segments': [
            {'ring_range': '123', 'segment_index': 1, 'segment_count': 2, 'count': 60, 'avg_thrust': 0, 'avg_penetration': None, 'end_time': '2026-01-01T10:00:00'},
            {'ring_range': '123', 'segment_index': 2, 'segment_count': 2, 'count': 60, 'avg_penetration': None, 'start_time': '2026-01-01T11:00:00'},
        ]}))
        self.assertIn('按单环内时间顺序分段统计', answer)
        self.assertIn('| 环段 | 采样点数 |', answer)
        self.assertIn('第 1/2 段 | 60 | 0 |', answer)
        self.assertIn('有效分段不足 2 个', answer)
        self.assertIn('间隔约 60 分钟', answer)
        self.assertNotIn('None', answer)

    def test_recommendation_keeps_insufficient_models_without_reliable_inventory_claim(self):
        answer = self.assistant._format_recommend_tools_answer(json.dumps({'tool_model_count': 2, 'ranked_count': 0,
            'recommendations': [], 'insufficient_evidence': [{'tool_type_name': '型号甲', 'installed_count': 2, 'completed_service_count': 0}],
            'criteria': {'ring_range': [100, 300], 'min_samples': 3}, 'warnings': ['只有未完成服役样本'],
        }))
        self.assertIn('| 型号甲 | 2 | 0 |', answer)
        self.assertIn('暂无满足排名条件', answer)
        self.assertIn('只有未完成服役样本', answer)
        self.assertNotIn('库存 0', answer)

    def test_lifecycle_preserves_machine_identity_and_uncertain_service(self):
        answer = self.assistant._format_tool_performance_answer(json.dumps({'tools': [
            {'tool_number': 'GD-TEST-1201', 'shield_machine_id': 1, 'tool_uid': 'UID-A', 'status': '已拆下', 'install_ring_no': 100, 'removal_ring_no': 200, 'service_rings': None, 'install_ring_inferred': True, 'inspection_count': 0, 'abnormal_inspection_count': 0},
            {'tool_number': 'GD-TEST-1201', 'shield_machine_id': 2, 'tool_uid': 'UID-B', 'status': '在役', 'install_ring_no': 0},
        ], 'not_found': ['MISSING-1'], 'warnings': ['需核对旧刀身份']}))
        self.assertIn('机器 1；实例 UID-A', answer)
        self.assertIn('机器 2；实例 UID-B', answer)
        self.assertIn('暂不给出数值', answer)
        self.assertIn('MISSING-1', answer)
        self.assertIn('需核对旧刀身份', answer)
        self.assertNotIn('None', answer)

    def test_composite_source_scopes_and_all_warnings_remain_visible(self):
        answer = render_abnormal_cause(
            {'total_records': 10, 'replaced_count': 2, 'replacement_rate': '20%', 'warnings': ['换刀限制']},
            {'stratum_analysis': [], 'warnings': ['缺地层']},
            {'ring_range': [100, 300], 'total_records': 0, 'warnings': ['缺掘进']},
            {'recent_records': [{'ring_no': 200, 'tool_change_replaced': 147, 'count_source': 'confirmed_summary', 'detail_record_count': 122, 'abnormal_rate': None, 'warnings': ['确认量不同']}]},
            {'ring_range': [100, 300], 'tool_type': 'DISC'}, self.table,
        )
        self.assertIn('100–300 环 · 滚刀', answer)
        self.assertIn('100–300 环 · 全部刀具；整仓数量', answer)
        self.assertIn('查询/分段环号范围', answer)
        self.assertNotIn('实际数据环号', answer)
        self.assertTrue(all(value in answer for value in ['换刀限制', '缺地层', '缺掘进', '确认量不同']))
        self.assertNotIn('说明异常不是单条记录噪声', answer)
        self.assertNotIn('None', answer)

    def test_all_report_error_states_keep_failure_and_warnings(self):
        for kind in ('change_trend', 'manufacturer', 'stratum_distribution', 'stratum_wear', 'position_stratum', 'tunneling_summary', 'tunneling_trend', 'tunneling_anomaly', 'tunneling_correlation', 'recommendation', 'performance'):
            with self.subTest(kind=kind):
                answer = render_report(kind, {'error': '数据库不可用', 'warnings': ['尚未取得结果']}, self.table)
                self.assertIn('查询失败：数据库不可用', answer)
                self.assertIn('尚未取得结果', answer)
                self.assertNotIn('None', answer)

    def test_pure_tunneling_and_geology_scopes_do_not_claim_tool_type_filter(self):
        for kind in ('stratum_distribution', 'tunneling_summary', 'tunneling_trend', 'tunneling_anomaly', 'tunneling_correlation'):
            answer = render_report(kind, {}, self.table, {'ring_range': [100, 300], 'tool_type': 'DISC'})
            scope_line = next(line for line in answer.splitlines() if line.startswith('分析范围：'))
            self.assertIn('100–300 环', scope_line)
            self.assertNotIn('刀具', scope_line)
            self.assertNotIn('滚刀', scope_line)
