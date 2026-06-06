"""CS2 Toolkit — entry point."""
import os
import threading
import time

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
    threading.Thread(target=automation_loop, daemon=True, name=automation_name).start()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
