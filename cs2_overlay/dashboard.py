"""Local web dashboard for supervising CS2 Toolkit."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from .core import BASE, is_admin, list_cs2_windows

OVERLAY_SCRIPT = Path(BASE) / "overlay.py"
CONFIG_JSON = Path(BASE) / "config.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOG_LIMIT = 300

MODES = {
    "auto_derank": {
        "label": "Auto Derank",
        "env": {
            "CS2_TOOLKIT_DERANK_AFK": "0",
            "CS2_TOOLKIT_AUTO_RECONNECT": "0",
        },
    },
    "derank_afk": {
        "label": "Derank AFK",
        "env": {
            "CS2_TOOLKIT_DERANK_AFK": "1",
            "CS2_TOOLKIT_AUTO_RECONNECT": "0",
        },
    },
    "afk_reconnect": {
        "label": "AFK Reconnect",
        "env": {
            "CS2_TOOLKIT_DERANK_AFK": "1",
            "CS2_TOOLKIT_AUTO_RECONNECT": "1",
        },
    },
}


def mode_env(mode):
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    return dict(MODES[mode]["env"])


class LogBuffer:
    def __init__(self, limit=LOG_LIMIT):
        self._lines = deque(maxlen=limit)
        self._lock = threading.Lock()

    def add(self, line):
        text = str(line).rstrip("\r\n")
        with self._lock:
            self._lines.append(text)

    def lines(self):
        with self._lock:
            return list(self._lines)


class DashboardSupervisor:
    def __init__(self, popen=subprocess.Popen, reader_thread=None, log_buffer=None):
        self._popen = popen
        self._reader_thread = reader_thread or self._start_reader_thread
        self.logs = log_buffer or LogBuffer()
        self.process = None
        self.mode = "auto_derank"
        self.returncode = None

    def _is_running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, mode="auto_derank"):
        if self._is_running():
            return {"ok": False, "error": "automation already running"}
        env = os.environ.copy()
        env.update(mode_env(mode))
        cmd = [sys.executable, str(OVERLAY_SCRIPT)]
        self.mode = mode
        self.returncode = None
        self.process = self._popen(
            cmd,
            cwd=BASE,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader_thread(target=self._read_output, args=(self.process,))
        return {"ok": True, "pid": self.process.pid}

    def stop(self):
        proc = self.process
        if proc is None or proc.poll() is not None:
            return {"ok": False, "error": "automation is not running"}
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.returncode = proc.poll()
        return {"ok": True}

    def restart(self, mode=None):
        if self._is_running():
            self.stop()
        return self.start(mode or self.mode)

    def state(self):
        running = self._is_running()
        pid = self.process.pid if running and self.process is not None else None
        if self.process is not None and not running:
            self.returncode = self.process.poll()
        try:
            cs2_count = len(list_cs2_windows())
        except Exception:
            cs2_count = None
        warnings = []
        admin = is_admin()
        if not admin:
            warnings.append("Dashboard is not running as Administrator")
        if not OVERLAY_SCRIPT.is_file():
            warnings.append("overlay.py was not found")
        return {
            "admin": admin,
            "running": running,
            "pid": pid,
            "mode": self.mode,
            "returncode": self.returncode,
            "warnings": warnings,
            "cs2WindowCount": cs2_count,
        }

    def _read_output(self, proc):
        if proc.stdout is None:
            return
        for line in proc.stdout:
            self.logs.add(line)

    def _start_reader_thread(self, target, args=()):
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        return thread
