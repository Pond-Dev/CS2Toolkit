"""DERANK AFK bot mode: accept popups, then disconnect back to lobby."""
import time

from .autoclick import accept_reconnect, auto_clicks
from .config import AUTO_RECONNECT, FOCUS_DELAY, STATE_POLL
from .cs2_window import (
    focus_window,
    list_cs2_windows,
    window_is_foreground,
    window_monitor_rect,
)
from .input import any_match_in, load_templates, scan_matches, send_disconnect
from .log_setup import d_print, log

WARMUP_IMAGE_PREFIX = "warmup"
WARMUP_DISCONNECT_FOCUS_DELAY = 0.05

_last_window_state: dict = {}  # hwnd -> label str


def _press_disconnect_on_windows(
    windows,
    focus_func=focus_window,
    is_foreground_func=window_is_foreground,
    press_disconnect=send_disconnect,
    sleep=time.sleep,
    log_func=log,
    reason="disconnect",
    focus_delay=FOCUS_DELAY,
):
    count = 0
    for hwnd in windows:
        if not focus_func(hwnd):
            d_print(f"DERANK AFK: focus failed for hwnd={hwnd}")
            continue
        sleep(focus_delay)
        if not is_foreground_func(hwnd):
            d_print(f"DERANK AFK: focus did not land on hwnd={hwnd}; disconnect skipped")
            continue
        press_disconnect()
        count += 1
        log_func(f"[*] DERANK AFK: {reason}; disconnected window {hwnd}")
    return count


def disconnect_warmup_windows(
    windows,
    by_name=None,
    focus_func=focus_window,
    is_foreground_func=window_is_foreground,
    press_disconnect=send_disconnect,
    sleep=time.sleep,
    log_func=log,
):
    """Disconnect CS2 windows that show the warmup image."""
    # Prune closed windows so stale hwnd entries don't suppress log lines.
    active = set(windows)
    for stale in [h for h in list(_last_window_state) if h not in active]:
        del _last_window_state[stale]

    warmup_templates = [
        (name, img) for name, img in (by_name or {}).items()
        if name.startswith(WARMUP_IMAGE_PREFIX)
    ]
    if not warmup_templates:
        return 0

    matches = scan_matches(warmup_templates)

    # Check all windows — if any shows warmup, disconnect every window.
    any_in_warmup = any(
        any_match_in(matches, window_monitor_rect(hwnd)) for hwnd in windows
    )
    label = "WARMUP" if any_in_warmup else "LOBBY"

    for hwnd in windows:
        prev = _last_window_state.get(hwnd)
        if prev != label:
            _last_window_state[hwnd] = label
            log_func(f"[*] DERANK AFK: hwnd={hwnd} -> {label}")

    if not any_in_warmup:
        return 0

    return _press_disconnect_on_windows(
        windows,
        focus_func=focus_func,
        is_foreground_func=is_foreground_func,
        press_disconnect=press_disconnect,
        sleep=sleep,
        log_func=log_func,
        reason="warmup (image)",
        focus_delay=WARMUP_DISCONNECT_FOCUS_DELAY,
    )


def afk_tick(by_name):
    """One AFK pass: accept popups, reconnect if enabled, disconnect on warmup."""
    auto_clicks(by_name, suppress_reconnect=False)
    if AUTO_RECONNECT:
        accept_reconnect(by_name)
        return 0
    return disconnect_warmup_windows(list_cs2_windows(), by_name)


def afk_loop():
    by_name = dict(load_templates())
    log("[*] DERANK AFK: auto accept + disconnect mode started")
    log(f"[*] Templates loaded ({len(by_name)}): {', '.join(sorted(by_name)) or 'NONE'}")
    while True:
        afk_tick(by_name)
        time.sleep(STATE_POLL)
