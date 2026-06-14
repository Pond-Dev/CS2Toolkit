"""CS2 Toolkit — command-line launcher.

Supervises ``overlay.py``: starts it, lets its logs stream straight to
this console, and restarts it (with back-off) if it exits. Press Ctrl+C to stop.

Run as Administrator so the overlay can send synthetic keyboard/mouse input:

    py -3 launcher.py
"""
import ctypes
import os
import subprocess
import sys
import time

VERSION = "1.4"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OVERLAY_SCRIPT = os.path.join(BASE_DIR, "overlay.py")

RESTART_DELAY = 2.0
RESTART_BACKOFF = 1.5
RESTART_MAX_DELAY = 30.0
RESTART_RESET_AFTER = 60


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def overlay_cmd():
    return [sys.executable, OVERLAY_SCRIPT]


def _terminate(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
    except Exception:
        pass


def supervise():
    """Run the overlay, restarting it with back-off whenever it exits.

    Returns when the user presses Ctrl+C.
    """
    delay = RESTART_DELAY
    while True:
        started = time.monotonic()
        proc = subprocess.Popen(overlay_cmd(), cwd=BASE_DIR)
        try:
            proc.wait()
        except KeyboardInterrupt:
            _terminate(proc)
            return

        # Reset the back-off after a healthy run; escalate after a quick crash.
        if time.monotonic() - started >= RESTART_RESET_AFTER:
            delay = RESTART_DELAY
        print(f"[WARN] Overlay exited ({proc.returncode}); restarting in {delay:.0f}s.")
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            return
        delay = min(delay * RESTART_BACKOFF, RESTART_MAX_DELAY)


def main():
    print(f"CS2 Toolkit v{VERSION}")
    print(f"Base: {BASE_DIR}")
    if not is_admin():
        print("[WARN] Not running as Administrator — synthetic keyboard/mouse input will fail.")
    print("Overlay starting. Press Ctrl+C to stop.\n")
    supervise()
    print("\n[*] Stopped.")


if __name__ == "__main__":
    main()
