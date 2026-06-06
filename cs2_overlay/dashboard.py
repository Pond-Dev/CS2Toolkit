"""Local web dashboard for supervising CS2 Toolkit."""
from __future__ import annotations

import os
import json
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from . import config as default_config
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


EDITABLE_CONFIG_KEYS = {
    "AUTO_INVITE",
    "HOST_MONITOR_INDEX",
    "GAME_MODE",
    "ALT_FRIEND_CODES",
    "MATCH_THRESHOLD",
    "MATCH_SCALES",
    "STARTUP_DELAY_SECS",
    "DEBUG",
}


def _require_bool(key, value):
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _require_non_negative_number(key, value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative number")
    return value


def validate_config_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("config payload must be an object")
    validated = {}
    for key, value in payload.items():
        if key not in EDITABLE_CONFIG_KEYS:
            raise ValueError(f"unknown config key: {key}")
        if key in {"AUTO_INVITE", "DEBUG"}:
            validated[key] = _require_bool(key, value)
        elif key == "HOST_MONITOR_INDEX":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("HOST_MONITOR_INDEX must be an integer >= 0")
            validated[key] = value
        elif key == "GAME_MODE":
            if value not in {"competitive", "premier"}:
                raise ValueError("GAME_MODE must be competitive or premier")
            validated[key] = value
        elif key == "ALT_FRIEND_CODES":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError("ALT_FRIEND_CODES must be an array of strings")
            validated[key] = value
        elif key == "MATCH_THRESHOLD":
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
            ):
                raise ValueError("MATCH_THRESHOLD must be a number between 0 and 1")
            validated[key] = value
        elif key == "MATCH_SCALES":
            if (
                not isinstance(value, list)
                or not value
                or not all(
                    isinstance(item, (int, float)) and not isinstance(item, bool) and item > 0
                    for item in value
                )
            ):
                raise ValueError("MATCH_SCALES must be a non-empty array of positive numbers")
            validated[key] = value
        elif key == "STARTUP_DELAY_SECS":
            validated[key] = _require_non_negative_number(key, value)
    return validated


def read_dashboard_config(path=CONFIG_JSON):
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object")
    return data


def editable_dashboard_config(path=CONFIG_JSON):
    values = {key: getattr(default_config, key) for key in EDITABLE_CONFIG_KEYS}
    path = Path(path)
    if path.is_file():
        values.update(
            {key: value for key, value in read_dashboard_config(path).items() if key in EDITABLE_CONFIG_KEYS}
        )
    for key, value in list(values.items()):
        if isinstance(value, tuple):
            values[key] = list(value)
    return values


def write_dashboard_config(payload, path=CONFIG_JSON):
    path = Path(path)
    existing = read_dashboard_config(path) if path.is_file() else {}
    validated = validate_config_payload(payload)
    existing.update(validated)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "config": existing}
