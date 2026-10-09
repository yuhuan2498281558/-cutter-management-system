from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from application.ai_assistant import summary_worker


class SummaryWorkerTests(SimpleTestCase):
    def setUp(self):
        # Exercise the real scheduler and queued closure without starting a
        # background thread or leaving process-global pending jobs behind.
        self.executor = Mock()
        self.pending = set()
        for patcher in (
            patch.object(summary_worker, "_executor", self.executor),
            patch.object(summary_worker, "_pending", self.pending),
            patch.object(summary_worker, "close_old_connections"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_job(self, index=0):
        return self.executor.submit.call_args_list[index].args[0]()

    def test_deduplicates_scope_and_releases_it_on_completion(self):
        callback = Mock()
        self.assertTrue(summary_worker.schedule_summary("same", callback))
        self.assertFalse(summary_worker.schedule_summary("same", callback))
        self.assertEqual(self.executor.submit.call_count, 1)
        self.run_job()
        callback.assert_called_once_with()
        self.assertEqual(self.pending, set())
        self.assertTrue(summary_worker.schedule_summary("same", callback))

    def test_capacity_includes_queued_jobs_and_recovers_after_completion(self):
        for index in range(8):
            self.assertTrue(summary_worker.schedule_summary(str(index), Mock()))
        self.assertFalse(summary_worker.schedule_summary("overflow", Mock()))
        self.assertEqual(self.executor.submit.call_count, 8)
        self.run_job()
        self.assertTrue(summary_worker.schedule_summary("overflow", Mock()))
        self.assertEqual(len(self.pending), 8)

    def test_callback_failure_releases_key_and_closes_connections(self):
        callback = Mock(side_effect=RuntimeError("callback failed"))
        summary_worker.schedule_summary("failed", callback)
        with self.assertLogs(summary_worker.logger, level="ERROR"):
            self.run_job()
        self.assertEqual(self.pending, set())
        self.assertEqual(summary_worker.close_old_connections.call_count, 2)

    def test_submit_failure_releases_key_and_allows_retry(self):
        self.executor.submit.side_effect = RuntimeError("executor unavailable")
        with self.assertLogs(summary_worker.logger, level="ERROR"):
            self.assertFalse(summary_worker.schedule_summary("failed", Mock()))
        self.assertEqual(self.pending, set())
        self.executor.submit.side_effect = None
        self.assertTrue(summary_worker.schedule_summary("failed", Mock()))

    def test_connection_cleanup_failure_does_not_leak_pending_capacity(self):
        summary_worker.close_old_connections.side_effect = [None, RuntimeError("cleanup failed")]
        summary_worker.schedule_summary("cleanup", Mock())
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self.run_job()
        self.assertEqual(self.pending, set())

    def test_connection_setup_failure_skips_callback_and_releases_key(self):
        callback = Mock()
        summary_worker.close_old_connections.side_effect = [RuntimeError("setup failed"), None]
        summary_worker.schedule_summary("setup", callback)
        with self.assertLogs(summary_worker.logger, level="ERROR"):
            self.run_job()
        callback.assert_not_called()
        self.assertEqual(self.pending, set())
