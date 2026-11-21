from unittest.mock import patch

from django.test import TestCase

from application.ai_assistant.views import _context_for_user, _validate_body
from application.shield.models import ProjectInfo
from dvadmin.system.models import Users


class QueryContextControlsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = Users.objects.create(id=7, username='tester', is_superuser=True)
        ProjectInfo.objects.create(project_id='P1', project_name='上下文测试')

    def test_modes_and_individual_clears_are_validated(self):
        for mode in ('auto', 'new', 'continue'):
            self.assertIsNone(_validate_body({
                'query': '换刀统计', 'context_mode': mode,
                'clear_slots': ['ring_range', 'tool_type', 'cutter_position_no'],
            }))
        for body in (
            {'context_mode': None}, {'context_mode': {}}, {'context_mode': 'reuse'},
            {'clear_slots': None}, {'clear_slots': 'tool_type'},
            {'clear_slots': [{}]}, {'clear_slots': ['project_id']},
            {'clear_slots': ['tool_type'] * 4},
        ):
            with self.subTest(body=body):
                self.assertIsNotNone(_validate_body({'query': '换刀统计', **body}))

    @patch('application.ai_assistant.views._build_project_snapshot', return_value={})
    def test_controls_do_not_override_authenticated_identity(self, snapshot):
        body = {'project_id': 'P1', 'user_id': 999, 'context_mode': 'continue',
                'clear_slots': ['tool_type']}
        context = _context_for_user(self.user, body)
        self.assertEqual(context['user_id'], 7)
        self.assertEqual(context['context_mode'], 'continue')
        self.assertEqual(context['clear_slots'], ['tool_type'])
        body['clear_slots'].clear()
        self.assertEqual(context['clear_slots'], ['tool_type'])

    @patch('application.ai_assistant.views._build_project_snapshot', return_value={})
    def test_old_clients_default_to_auto_without_clear(self, snapshot):
        context = _context_for_user(self.user, {'project_id': 'P1'})
        self.assertEqual(context['context_mode'], 'auto')
        self.assertEqual(context['clear_slots'], [])
