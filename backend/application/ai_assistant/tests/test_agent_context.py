"""模型视图与原始记录隔离。"""
import json
from unittest.mock import patch

from django.test import SimpleTestCase
from langchain_core.prompts import ChatPromptTemplate

from application.ai_assistant import llm_service as service
from application.ai_assistant.agent_views import AGENT_PAGE_SIZE, agent_view


def _json(value):
    return json.dumps(value, ensure_ascii=False)


_PAGED = {
    'query_cutter_position_stats', 'query_tool_change_trend',
    'query_position_stratum_impact', 'query_tunneling_anomaly',
    'query_tunneling_wear_correlation', 'query_tool_inspections',
    'query_old_tool_repairs', 'query_tool_cost_catalog', 'query_data_catalog',
    'query_opening_records', 'query_tunneling_summary', 'query_tunneling_trend',
    'recommend_tools', 'query_registered_amounts', 'query_stratum_area',
    'compare_manufacturer_service',
}


class AgentViewTests(SimpleTestCase):
    def test_nested_pages_preserve_totals_statistics_and_scalar_lists(self):
        data = {
            'scope': {'record_count': 59, 'ring_range': [1, 59]},
            'summary': {'count': 59, 'rate': 0.37},
            '_analysis_payload': {'summary': {'count': 59}},
            'rows': [{'id': i, 'children': [{'id': j} for j in range(27)]} for i in range(59)],
            'nested': {'items': [{'id': i} for i in range(42)]},
            'numbers': list(range(100)), 'strings': [str(i) for i in range(100)],
        }
        result = json.loads(agent_view(_json(data), page=2, page_size=20))
        for key in ('scope', 'summary', '_analysis_payload', 'numbers', 'strings'):
            self.assertEqual(result[key], data[key])
        self.assertEqual([row['id'] for row in result['rows']], list(range(20, 40)))
        self.assertEqual(result['rows'][0]['children'], [{'id': i} for i in range(20, 27)])
        self.assertEqual(result['_paging']['rows'], {'total': 59, 'page': 2, 'page_size': 20, 'has_more': True})
        self.assertEqual(result['_paging']['rows.0.children'], {'total': 27, 'page': 2, 'page_size': 20, 'has_more': False})
        self.assertEqual(result['_paging']['nested.items']['total'], 42)
        self.assertEqual(result['_paging_note'], '列表只给了第2页（每页20条），各列表总数见 _paging。需要后面的记录时，用相同参数加 page=3 再查。')
        self.assertEqual(AGENT_PAGE_SIZE, 50)

    def test_out_of_range_page_and_short_lists(self):
        result = json.loads(agent_view(_json({'rows': [{'id': i} for i in range(21)], 'short': [{'id': 1}]}), page=50, page_size=20))
        self.assertEqual(result['rows'], [])
        self.assertFalse(result['_paging']['rows']['has_more'])
        self.assertEqual(result['short'], [{'id': 1}])
        self.assertNotIn('_paging', json.loads(agent_view(_json({'rows': [{'id': 1}]}))))

    def test_long_text_deduplicates_only_visible_exact_matches(self):
        long = '口径' * 20
        raw = _json({'note': long, 'summary': {'count_basis': long}, 'other': long + '。', 'short': ['说明'] * 2})
        result = json.loads(agent_view(raw))
        self.assertEqual(result['note'], long)
        self.assertEqual(result['summary']['count_basis'], '（同上）')
        self.assertEqual(result['other'], long + '。')
        self.assertEqual(result['short'], ['说明'] * 2)
        rows = [{'note': long} for _ in range(21)]
        self.assertEqual(json.loads(agent_view(_json({'rows': rows}), page=2, page_size=20))['rows'][0]['note'], long)

    def test_error_result_is_byte_for_byte_unchanged(self):
        for error in ('失败', ''):
            raw = json.dumps({'error': error, 'note': '说明' * 30, 'rows': [{'note': '说明' * 30}] * 30}, indent=2)
            self.assertEqual(agent_view(raw), raw)

    def test_no_pagination_keeps_nested_lists_and_still_deduplicates(self):
        rows = [{'id': i} for i in range(31)]
        long = '统计口径' * 20
        result = json.loads(agent_view(_json({
            'rows': rows, 'nested': {'rows': rows}, 'note': long, 'summary': long,
        }), page_size=None))
        self.assertEqual(result['rows'], rows)
        self.assertEqual(result['nested']['rows'], rows)
        self.assertEqual(result['note'], long)
        self.assertEqual(result['summary'], '（同上）')
        self.assertNotIn('_paging', result)
        self.assertNotIn('_paging_note', result)

    def test_wrappers_page_without_forwarding_pagination_or_changing_trace(self):
        raw = _json({'scope': {'record_count': 31}, 'summary': {'count': 31}, 'facts': ['全部31条'], 'rows': [{'id': i} for i in range(31)]})
        for tool in [*service.TOOLS, service.tool_calculate_tool_performance,
                     service.tool_compare_manufacturer_performance]:
            name = tool.name.removeprefix('tool_')
            self.assertEqual('page' in tool.args_schema.model_fields, name in _PAGED)
            self.assertEqual('page_size' in tool.args_schema.model_fields, name in _PAGED)
            params = {'tool_ids': ['UID']} if name == 'trace_tool_lifecycle' else {}
            if name == 'calculate_tool_performance':
                params = {'tool_numbers': ['UID']}
            if name in _PAGED:
                params.update(page=2, page_size=5)
                properties = tool.args_schema.model_json_schema()['properties']
                for key, default, minimum in (('page', 1, 1), ('page_size', 50, 5)):
                    self.assertEqual({field: properties[key][field] for field in ('type', 'default', 'minimum', 'maximum')},
                                     {'type': 'integer', 'default': default, 'minimum': minimum, 'maximum': 50})
                    self.assertNotIn('description', properties[key])

            def _query(params_str):
                forwarded = json.loads(params_str)
                self.assertNotIn('page', forwarded)
                self.assertNotIn('page_size', forwarded)
                self.assertEqual(forwarded['project_id'], 'CTX')
                return raw

            _query.__name__ = name
            service._trace_start()
            try:
                with self.subTest(tool=name), patch.object(service, name, service._traced_tool(_query)):
                    bound = service._bind_tools_to_project([tool], 'CTX')[0]
                    result = json.loads(bound.invoke(params))
                    self.assertEqual(result['rows'], [{'id': i} for i in (range(5, 10) if name in _PAGED else range(31))])
                    if name in _PAGED:
                        self.assertEqual(result['_paging']['rows'], {'total': 31, 'page': 2, 'page_size': 5, 'has_more': True})
                    else:
                        self.assertNotIn('_paging', result)
                        self.assertNotIn('_paging_note', result)
                    self.assertEqual(result['summary'], {'count': 31})
                    self.assertEqual(service._trace_calls(True)[0]['result'], raw)
            finally:
                service._trace_stop()

    def test_pagination_validation_and_prompt_template(self):
        for name in _PAGED:
            tool = getattr(service, 'tool_' + name)
            for params in ({'page': 0}, {'page': 51}, {'page_size': 4}, {'page_size': 51}):
                with self.subTest(name=name, params=params), patch.object(tool, 'func') as execute:
                    self.assertEqual(json.loads(tool.invoke(params))['code'], 'invalid_tool_arguments')
                    execute.assert_not_called()
        self.assertEqual(ChatPromptTemplate.from_messages([('system', service.SYSTEM_PROMPT)]).input_variables, [])
