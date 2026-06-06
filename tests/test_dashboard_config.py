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
            path.write_text(
                json.dumps({"CUSTOM_KEEP": 123, "GAME_MODE": "competitive"}),
                encoding="utf-8",
            )

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
