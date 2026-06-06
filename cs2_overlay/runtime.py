"""Launch wiring: startup delay + which automation loop to run for each mode."""
import time

from .core import log
from .flows import afk_loop, controller_loop


def wait_before_automation(delay, sleep=time.sleep, log_func=log):
    """Pause before starting automation threads."""
    if delay <= 0:
        return
    log_func(f"[*] Startup delay: waiting {delay:g}s before automation")
    sleep(delay)


def wait_for_automation_mode(derank_afk_mode, delay_secs, wait_func=wait_before_automation):
    if derank_afk_mode:
        return
    wait_func(delay_secs)


def automation_for_mode(derank_afk_mode):
    if derank_afk_mode:
        return afk_loop, "derank_afk"
    return controller_loop, "controller"
