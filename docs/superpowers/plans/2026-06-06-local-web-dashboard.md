# Local Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local browser dashboard that starts/stops CS2 Toolkit, edits allowlisted config settings, and streams recent automation logs.

**Architecture:** Add a standard-library HTTP server that owns exactly one `overlay.py` subprocess and serves a static dashboard UI. Keep the existing automation loops in `overlay.py`/`cs2_overlay.flows`; the dashboard only supervises them and writes `config.json` for the next run.

**Tech Stack:** Python stdlib (`http.server`, `json`, `subprocess`, `threading`, `webbrowser`, `unittest`) plus existing project modules.

---

## File Structure

- Create `cs2_overlay/dashboard.py`: dashboard domain logic, config validation, subprocess supervisor, HTTP handler, static HTML/CSS/JS strings, and `run_dashboard`.
- Create `dashboard.py`: thin entry point that calls `cs2_overlay.dashboard.main`.
- Create `tests/test_dashboard_supervisor.py`: process lifecycle and log-buffer tests with fake process factories.
- Create `tests/test_dashboard_config.py`: allowlisted config validation/read/write tests.
- Create `tests/test_dashboard_http.py`: HTTP API and static asset tests against the handler in memory.
- Modify `README.md`: add dashboard run instructions.
- Modify `.gitignore`: ignore `.superpowers/` visual-brainstorming artifacts.

## Task 1: Dashboard Supervisor

**Files:**
- Create: `cs2_overlay/dashboard.py`
- Test: `tests/test_dashboard_supervisor.py`

- [ ] **Step 1: Write failing supervisor tests**

```python
import unittest

from cs2_overlay import dashboard


class FakeProcess:
    def __init__(self, pid=1234, returncode=None, stdout=None):
        self.pid = pid
        self.returncode = returncode
        self.stdout = stdout or []
        self.terminated = False
        self.killed = False
        self.waits = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.returncode


class DashboardSupervisorTests(unittest.TestCase):
    def test_mode_env_maps_existing_launcher_modes(self):
        self.assertEqual(
            dashboard.mode_env("auto_derank"),
            {
                "CS2_TOOLKIT_DERANK_AFK": "0",
                "CS2_TOOLKIT_AUTO_RECONNECT": "0",
            },
        )
        self.assertEqual(
            dashboard.mode_env("derank_afk")["CS2_TOOLKIT_DERANK_AFK"],
            "1",
        )
        self.assertEqual(
            dashboard.mode_env("afk_reconnect")["CS2_TOOLKIT_AUTO_RECONNECT"],
            "1",
        )

    def test_start_refuses_when_process_is_running(self):
        created = []
        supervisor = dashboard.DashboardSupervisor(
            popen=lambda *args, **kwargs: created.append((args, kwargs)) or FakeProcess(),
            reader_thread=lambda target, args=(): None,
        )

        self.assertEqual(supervisor.start("auto_derank")["ok"], True)
        second = supervisor.start("derank_afk")

        self.assertEqual(second["ok"], False)
        self.assertEqual(second["error"], "automation already running")
        self.assertEqual(len(created), 1)

    def test_stop_terminates_only_managed_process(self):
        proc = FakeProcess()
        supervisor = dashboard.DashboardSupervisor(
            popen=lambda *args, **kwargs: proc,
            reader_thread=lambda target, args=(): None,
        )
        supervisor.start("auto_derank")

        result = supervisor.stop()

        self.assertEqual(result["ok"], True)
        self.assertEqual(proc.terminated, True)
        self.assertEqual(proc.killed, False)

    def test_log_buffer_keeps_recent_lines(self):
        buf = dashboard.LogBuffer(limit=3)

        for line in ["one\n", "two\n", "three\n", "four\n"]:
            buf.add(line)

        self.assertEqual(buf.lines(), ["two", "three", "four"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_dashboard_supervisor
```

Expected: fail because `cs2_overlay.dashboard` does not exist.

- [ ] **Step 3: Implement supervisor primitives**

Add to `cs2_overlay/dashboard.py`:

```python
"""Local web dashboard for supervising CS2 Toolkit."""
from __future__ import annotations

import os
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
        if not is_admin():
            warnings.append("Dashboard is not running as Administrator")
        if not OVERLAY_SCRIPT.is_file():
            warnings.append("overlay.py was not found")
        return {
            "admin": is_admin(),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_dashboard_supervisor
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add cs2_overlay/dashboard.py tests/test_dashboard_supervisor.py
git commit -m "Add dashboard process supervisor"
```

## Task 2: Config Validation And Persistence

**Files:**
- Modify: `cs2_overlay/dashboard.py`
- Test: `tests/test_dashboard_config.py`

- [ ] **Step 1: Write failing config tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from cs2_overlay import dashboard


class DashboardConfigTests(unittest.TestCase):
    def test_validate_config_accepts_allowlisted_values(self):
        payload = {
            "AUTO_INVITE": False,
            "HOST_MONITOR_INDEX": 1,
            "GAME_MODE": "premier",
            "ALT_FRIEND_CODES": ["AAAAA-1111"],
            "MATCH_THRESHOLD": 0.75,
            "MATCH_SCALES": [1.0, 0.85],
            "STARTUP_DELAY_SECS": 0,
            "DEBUG": True,
        }

        validated = dashboard.validate_config_payload(payload)

        self.assertEqual(validated["GAME_MODE"], "premier")
        self.assertEqual(validated["MATCH_SCALES"], [1.0, 0.85])

    def test_validate_config_rejects_unknown_key(self):
        with self.assertRaises(ValueError) as ctx:
            dashboard.validate_config_payload({"UNKNOWN": True})

        self.assertIn("UNKNOWN", str(ctx.exception))

    def test_validate_config_rejects_bad_game_mode(self):
        with self.assertRaises(ValueError):
            dashboard.validate_config_payload({"GAME_MODE": "wingman"})

    def test_write_config_preserves_existing_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"CUSTOM_KEEP": 123, "GAME_MODE": "competitive"}), encoding="utf-8")

            result = dashboard.write_dashboard_config(
                {"GAME_MODE": "premier"},
                path=path,
            )

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["CUSTOM_KEEP"], 123)
            self.assertEqual(saved["GAME_MODE"], "premier")
            self.assertEqual(result["ok"], True)

    def test_editable_config_uses_defaults_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"

            config = dashboard.editable_dashboard_config(path=path)

            self.assertIn("AUTO_INVITE", config)
            self.assertIn("HOST_MONITOR_INDEX", config)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_dashboard_config
```

Expected: fail because config helpers are not implemented.

- [ ] **Step 3: Implement allowlisted config helpers**

Append to `cs2_overlay/dashboard.py`:

```python
import json

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
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError("MATCH_THRESHOLD must be a number between 0 and 1")
            validated[key] = value
        elif key == "MATCH_SCALES":
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, (int, float)) and not isinstance(item, bool) and item > 0 for item in value)
            ):
                raise ValueError("MATCH_SCALES must be a non-empty array of positive numbers")
            validated[key] = value
        elif key == "STARTUP_DELAY_SECS":
            validated[key] = _require_non_negative_number(key, value)
    return validated


def read_dashboard_config(path=CONFIG_JSON):
    if not Path(path).is_file():
        return {}
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config.json must contain an object")
    return data


def editable_dashboard_config(path=CONFIG_JSON):
    values = {key: getattr(default_config, key) for key in EDITABLE_CONFIG_KEYS}
    if Path(path).is_file():
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_dashboard_config
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add cs2_overlay/dashboard.py tests/test_dashboard_config.py
git commit -m "Add dashboard config validation"
```

## Task 3: HTTP API

**Files:**
- Modify: `cs2_overlay/dashboard.py`
- Test: `tests/test_dashboard_http.py`

- [ ] **Step 1: Write failing HTTP tests**

```python
import json
import unittest

from cs2_overlay import dashboard


class FakeSupervisor:
    def __init__(self):
        self.started = []
        self.stopped = 0
        self.restarted = []
        self.logs = dashboard.LogBuffer()

    def state(self):
        return {
            "admin": True,
            "running": False,
            "pid": None,
            "mode": "auto_derank",
            "returncode": None,
            "warnings": [],
            "cs2WindowCount": 0,
        }

    def start(self, mode):
        self.started.append(mode)
        return {"ok": True, "pid": 99}

    def stop(self):
        self.stopped += 1
        return {"ok": True}

    def restart(self, mode=None):
        self.restarted.append(mode)
        return {"ok": True, "pid": 100}


class DashboardHttpTests(unittest.TestCase):
    def test_api_state_returns_json(self):
        app = dashboard.DashboardApp(supervisor=FakeSupervisor())

        status, headers, body = app.dispatch("GET", "/api/state", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body)["mode"], "auto_derank")

    def test_api_start_uses_requested_mode(self):
        supervisor = FakeSupervisor()
        app = dashboard.DashboardApp(supervisor=supervisor)

        status, _headers, body = app.dispatch(
            "POST",
            "/api/start",
            json.dumps({"mode": "derank_afk"}).encode("utf-8"),
        )

        self.assertEqual(status, 200)
        self.assertEqual(supervisor.started, ["derank_afk"])
        self.assertEqual(json.loads(body)["ok"], True)

    def test_static_index_is_served(self):
        app = dashboard.DashboardApp(supervisor=FakeSupervisor())

        status, headers, body = app.dispatch("GET", "/", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("CS2 Toolkit Dashboard", body)

    def test_start_conflict_returns_409(self):
        class ConflictSupervisor(FakeSupervisor):
            def start(self, mode):
                return {"ok": False, "error": "automation already running"}

        app = dashboard.DashboardApp(supervisor=ConflictSupervisor())

        status, _headers, body = app.dispatch("POST", "/api/start", b"{}")

        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "automation already running")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_dashboard_http
```

Expected: fail because `DashboardApp` is not implemented.

- [ ] **Step 3: Implement dispatchable dashboard app**

Append to `cs2_overlay/dashboard.py`:

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CS2 Toolkit Dashboard</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header><strong>CS2 Toolkit Dashboard</strong><span id="status-pill">Loading</span></header>
  <main>
    <aside>
      <button id="start">Start</button>
      <button id="restart">Restart</button>
      <button id="stop">Stop</button>
      <select id="mode">
        <option value="auto_derank">Auto Derank</option>
        <option value="derank_afk">Derank AFK</option>
        <option value="afk_reconnect">AFK Reconnect</option>
      </select>
    </aside>
    <section>
      <div id="cards"></div>
      <form id="config-form"></form>
      <pre id="logs"></pre>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""

STYLE_CSS = "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#17202c}header{height:56px;background:#101720;color:#edf4fa;display:flex;align-items:center;justify-content:space-between;padding:0 18px}main{display:grid;grid-template-columns:260px 1fr;gap:16px;padding:16px}aside,section{background:white;border:1px solid #dde4eb;border-radius:8px;padding:14px}button,select,input,textarea{font:inherit}button{width:100%;margin:0 0 8px;padding:9px;border:0;border-radius:7px;background:#334155;color:white}#start{background:#16a34a}#stop{background:#fff1f2;color:#be123c;border:1px solid #fecdd3}#cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px}label{display:grid;gap:4px;margin-bottom:8px}pre{background:#0b1118;color:#d8e3ec;border-radius:8px;padding:12px;min-height:180px;overflow:auto}"

APP_JS = """async function api(path, options={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  return await res.json();
}
async function refresh() {
  const state = await api('/api/state');
  document.getElementById('status-pill').textContent = state.running ? 'RUNNING' : 'STOPPED';
  document.getElementById('cards').innerHTML = [
    ['Admin', state.admin ? 'Yes' : 'No'],
    ['PID', state.pid || '-'],
    ['Mode', state.mode],
    ['CS2 windows', state.cs2WindowCount ?? '-']
  ].map(([k,v]) => `<div class="card"><small>${k}</small><br><strong>${v}</strong></div>`).join('');
  const logs = await api('/api/logs');
  document.getElementById('logs').textContent = logs.lines.join('\\n');
}
async function send(path, body={}) {
  await api(path, {method:'POST', body:JSON.stringify(body)});
  await refresh();
}
document.getElementById('start').onclick = () => send('/api/start', {mode:document.getElementById('mode').value});
document.getElementById('stop').onclick = () => send('/api/stop');
document.getElementById('restart').onclick = () => send('/api/restart', {mode:document.getElementById('mode').value});
setInterval(refresh, 1500);
refresh();
"""


class DashboardApp:
    def __init__(self, supervisor=None):
        self.supervisor = supervisor or DashboardSupervisor()

    def dispatch(self, method, path, body):
        route = urlparse(path).path
        try:
            if method == "GET" and route == "/":
                return self._text(200, INDEX_HTML, "text/html; charset=utf-8")
            if method == "GET" and route == "/style.css":
                return self._text(200, STYLE_CSS, "text/css; charset=utf-8")
            if method == "GET" and route == "/app.js":
                return self._text(200, APP_JS, "application/javascript; charset=utf-8")
            if method == "GET" and route == "/api/state":
                return self._json(200, self.supervisor.state())
            if method == "GET" and route == "/api/logs":
                return self._json(200, {"lines": self.supervisor.logs.lines()})
            if method == "GET" and route == "/api/config":
                return self._json(200, {"config": editable_dashboard_config()})
            if method == "POST" and route == "/api/start":
                payload = self._payload(body)
                return self._result(self.supervisor.start(payload.get("mode", "auto_derank")))
            if method == "POST" and route == "/api/stop":
                return self._result(self.supervisor.stop())
            if method == "POST" and route == "/api/restart":
                payload = self._payload(body)
                return self._result(self.supervisor.restart(payload.get("mode")))
            if method == "POST" and route == "/api/config":
                return self._json(200, write_dashboard_config(self._payload(body)))
            return self._json(404, {"ok": False, "error": "not found"})
        except ValueError as exc:
            return self._json(400, {"ok": False, "error": str(exc)})

    def _payload(self, body):
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _json(self, status, value):
        return status, {"Content-Type": "application/json"}, json.dumps(value).encode("utf-8")

    def _result(self, value):
        status = 200 if value.get("ok") else 409
        return self._json(status, value)

    def _text(self, status, value, content_type):
        return status, {"Content-Type": content_type}, value.encode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_dashboard_http
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add cs2_overlay/dashboard.py tests/test_dashboard_http.py
git commit -m "Add dashboard HTTP API"
```

## Task 4: HTTP Server Entry Point

**Files:**
- Modify: `cs2_overlay/dashboard.py`
- Create: `dashboard.py`
- Test: `tests/test_dashboard_http.py`

- [ ] **Step 1: Add failing entry-point test**

Append to `tests/test_dashboard_http.py`:

```python
class DashboardEntrypointTests(unittest.TestCase):
    def test_make_handler_writes_dispatch_response(self):
        app = dashboard.DashboardApp(supervisor=FakeSupervisor())
        handler_cls = dashboard.make_handler(app)

        self.assertEqual(handler_cls.app, app)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_dashboard_http
```

Expected: fail because `make_handler` is not implemented.

- [ ] **Step 3: Implement handler and CLI main**

Append to `cs2_overlay/dashboard.py`:

```python
import argparse
import webbrowser


def make_handler(app):
    class DashboardHandler(BaseHTTPRequestHandler):
        app = None

        def do_GET(self):
            self._serve()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self._serve(self.rfile.read(length))

        def log_message(self, format, *args):
            return

        def _serve(self, body=b""):
            status, headers, response = self.app.dispatch(self.command, self.path, body)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    DashboardHandler.app = app
    return DashboardHandler


def run_dashboard(host=DEFAULT_HOST, port=DEFAULT_PORT, open_browser=True):
    app = DashboardApp()
    server = ThreadingHTTPServer((host, port), make_handler(app))
    url = f"http://{host}:{port}"
    print(f"CS2 Toolkit dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.supervisor.stop()
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the CS2 Toolkit local dashboard.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    run_dashboard(args.host, args.port, open_browser=not args.no_browser)
```

Create `dashboard.py`:

```python
"""CS2 Toolkit local dashboard entry point."""

from cs2_overlay.dashboard import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_dashboard_http
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add dashboard.py cs2_overlay/dashboard.py tests/test_dashboard_http.py
git commit -m "Add dashboard entry point"
```

## Task 5: Dashboard Config UI

**Files:**
- Modify: `cs2_overlay/dashboard.py`
- Test: `tests/test_dashboard_http.py`

- [ ] **Step 1: Add static UI coverage**

Add to `DashboardHttpTests`:

```python
    def test_dashboard_includes_config_form_targets(self):
        app = dashboard.DashboardApp(supervisor=FakeSupervisor())

        _status, _headers, body = app.dispatch("GET", "/app.js", b"")

        self.assertIn("/api/config", body)
        self.assertIn("ALT_FRIEND_CODES", body)
        self.assertIn("MATCH_THRESHOLD", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_dashboard_http
```

Expected: fail because `APP_JS` does not render config controls.

- [ ] **Step 3: Extend `APP_JS` with config rendering and save**

Update `APP_JS` so it includes:

```javascript
const CONFIG_FIELDS = [
  ['AUTO_INVITE', 'checkbox'],
  ['HOST_MONITOR_INDEX', 'number'],
  ['GAME_MODE', 'select'],
  ['ALT_FRIEND_CODES', 'textarea'],
  ['MATCH_THRESHOLD', 'number'],
  ['MATCH_SCALES', 'text'],
  ['STARTUP_DELAY_SECS', 'number'],
  ['DEBUG', 'checkbox']
];
async function loadConfig() {
  const data = await api('/api/config');
  const config = data.config || {};
  const form = document.getElementById('config-form');
  form.innerHTML = CONFIG_FIELDS.map(([key, type]) => {
    const value = config[key];
    if (type === 'checkbox') return `<label><span>${key}</span><input data-key="${key}" type="checkbox" ${value ? 'checked' : ''}></label>`;
    if (type === 'textarea') return `<label><span>${key}</span><textarea data-key="${key}">${(value || []).join('\\n')}</textarea></label>`;
    if (type === 'select') return `<label><span>${key}</span><select data-key="${key}"><option value="competitive">competitive</option><option value="premier">premier</option></select></label>`;
    return `<label><span>${key}</span><input data-key="${key}" type="${type}" value="${Array.isArray(value) ? value.join(', ') : value ?? ''}"></label>`;
  }).join('') + '<button type="button" id="save-config">Save Config</button>';
  if (config.GAME_MODE) form.querySelector('[data-key="GAME_MODE"]').value = config.GAME_MODE;
  document.getElementById('save-config').onclick = saveConfig;
}
async function saveConfig() {
  const payload = {};
  document.querySelectorAll('[data-key]').forEach(el => {
    const key = el.dataset.key;
    if (el.type === 'checkbox') payload[key] = el.checked;
    else if (key === 'ALT_FRIEND_CODES') payload[key] = el.value.split('\\n').map(x => x.trim()).filter(Boolean);
    else if (key === 'MATCH_SCALES') payload[key] = el.value.split(',').map(x => Number(x.trim())).filter(x => !Number.isNaN(x));
    else if (el.type === 'number') payload[key] = Number(el.value);
    else payload[key] = el.value;
  });
  await send('/api/config', payload);
  await loadConfig();
}
loadConfig();
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_dashboard_http
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add cs2_overlay/dashboard.py tests/test_dashboard_http.py
git commit -m "Add dashboard config controls"
```

## Task 6: Documentation And Ignore Rules

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Add README dashboard instructions**

Add this section after the existing "Running" section:

```markdown
### Dashboard

To use the local browser dashboard instead of the console-only launcher, run from an elevated terminal:

```powershell
python dashboard.py
```

The dashboard opens on `http://127.0.0.1:8765` by default. It can start, stop, and restart the automation subprocess, choose the runtime mode, edit common `config.json` settings, and show recent logs.

Use `--no-browser` if you only want to start the server:

```powershell
python dashboard.py --no-browser
```
```

- [ ] **Step 2: Ignore brainstorming artifacts**

Add this line to `.gitignore`:

```gitignore
.superpowers/
```

- [ ] **Step 3: Commit**

```powershell
git add README.md .gitignore
git commit -m "Document dashboard launcher"
```

## Task 7: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run dashboard-specific tests**

Run:

```powershell
python -m unittest tests.test_dashboard_supervisor tests.test_dashboard_config tests.test_dashboard_http
```

Expected: all tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 3: Run compile check**

Run:

```powershell
python -m compileall -q launcher.py overlay.py dashboard.py cs2_overlay tests
```

Expected: no output and exit code 0.

- [ ] **Step 4: Smoke-start the server without opening a browser**

Run briefly from a terminal:

```powershell
python dashboard.py --no-browser --port 8766
```

Expected: prints `CS2 Toolkit dashboard: http://127.0.0.1:8766`. Stop with `Ctrl+C`.
