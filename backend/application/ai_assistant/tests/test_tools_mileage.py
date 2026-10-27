import json
import math
from contextlib import ExitStack
from unittest.mock import patch

from django.test import TestCase

from application.ai_assistant import llm_service
from application.ai_assistant.answer_reporting import render_report
from application.ai_assistant.memory_service import MemorySnapshot, StoredMessage
from application.ai_assistant.tools_mileage import query_tool_mileage
from application.ai_assistant.tests import test_tools_refresh as fixtures
from application.shield.models import ToolChangeDetail


class ToolMileageTests(TestCase):
    setUpTestData = classmethod(fixtures.ToolsRefreshTests.setUpTestData.__func__)
    opening = fixtures.ToolsRefreshTests.opening
    detail = fixtures.ToolsRefreshTests.detail
    info = fixtures.ToolsRefreshTests.info
    install = fixtures.ToolsRefreshTests.install
    remove = fixtures.ToolsRefreshTests.remove
    tunnel = fixtures.ToolsRefreshTests.tunnel
    call = fixtures.ToolsRefreshTests.call

    def test_reuses_project_scoped_confirmed_segments_and_readings(self):
        first = self.opening(10, right_revolution_reading=1000, left_revolution_reading=100)
        last = self.opening(20, right_revolution_reading=2000, left_revolution_reading=300)
        installed, instance = self.install(first, self.info(), 'S1L')
        ToolChangeDetail.objects.filter(pk=installed.pk).update(manufacturer='甲厂')
        self.remove(last, instance, 'S1L')
        self.install(self.opening(100, project=self.other_project), self.info('其他项目'))
        data = self.call(query_tool_mileage, cutter_position_no='s1l', manufacturers=['甲厂'], ring_range=[20, 20])
        self.assertEqual(data['summary']['removed_count'], 1)
        self.assertEqual(data['revolution_basis']['source_share']['reading'], 1)
        self.assertEqual(data['revolution_basis']['reading_opening_count'], 2)
        position = data['position']
        self.assertEqual(position['cutter_position_no'], 'S1L')
        self.assertEqual(position['radius_mm'], 3430)
        segment = position['segments'][0]
        self.assertEqual((segment['installation_ring_no'], segment['ring_no'], segment['service_rings']), ('10', '20', 10))
        self.assertEqual(segment['km'], round(2 * math.pi * 3430 * 1200 / 1e6, 2))
        self.assertEqual(position['covered_km'], segment['km'])
        band = data['groups'][0]['bands'][0]
        self.assertNotIn('trajectories', band)
        self.assertEqual(band['cells'][0]['life_km'], {'count': 1, 'values': [segment['km']]})
        self.assertIsNone(band['cells'][0]['cost_per_km'])
        answer = render_report('tool_mileage', data, llm_service.ToolAssistant._answer_table)
        self.assertIn('## 刀具里程', answer)
        self.assertIn('### 刀位 S1L（轨迹半径', answer)
        self.assertIn('开仓读数', answer)
        self.assertNotIn('| 中位 ', answer)

    def test_estimates_quartiles_and_exclusions_are_explicit(self):
        info = self.info()
        for start in (10, 30, 50, 70, 90):
            _, instance = self.install(self.opening(start), info)
            self.remove(self.opening(start + 10), instance)
        _, instance = self.install(self.opening(110), info, '2')
        self.remove(self.opening(120), instance, '2', status='PENDING_VENDOR_FEEDBACK')
        data = self.call(query_tool_mileage, cutter_position_no='1')
        self.assertEqual(data['summary']['removed_count'], 5)
        self.assertEqual([int(row['installation_ring_no']) for row in data['position']['segments']], [10, 30, 50, 70, 90])
        self.assertTrue(any('厂家反馈未确认' == row['reason'] for row in data['excluded']))
        # 刀位 2 的待反馈段只算在刀位 2 上；问刀位 1 时不带全项目的分带表
        self.assertNotIn('厂家反馈未确认', [row['reason'] for row in data['position']['excluded']])
        answer = render_report('tool_mileage', data, llm_service.ToolAssistant._answer_table)
        self.assertNotIn('按轨迹分带和厂家统计', answer)
        self.assertNotIn('厂家反馈未确认', answer)
        other = self.call(query_tool_mileage, cutter_position_no='2')
        self.assertIn({'reason': '厂家反馈未确认', 'count': 1}, other['position']['excluded'])
        cells =[c for group in data['groups'] for band in group['bands'] for c in band['cells']]
        self.assertTrue(any(c['life_km'] and 'median' in c['life_km'] for c in cells))
        self.assertIn('里程全部按参考贯入度约 120 圈/环估算，不是实测', data['warnings'])
        self.tunnel(ring=11, counter_revolutions=100)
        mixed = self.call(query_tool_mileage)
        self.assertTrue(0 < mixed['revolution_basis']['estimated_share'] < 1)
        self.assertTrue(any('% 的圈数按参考值估算' in warning for warning in mixed['warnings']))
        for raw in ('null', '{', '{"cutter_position_no":"Y2"}', '{"manufacturers":[1]}'):
            self.assertIn('error', json.loads(query_tool_mileage(raw)))


class MileageAndFollowupRoutingTests(TestCase):
    def setUp(self):
        self.assistant = llm_service.ToolAssistant.__new__(llm_service.ToolAssistant)

    def test_mileage_keywords_precede_cost_and_multi_domain_gate(self):
        queries = ['统计各厂家刀具每公里成本和磨损率', '统计滚刀每百公里磨损',
                   '按刀位轨迹半径和刀盘圈数计算刀具里程，对比各厂家至更换里程',
                   'S1L 刀位的里程', '滚刀至更换里程按厂家对比', '厂家刀位寿命与里程',
                   '刀具走了多远', '刀盘累计圈数', '刀具 KM', '轨迹分带']
        with patch.object(self.assistant, '_named_manufacturers', return_value=[]), patch.object(llm_service, 'query_tool_mileage', return_value='{}') as tool:
            for query in queries:
                with self.subTest(query=query):
                    result = self.assistant._direct_route(query, {'project_id': 'REFRESH'})
                    self.assertEqual(result['rule_branch'], 'tool_mileage')
                    if 'S1L' in query:
                        self.assertEqual(json.loads(tool.call_args.args[0])['cutter_position_no'], 'S1L')
        for query, intent in [('统计滚刀寿命', 'group_service'), ('对比各厂家刀具的使用寿命和异常磨损率', 'manufacturer_service')]:
            self.assertEqual(self.assistant._rule_intent(query), intent)
        with patch.object(llm_service, 'trace_tool_lifecycle', return_value='{}'):
            self.assertEqual(self.assistant._direct_route('GD-TEST-0001 的里程', {'project_id': 'REFRESH'})['rule_branch'], 'tool_lifecycle')

    def test_every_continuation_label_routes_to_its_own_intent(self):
        with ExitStack() as stack:
            for name in {*llm_service._TOOL_SOURCES, 'query_data_catalog'}:
                stack.enter_context(patch.object(llm_service, name, return_value='{}'))
            stack.enter_context(patch.object(self.assistant, '_named_manufacturers', return_value=[]))
            stack.enter_context(patch.object(self.assistant, '_recent_ring_range', return_value=[388, 487]))
            for intent, label, _ in self.assistant._rule_intents():
                with self.subTest(intent=intent):
                    self.assertEqual(self.assistant._rule_intent(label), intent)
                    self.assertEqual(self.assistant._direct_route(label, {'project_id': 'REFRESH'})['rule_branch'], intent)

    def test_followups_keep_intent_filters_and_sort(self):
        cases = [('统计滚刀平均寿命和集中更换环段', '那刮刀呢', 'group_service'),
                 ('统计100环到300环的地层面积占比', '那400环到487环呢', 'stratum_area'),
                 ('找出异常磨损集中的前10个刀位，并列出异常类型', '那滚刀呢', 'cutter_position'),
                 ('统计滚刀返修进度，列出待厂家反馈、已确认、已归档的数量', '那刮刀呢', 'old_tool_repairs'),
                 ('列出需要关注但还没更换的刀，包括刀位、环号和磨损情况', '那刮刀呢', 'tool_inspections'),
                 ('对比各厂家滚刀寿命', '那刮刀呢', 'manufacturer_service'),
                 ('统计100环到300环滚刀里程', '那刮刀呢', 'tool_mileage')]
        for first, followup, intent in cases:
            with self.subTest(intent=intent):
                initial = self.assistant._prepare_query_context(first, MemorySnapshot(scope_key='test'))
                snapshot = MemorySnapshot(scope_key='test', slots=initial['memory_slots'], messages=[
                    StoredMessage(1, 'human', first, 5, metadata={'query_intent': initial['query_spec']})])
                current = self.assistant._prepare_query_context(followup, snapshot)
                self.assertEqual(self.assistant._rule_intent(current['effective_query']), intent)
                if intent == 'cutter_position':
                    self.assertEqual(current['query_spec']['sort_by'], 'abnormal')
                    self.assertIn('异常', current['effective_query'])
                if intent == 'tool_mileage':
                    self.assertEqual(current['memory_slots'], {'ring_range': [100, 300], 'tool_type': 'SCRAPER'})
        snapshot.messages[0].metadata.update(query_intent={'intent': 'unknown_old_intent'})
        current = self.assistant._prepare_query_context('那刮刀呢', snapshot)
        self.assertEqual(current['effective_query'], '那刮刀呢')
        self.assertNotIn('ring_range', current['memory_slots'])
