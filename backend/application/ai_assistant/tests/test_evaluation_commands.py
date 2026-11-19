import io
import json
import os
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class EvaluationCommandTests(SimpleTestCase):
    def test_experiment_focus_sources_and_rubric_numeric_scoring(self):
        from application.ai_assistant.management.commands.run_experiment import Command, resolve_refs

        cases = [
            {'id': 'analysis', 'question': '登记金额多少', 'task_type': 'rubric',
             'focus_sources': ['cost', 'repair'], 'gt_sql': 'SELECT 12 AS amount',
             'answer_extract': {'amount': r'登记金额(\d+)'}, 'rubric': '0=错误；1=遗漏；2=完整'},
            {'id': 'free', 'question': '解释覆盖范围', 'task_type': 'rubric',
             'focus_sources': [], 'rubric': '0=错误；1=遗漏；2=完整'},
            {'id': 'plain', 'question': '解释覆盖范围', 'task_type': 'rubric'},
        ]
        with tempfile.TemporaryDirectory(prefix='ai-v4-test-') as directory:
            bank = os.path.join(directory, 'bank.json')
            with open(bank, 'w', encoding='utf-8') as target:
                json.dump(cases, target)
            with open(bank, encoding='utf-8') as source:
                loaded = resolve_refs(json.load(source))
        command = Command()
        runner = Mock()
        runner.chat.return_value = {'success': True, 'answer': '登记金额12'}
        for arm in Command.ARMS:
            for case in loaded:
                with self.subTest(arm=arm, case=case['id']):
                    self.assertFalse(command._is_todo(case))
                    truth = [{'amount': 12}] if case.get('gt_sql') else None
                    with patch.object(command, '_ground_truth', return_value=(truth, '')):
                        record = command._run_case(runner, arm, case, 0, 'isolated', {'project': 'fixture'})[0]
                    context = runner.chat.call_args.args[1]
                    if arm in ('agent', 'hybrid') and 'focus_sources' in case:
                        self.assertEqual(context['focus_sources'], case['focus_sources'])
                    else:
                        self.assertNotIn('focus_sources', context)
                    self.assertEqual(record.get('rubric'), case.get('rubric'))
                    self.assertEqual(record['task_type'], 'rubric')
                    if truth:
                        self.assertTrue(record['exact_match'])
                        self.assertEqual(record['extracted'], {'amount': 12})
                    else:
                        self.assertNotIn('exact_match', record)

    def test_sql_guard_checks_join_comma_and_nested_tables_without_model(self):
        from application.ai_assistant.baselines import TextToSQLBaseline
        baseline = object.__new__(TextToSQLBaseline)
        allowed = 'shield_project_info'
        # 护栏不再改写 SQL 追加 LIMIT（旧做法会在已有 LIMIT 的语句后再拼一次），行数在执行时截取
        self.assertEqual(baseline._guard(f'SELECT * FROM {allowed} LIMIT 5'), f'SELECT * FROM {allowed} LIMIT 5')
        self.assertEqual(baseline._guard(f'SELECT * FROM (SELECT * FROM public."{allowed}") p'),
                         f'SELECT * FROM (SELECT * FROM public."{allowed}") p')
        for sql in ('SELECT * FROM auth_user',
                    f'SELECT * FROM {allowed} p JOIN auth_user u ON p.id=u.id',
                    f'SELECT * FROM {allowed} p, auth_user u',
                    'SELECT * FROM (SELECT * FROM auth_user) hidden',
                    f'SELECT * FROM {allowed} WHERE EXISTS (SELECT 1 FROM auth_user)',
                    f'SELECT * FROM private.{allowed}',
                    'SELECT * FROM query_to_xml(\'SELECT * FROM auth_user\', true, false, \'\')'):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                baseline._guard(sql)

    def test_ground_truth_and_baseline_execute_inside_readonly_guard(self):
        from application.ai_assistant.baselines import TextToSQLBaseline
        from application.ai_assistant.management.commands.run_experiment import Command
        active = []
        @contextmanager
        def readonly():
            active.append(True)
            try:
                yield
            finally:
                active.pop()
        cursor = MagicMock()
        cursor.description = [('value',)]
        cursor.fetchall.return_value = [(2,)]
        cursor.fetchmany.return_value = [(2,)]
        cursor.execute.side_effect = lambda *_: self.assertTrue(active)
        for module, run in (
            ('application.ai_assistant.baselines', lambda: TextToSQLBaseline._execute('SELECT 2')),
            ('application.ai_assistant.management.commands.run_experiment', lambda: Command()._ground_truth({'gt_sql': 'SELECT 2'})),
        ):
            target = (module + '.readonly_database' if module.endswith('baselines') else
                      'application.ai_assistant.evaluation.current_data_suite.readonly_database')
            with patch(target, readonly), patch(module + '.connection') as connection:
                connection.cursor.return_value.__enter__.return_value = cursor
                self.assertTrue(run())
        self.assertFalse(active)

    def test_verify_requires_explicit_snapshot_path(self):
        with self.assertRaisesMessage(CommandError, '--output'):
            call_command('verify_ground_truth', stdout=io.StringIO())

    def test_verify_executes_bank_sql_inside_readonly_transaction(self):
        module = 'application.ai_assistant.management.commands.verify_ground_truth'
        active = []
        @contextmanager
        def readonly():
            active.append(True)
            try:
                yield
            finally:
                active.pop()
        cursor = MagicMock(description=[('count',)])
        cursor.fetchall.return_value = [(2,)]
        cursor.fetchmany.return_value = [(2,)]
        cursor.execute.side_effect = lambda *_: self.assertTrue(active)
        with tempfile.TemporaryDirectory(prefix='ai-gt-test-') as directory:
            bank, output = os.path.join(directory, 'bank.json'), os.path.join(directory, 'snapshot.json')
            with open(bank, 'w', encoding='utf-8') as target:
                json.dump([{'id': 'read_only', 'gt_sql': 'SELECT 2 AS count'}], target)
            with patch(module + '.readonly_database', readonly), patch(module + '.connection') as connection, patch(
                module + '.Command._fingerprint', return_value=('fixture', {})
            ):
                connection.cursor.return_value.__enter__.return_value = cursor
                call_command('verify_ground_truth', bank=bank, output=output, stdout=io.StringIO())
            with open(output, encoding='utf-8') as source:
                self.assertEqual(json.load(source)['ground_truth']['read_only'], [{'count': 2}])
        self.assertFalse(active)

    def test_commands_require_project_before_any_assistant_call(self):
        for command in ("benchmark_ai_assistant", "regression_ai_assistant"):
            with self.subTest(command=command), patch(
                f"application.ai_assistant.management.commands.{command}.get_assistant"
            ) as assistant:
                with self.assertRaisesMessage(CommandError, "--project-id is required"):
                    call_command(command, stdout=io.StringIO())
                assistant.assert_not_called()

    def test_benchmark_isolates_each_case_and_run_and_passes_project(self):
        module = "application.ai_assistant.management.commands.benchmark_ai_assistant"
        assistant = Mock()
        assistant.chat.return_value = {"success": True, "type": "analysis", "answer": "answer"}
        with tempfile.TemporaryDirectory(prefix="ai-eval-test-") as directory:
            output = os.path.join(directory, "result.json")
            with patch(f"{module}.get_assistant", return_value=assistant), patch(
                f"{module}.get_llm_config", return_value=SimpleNamespace(provider="test", model="test", base_url="")
            ), patch(f"{module}._build_project_snapshot", return_value={"latest_ring_no": 487}):
                for _ in range(2):
                    call_command("benchmark_ai_assistant", project_id="PROJECT-A", route_mode="rule",
                                 questions=["q1", "q2"], user_id="123", output=output, stdout=io.StringIO())
            with open(output, encoding="utf-8") as source:
                result = json.load(source)
        contexts = [call.args[1] for call in assistant.chat.call_args_list]
        self.assertEqual(len({context["user_id"] for context in contexts}), 4)
        self.assertTrue(all(context["project_id"] == "PROJECT-A" for context in contexts))
        self.assertTrue(all(context["route_mode"] == "rule" for context in contexts))
        self.assertTrue(all(context["latest_ring_no"] == 487 for context in contexts))
        self.assertTrue(all(not context["user_id"].isdigit() for context in contexts))
        self.assertEqual(result["summary"]["scope_policy"], "isolated_per_case")

    def test_regression_uses_bound_project_and_separate_case_scopes(self):
        module = "application.ai_assistant.management.commands.regression_ai_assistant"
        assistant = Mock()
        assistant.chat.return_value = {"success": True, "type": "analysis", "answer": "expected"}
        cases = [{"id": str(i), "question": "question", "must_contain": ["expected"]} for i in range(2)]
        with patch(f"{module}.get_assistant", return_value=assistant), patch(
            f"{module}._build_project_snapshot", return_value={}
        ), patch(f"{module}.Command._load_cases", return_value=cases):
            call_command("regression_ai_assistant", project_id="PROJECT-B", stdout=io.StringIO())
        first, second = [call.args[1] for call in assistant.chat.call_args_list]
        self.assertNotEqual(first["user_id"], second["user_id"])
        self.assertEqual(first["project_id"], "PROJECT-B")
        self.assertEqual(second["project_id"], "PROJECT-B")
