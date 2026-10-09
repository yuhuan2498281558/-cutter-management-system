"""Local Windows dev-service watchdog. No installation or auto-start registration."""

import argparse
import ctypes
from ctypes import wintypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import psutil


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".codex-runtime" / "dev-services"


def memory_snapshot():
    physical = psutil.virtual_memory()
    result = {"available_mb": round(physical.available / 1024**2)}
    if os.name == "nt":
        class PerformanceInfo(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
                    "PhysicalAvailable", "SystemCache", "KernelTotal",
                    "KernelPaged", "KernelNonpaged", "PageSize",
                )
            ] + [(name, wintypes.DWORD) for name in (
                "HandleCount", "ProcessCount", "ThreadCount",
            )]

        info = PerformanceInfo()
        info.cb = ctypes.sizeof(info)
        if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            result["commit_percent"] = round(100 * info.CommitTotal / max(info.CommitLimit, 1), 1)
    return result


def memory_critical(memory):
    return memory["available_mb"] < 256 or memory.get("commit_percent", 0) >= 95


def restart_delay(failures):
    return min(300, 5 * 2 ** min(max(failures - 1, 0), 6))


def make_logger(name, folder):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(folder / f"{name}.log", maxBytes=3 * 1024**2,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger


def same_process(process, spec):
    try:
        command = process.cmdline()
        return (
            Path(process.exe()).resolve() == Path(spec["command"][0]).resolve()
            and Path(process.cwd()).resolve() == Path(spec["cwd"]).resolve()
            and command[1:] == spec["command"][1:]
        )
    except (psutil.Error, OSError):
        return False


def port_available(port):
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Service:
    def __init__(self, spec, logger, folder):
        self.spec = spec
        self.logger = logger
        self.folder = folder
        self.process = None
        self.child = None
        self.failures = 0
        self.next_start = 0
        self.started = 0
        self.state = "waiting"
        self.last_exit = None

    def adopt(self):
        matches = [p for p in psutil.process_iter() if same_process(p, self.spec)]
        if len(matches) == 1:
            self.process = matches[0]
            self.started = time.monotonic()
            self.state = "adopted"
            self.logger.info("%s adopted pid=%s; existing output logs unchanged",
                             self.spec["name"], self.process.pid)
            return True
        return bool(matches)  # Multiple matching processes: do not add another.

    def tick(self, now, memory):
        if self.process is not None:
            if self.process.is_running() and (self.child is None or self.child.poll() is None):
                if now - self.started >= 300:
                    self.failures = 0
                return
            self.last_exit = self.child.poll() if self.child else "unknown (adopted)"
            self.failures += 1
            self.next_start = now + restart_delay(self.failures)
            self.logger.warning("%s exited pid=%s code=%s memory=%s retry_in=%ss",
                                self.spec["name"], self.process.pid, self.last_exit,
                                memory, restart_delay(self.failures))
            self.process = self.child = None
            self.state = "backoff"
        if now < self.next_start:
            return
        if self.adopt():
            return
        if memory_critical(memory):
            self.state = "waiting_for_memory"
            return
        if not port_available(self.spec["port"]):
            if self.state != "port_in_use":
                self.logger.warning("%s port %s occupied; leaving its owner alone",
                                    self.spec["name"], self.spec["port"])
            self.state = "port_in_use"
            return
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUNBUFFERED"] = "1"
        try:
            paths = [self.folder / f"{self.spec['name']}.{kind}.log"
                     for kind in ("out", "err")]
            for path in paths:
                # Rotate only between processes; never move an active Windows log handle.
                for index in range(3, 0, -1):
                    source = Path(f"{path}.{index - 1}") if index > 1 else path
                    if source.exists():
                        source.replace(Path(f"{path}.{index}"))
            with paths[0].open("ab") as output, paths[1].open("ab") as error_output:
                self.child = subprocess.Popen(
                    self.spec["command"], cwd=self.spec["cwd"], env=environment,
                    stdin=subprocess.DEVNULL, stdout=output, stderr=error_output,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            self.process = psutil.Process(self.child.pid)
            self.started = now
            self.state = "running"
            self.logger.info("%s started pid=%s", self.spec["name"], self.process.pid)
        except (OSError, psutil.Error) as error:
            self.failures += 1
            self.next_start = now + restart_delay(self.failures)
            self.state = "start_failed"
            self.logger.error("%s start failed: %s", self.spec["name"], error)

    def snapshot(self):
        info = {"name": self.spec["name"], "state": self.state,
                "pid": None, "last_exit": self.last_exit}
        if self.process is not None:
            try:
                memory = self.process.memory_info()
                info.update(pid=self.process.pid,
                            private_mb=round(getattr(memory, "private", memory.rss) / 1024**2))
            except psutil.Error:
                pass
        return info


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def guard_alive(state):
    try:
        process = psutil.Process(state["pid"])
        return (abs(process.create_time() - state["created"]) < 0.01
                and str(Path(__file__).resolve()) in process.cmdline()
                and "run" in process.cmdline())
    except (KeyError, psutil.Error):
        return False


def read_state():
    try:
        return json.loads((RUNTIME / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run_guard(args):
    import msvcrt

    with (RUNTIME / "guard.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return  # Another guard already owns this repository.
        logger = make_logger("guard", RUNTIME)
        specs = [
            {"name": "frontend", "cwd": str(ROOT / "web"), "port": 5173,
             "command": [args.node, "node_modules/vite/bin/vite.js", "--host",
                         "127.0.0.1", "--port", "5173", "--strictPort"]},
            {"name": "backend", "cwd": str(ROOT / "backend"), "port": 8000,
             "command": [args.python, "-m", "daphne", "-b", "127.0.0.1",
                         "-p", "8000", "application.asgi:application"]},
        ]
        services = [Service(spec, logger, RUNTIME) for spec in specs]
        identity = {"pid": os.getpid(), "created": psutil.Process().create_time()}
        heartbeat = 0
        logger.info("guard started pid=%s", os.getpid())
        try:
            while not (RUNTIME / "stop.request").exists():
                now = time.monotonic()
                memory = memory_snapshot()
                for service in services:
                    service.tick(now, memory)
                state = {**identity, "updated": time.time(), "memory": memory,
                         "services": [service.snapshot() for service in services]}
                write_json(RUNTIME / "status.json", state)
                if now >= heartbeat:
                    logger.info("heartbeat %s", json.dumps(state, ensure_ascii=False))
                    heartbeat = now + 60
                time.sleep(5)
        finally:
            logger.info("guard stopped; service processes left running")
            (RUNTIME / "stop.request").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "run", "status", "stop"])
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This launcher requires Windows.")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    state = read_state()
    if args.action == "status":
        print(json.dumps({"guard_running": guard_alive(state), **state}, indent=2))
    elif args.action == "stop":
        if guard_alive(state):
            (RUNTIME / "stop.request").touch()
            for _ in range(50):
                if not guard_alive(state):
                    break
                time.sleep(0.2)
            if guard_alive(state):
                raise RuntimeError("Guard has not stopped yet; inspect guard.log.")
        print("Protection stopped. Frontend and backend left running.")
    elif args.action == "run":
        run_guard(args)
    elif guard_alive(state):
        print(f"Protection already running: PID {state['pid']}")
    else:
        if not args.node or not Path(args.node).is_file() or not Path(args.python).is_file():
            parser.error("Python/Node executable not found. Use --python and --node.")
        (RUNTIME / "stop.request").unlink(missing_ok=True)
        command = [args.python, str(Path(__file__).resolve()), "run",
                   "--node", args.node, "--python", args.python]
        # Keep the guard separate from terminal lifetime/job cleanup where Windows permits.
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        with (RUNTIME / "launcher.log").open("ab") as output:
            try:
                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                 creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            except PermissionError:
                print("Job breakaway unavailable; using a detached console process.")
                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                 creationflags=flags)
        for _ in range(50):
            state = read_state()
            if guard_alive(state):
                print(f"Protection running: PID {state['pid']}; logs: {RUNTIME}")
                return
            time.sleep(0.2)
        raise RuntimeError(f"Guard did not become ready. Inspect {RUNTIME / 'launcher.log'}")


if __name__ == "__main__":
    main()
