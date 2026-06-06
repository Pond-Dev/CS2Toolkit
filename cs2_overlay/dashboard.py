"""Local web dashboard for supervising CS2 Toolkit."""
from __future__ import annotations

import argparse
import os
import json
import subprocess
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import webbrowser

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


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CS2 Toolkit Dashboard</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <strong>CS2 Toolkit Dashboard</strong>
    <span id="status-pill">Loading</span>
  </header>
  <main>
    <aside>
      <button id="start" type="button">Start</button>
      <button id="restart" type="button">Restart</button>
      <button id="stop" type="button">Stop</button>
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

STYLE_CSS = (
    "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#17202c}"
    "header{height:56px;background:#101720;color:#edf4fa;display:flex;align-items:center;"
    "justify-content:space-between;padding:0 18px}"
    "main{display:grid;grid-template-columns:260px 1fr;gap:16px;padding:16px}"
    "aside,section{background:white;border:1px solid #dde4eb;border-radius:8px;padding:14px}"
    "button,select,input,textarea{font:inherit}"
    "button{width:100%;margin:0 0 8px;padding:9px;border:0;border-radius:7px;"
    "background:#334155;color:white}"
    "#start{background:#16a34a}"
    "#stop{background:#fff1f2;color:#be123c;border:1px solid #fecdd3}"
    "#cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}"
    ".card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px}"
    "label{display:grid;gap:4px;margin-bottom:8px}"
    "pre{background:#0b1118;color:#d8e3ec;border-radius:8px;padding:12px;"
    "min-height:180px;overflow:auto}"
)

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
        except (json.JSONDecodeError, ValueError) as exc:
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
