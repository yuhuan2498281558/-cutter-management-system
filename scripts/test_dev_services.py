"""Exercise restart protection with disposable processes, never the project servers."""

import logging
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import psutil

from dev_services import Service


class ServiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.close()
        self.fixture = self.folder / "fixture.py"
        self.fixture.write_text(
            "import time\nprint('ready', flush=True)\ntime.sleep(120)\n", encoding="utf-8")
        self.spec = {"name": "fixture", "cwd": str(self.folder), "port": self.port,
                     "command": [sys.executable, str(self.fixture)]}
        self.service = Service(self.spec, logging.getLogger("test"), self.folder)
        self.external = None
        self.normal = {"available_mb": 2048, "commit_percent": 70}

    def tearDown(self):
        for child in (self.service.child, self.external):
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
        self.temp.cleanup()

    def test_exit_recovery_backoff_and_critical_memory(self):
        self.service.tick(0, self.normal)
        first = self.service.child
        first.terminate()
        first.wait(timeout=5)
        self.service.tick(1, self.normal)
        self.assertIsNone(self.service.child)
        self.assertIsNotNone(self.service.last_exit)
        self.service.tick(5, self.normal)
        self.assertIsNone(self.service.child)
        self.service.tick(6, {"available_mb": 100, "commit_percent": 98})
        self.assertEqual(self.service.state, "waiting_for_memory")
        self.service.tick(7, self.normal)
        self.assertIsNotNone(self.service.child)
        self.assertNotEqual(first.pid, self.service.child.pid)
        self.assertTrue((self.folder / "fixture.out.log.1").exists())
        self.service.child.terminate()
        self.service.child.wait(timeout=5)
        self.service.tick(8, self.normal)
        self.assertEqual(self.service.next_start, 18)

    def test_adopt_existing_process_and_recover_after_exit(self):
        self.external = subprocess.Popen(self.spec["command"], cwd=self.folder,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.service.tick(time.monotonic(), self.normal)
        self.assertEqual(self.service.process.pid, self.external.pid)
        self.assertIsNone(self.service.child)
        self.external.terminate()
        self.external.wait(timeout=5)
        now = time.monotonic()
        self.service.tick(now, self.normal)
        self.service.tick(now + 6, self.normal)
        self.assertIsNotNone(self.service.child)
        self.assertEqual(self.service.last_exit, "unknown (adopted)")

    def test_foreign_port_owner_is_untouched(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.port))
            listener.listen()
            self.service.tick(0, self.normal)
            self.assertEqual(self.service.state, "port_in_use")
            self.assertIsNone(self.service.child)
            self.assertIsNotNone(listener.getsockname())

    def test_running_service_not_killed_under_memory_pressure(self):
        self.service.tick(0, self.normal)
        before = self.service.child.pid
        self.service.tick(1, {"available_mb": 100, "commit_percent": 99})
        self.assertEqual(self.service.child.pid, before)
        self.assertTrue(psutil.pid_exists(before))


if __name__ == "__main__":
    unittest.main()
