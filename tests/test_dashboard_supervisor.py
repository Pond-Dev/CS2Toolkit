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
