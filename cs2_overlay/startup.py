"""Startup timing helpers."""
import time

from .log_setup import log


def wait_before_automation(delay, sleep=time.sleep, log_func=log):
    """Pause before starting memory reads and automation threads."""
    if delay <= 0:
        return
    log_func(f"[*] Startup delay: waiting {delay:g}s before automation")
    sleep(delay)
