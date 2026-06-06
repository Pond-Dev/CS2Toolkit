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

    def test_start_conflict_returns_409(self):
        class ConflictSupervisor(FakeSupervisor):
            def start(self, mode):
                return {"ok": False, "error": "automation already running"}

        app = dashboard.DashboardApp(supervisor=ConflictSupervisor())

        status, _headers, body = app.dispatch("POST", "/api/start", b"{}")

        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "automation already running")

    def test_api_logs_returns_recent_lines(self):
        supervisor = FakeSupervisor()
        supervisor.logs.add("[*] hello")
        app = dashboard.DashboardApp(supervisor=supervisor)

        status, _headers, body = app.dispatch("GET", "/api/logs", b"")

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["lines"], ["[*] hello"])

    def test_static_index_is_served(self):
        app = dashboard.DashboardApp(supervisor=FakeSupervisor())

        status, headers, body = app.dispatch("GET", "/", b"")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("CS2 Toolkit Dashboard", body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
