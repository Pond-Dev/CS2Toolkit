"""Derank cycle (DERANK state of controller.py).

Runs on host window (HOST_MONITOR_INDEX) only:
  Loop: see reconnect.png → click → wait RECONNECT_WAIT_SECS → press Z
  Until reconnect.png is gone (match over).
"""
import time

from .config import (
    DERANK_IMAGES,
    DISCONNECT_RETRY,
    DISCONNECT_TIMEOUT,
    FOCUS_DELAY,
    HOST_MONITOR_INDEX,
    RECONNECT_WAIT_SECS,
)
from .cs2_window import focus_window, list_cs2_windows, window_monitor_rect
from .input import find_and_click_in_rect, has_match_in_rect, load_templates, send_disconnect
from .log_setup import d_print, log


def _press_disconnect(hwnd):
    if not focus_window(hwnd):
        d_print(f"focus failed for hwnd={hwnd}")
        return False
    time.sleep(FOCUS_DELAY)
    send_disconnect()
    log(f"[+] Derank: disconnect pressed window {hwnd}")
    return True


def run_cycle():
    reconnect_tmpl = load_templates(only=DERANK_IMAGES)
    if not reconnect_tmpl:
        log("[WARN] Derank: no reconnect image in pic/ — cycle skipped")
        return

    windows = list_cs2_windows()
    if not windows or HOST_MONITOR_INDEX >= len(windows):
        log(f"[WARN] Derank: no host window at index {HOST_MONITOR_INDEX}")
        return
    host = windows[HOST_MONITOR_INDEX]
    rect = window_monitor_rect(host)

    log("[*] State: DERANK CYCLE")
    while True:
        if not has_match_in_rect(reconnect_tmpl, rect):
            log("[*] Derank: no reconnect — match over")
            return

        find_and_click_in_rect(reconnect_tmpl, rect)
        log(f"[+] Derank: reconnect clicked — waiting {RECONNECT_WAIT_SECS}s")
        time.sleep(RECONNECT_WAIT_SECS)

        deadline = time.monotonic() + DISCONNECT_TIMEOUT
        while time.monotonic() < deadline:
            if _press_disconnect(host):
                break
            time.sleep(DISCONNECT_RETRY)
