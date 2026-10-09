"""A successful call only repairs the failed request it can be linked to."""
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase
from langchain_core.messages import AIMessage

from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot


TOOL_NAME = 'tool_query_tool_change_data'
SUCCESS = {'total_records': 2}


def action(arguments, batch):
    return SimpleNamespace(
        tool=TOOL_NAME, tool_input=arguments,
        message_log=[AIMessage(content='', tool_calls=[
            {'name': TOOL_NAME, 'args': {}, 'id': batch},
        ])] if batch else [],
    )


def error(fields):
    return {'error': 'Invalid arguments', 'code': 'invalid_tool_arguments', 'fields': fields}


class ToolRecoveryTests(SimpleTestCase):
    def test_other_type_or_range_cannot_resolve_same_tool_failure(self):
        assistant = ToolAssistant()
        failed = {'tool_type': 'DISC', 'ring_range': [100, 200], 'last_n_openings': -1}
        for changes in ({'tool_type': 'SCRAPER'}, {'ring_range': [300, 400]}):
            corrected = {**failed, 'last_n_openings': 3, **changes}
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                assistant._validated_agent_answer({
                    'output': 'Partial evidence', 'intermediate_steps': [
                        (action(failed, 'first'), error(['last_n_openings'])),
                        (action(corrected, 'next'), SUCCESS),
                    ],
                })

    def test_only_invalid_nested_element_changes_and_defaults_are_preserved(self):
        assistant = ToolAssistant()
        failed = {'tool_type': ' disc ', 'ring_range': [100, 'invalid']}
        corrected = {'tool_type': 'DISC', 'ring_range': [100, 200], 'last_n_openings': 0}
        result = {'output': 'Complete', 'intermediate_steps': [
            (action(failed, 'first'), error(['ring_range.1'])),
            (action(corrected, 'next'), SUCCESS),
        ]}
        self.assertEqual(assistant._validated_agent_answer(result), 'Complete')
        corrected['ring_range'] = [101, 200]
        with self.assertRaises(RuntimeError):
            assistant._validated_agent_answer(result)

    def test_reversed_interval_repair_preserves_known_endpoints(self):
        assistant = ToolAssistant()
        failed = {'tool_type': 'SCRAPER', 'ring_range': [200, 100]}
        for values in ([300, 400], []):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                assistant._validated_agent_answer({
                    'output': 'Wrong scope', 'intermediate_steps': [
                        (action(failed, 'first'), error(['ring_range'])),
                        (action({**failed, 'ring_range': values}, 'next'), SUCCESS),
                    ],
                })

    def test_same_batch_missing_input_and_root_errors_remain_unresolved(self):
        assistant = ToolAssistant()
        invalid = action({'ring_range': [200, 100]}, 'batch')
        for corrected, fields in (
            (action({'ring_range': [100, 200]}, 'batch'), ['ring_range']),
            (SimpleNamespace(tool=TOOL_NAME), ['ring_range']),
            (action({'ring_range': [100, 200]}, 'next'), ['']),
            (action({'ring_range': [100, 200]}, 'next'), None),
        ):
            with self.subTest(corrected=corrected, fields=fields), self.assertRaises(RuntimeError):
                assistant._validated_agent_answer({
                    'output': 'Unresolved', 'intermediate_steps': [
                        (invalid, error(fields)), (corrected, SUCCESS),
                    ],
                })

    def test_one_success_does_not_clear_two_failed_requests(self):
        assistant = ToolAssistant()
        with self.assertRaises(RuntimeError):
            assistant._validated_agent_answer({
                'output': 'Incomplete comparison', 'intermediate_steps': [
                    (action({'tool_type': 'DISC', 'ring_range': [200, 100]}, 'first'), error(['ring_range'])),
                    (action({'tool_type': 'SCRAPER', 'ring_range': [200, 100]}, 'first'), error(['ring_range'])),
                    (action({'tool_type': 'DISC', 'ring_range': [100, 200]}, 'next'), SUCCESS),
                ],
            })

    async def test_stream_requires_matching_start_input_run_and_later_model_round(self):
        invalid = {'tool_type': 'SCRAPER', 'ring_range': [200, 100]}
        valid = {'tool_type': 'SCRAPER', 'ring_range': [100, 200]}
        for variant in ('different_type', 'missing_start', 'wrong_run', 'same_round'):
            with self.subTest(variant=variant):
                assistant = ToolAssistant()
                snapshot = MemorySnapshot(scope_key='user:1', backend='legacy')
                assistant._load_memory = Mock(return_value=snapshot)
                assistant._prepare_query_context = Mock(return_value={
                    'user_id': '1', 'project_id': 'P', 'route_mode': 'agent',
                    'effective_query': '统计换刀', 'memory_slots': {}, 'query_spec': {},
                })
                assistant._store_turn_and_summarize = Mock(return_value=snapshot)
                candidate = {**valid, 'tool_type': 'DISC'} if variant == 'different_type' else valid

                async def events(*args, **kwargs):
                    yield {'event': 'on_chain_start', 'run_id': 'root', 'parent_ids': []}
                    yield {'event': 'on_chat_model_start', 'run_id': 'model1'}
                    if variant != 'missing_start':
                        yield {'event': 'on_tool_start', 'run_id': 'failed', 'name': TOOL_NAME, 'data': {'input': invalid}}
                    yield {'event': 'on_tool_end', 'run_id': 'failed', 'name': TOOL_NAME, 'data': {'output': error(['ring_range'])}}
                    if variant != 'same_round':
                        yield {'event': 'on_chat_model_start', 'run_id': 'model2'}
                    yield {'event': 'on_tool_start', 'run_id': 'fixed', 'name': TOOL_NAME, 'data': {'input': candidate}}
                    yield {'event': 'on_tool_end', 'run_id': 'wrong' if variant == 'wrong_run' else 'fixed',
                           'name': TOOL_NAME, 'data': {'output': SUCCESS}}
                    yield {'event': 'on_chain_end', 'run_id': 'root', 'data': {'output': {
                        'output': 'Do not save', 'intermediate_steps': [
                            (action(invalid, 'first'), error(['ring_range'])),
                            (action(candidate, 'next'), SUCCESS),
                        ],
                    }}}

                assistant._get_executor_for_query = Mock(return_value=SimpleNamespace(astream_events=events))
                messages = [item async for item in assistant.chat_stream('统计换刀', {'user_id': 1})]
                self.assertEqual(messages[-1]['type'], 'error')
                assistant._store_turn_and_summarize.assert_not_called()
