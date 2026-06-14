"""CS2 Toolkit — entry point."""
import os

from cs2_overlay.config import DERANK_AFK_MODE, STARTUP_DELAY_SECS, VERSION
from cs2_overlay.core import BASE, disable_console_quick_edit, is_admin, log
from cs2_overlay.runtime import automation_for_mode, wait_for_automation_mode


def main():
    if disable_console_quick_edit():
        log("[*] Console QuickEdit disabled")

    log(
        f"[*] Overlay v{VERSION} start pid={os.getpid()} "
        f"admin={is_admin()} base={BASE}"
    )

    wait_for_automation_mode(DERANK_AFK_MODE, STARTUP_DELAY_SECS)

    automation_loop, automation_name = automation_for_mode(DERANK_AFK_MODE)
    # Run the automation on the MAIN thread (not a daemon thread): if it ever
    # raises out, the process exits non-zero so the launcher/run.bat supervisor
    # can restart it. A daemon thread that died would leave this process alive
    # but idle, and the supervisor would never restart it.
    log(f"[*] Automation start: {automation_name}")
    automation_loop()


if __name__ == "__main__":
    main()
