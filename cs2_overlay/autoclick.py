"""Always-on per-monitor accepts shared by every phase (controller states AND
the derank cycle). Because the whole app runs on one thread, calling these from
each polling loop is safe — there is never a second clicker fighting for focus.

- ``accept_ready_check``: click the match ready-check (accept.png) on every
  monitor that shows it.
- ``accept_invite``: click the party-invite confirm (correct.png) on every
  monitor that shows it. The derank flow keeps a reconnect.png blocker enabled
  so it never steps on the reconnect sequence; derank AFK mode disables that blocker.
"""
import time

from .config import ACCEPT_INVITE_IMAGE, FOCUS_DELAY, READY_ACCEPT_IMAGE
from .cs2_window import focus_window, list_cs2_windows, window_monitor_rect
from .input import any_match_in, find_and_click_in_rect, scan_matches
from .log_setup import log

RECONNECT_IMAGE = "reconnect.png"


def click_image_on(name, img, windows, action_label=None):
    """Focus each window whose monitor shows ``img`` and click it there. Returns
    the number of clicks."""
    matches = scan_matches([(name, img)])
    if not matches:
        return 0
    total = 0
    for hwnd in windows:
        rect = window_monitor_rect(hwnd)
        if not any_match_in(matches, rect):
            continue
        focus_window(hwnd)
        time.sleep(FOCUS_DELAY)
        clicked = len(find_and_click_in_rect([(name, img)], rect))
        if clicked and action_label:
            log(f"[+] {action_label}: {name} clicked window {hwnd} count={clicked}")
        total += clicked
    return total


def accept_ready_check(by_name):
    """Click the match ready-check on every monitor that shows it."""
    name = READY_ACCEPT_IMAGE.lower()
    img = by_name.get(name)
    if img is not None:
        return click_image_on(name, img, list_cs2_windows(), action_label="Auto accept")
    return 0


def accept_invite(by_name, suppress_reconnect=True):
    """Click correct.png on every monitor that shows it, except monitors that are
    also showing reconnect.png when ``suppress_reconnect`` is enabled."""
    name = ACCEPT_INVITE_IMAGE.lower()
    img = by_name.get(name)
    if img is None:
        return 0
    templates = [(name, img)]
    reconnect = by_name.get(RECONNECT_IMAGE) if suppress_reconnect else None
    if suppress_reconnect and reconnect is not None:
        templates.append((RECONNECT_IMAGE, reconnect))
    matches = scan_matches(templates)
    if not matches:
        return 0
    total = 0
    for hwnd in list_cs2_windows():
        rect = window_monitor_rect(hwnd)
        correct_here = any_match_in({name: matches.get(name, [])}, rect)
        reconnect_here = suppress_reconnect and any_match_in(
            {RECONNECT_IMAGE: matches.get(RECONNECT_IMAGE, [])},
            rect,
        )
        if not correct_here or reconnect_here:
            continue
        focus_window(hwnd)
        time.sleep(FOCUS_DELAY)
        clicked = len(find_and_click_in_rect([(name, img)], rect))
        if clicked:
            log(f"[+] Auto accept: {name} clicked window {hwnd} count={clicked}")
        total += clicked
    return total


def accept_reconnect(by_name):
    """Click reconnect.png on every monitor showing it."""
    name = RECONNECT_IMAGE.lower()
    img = by_name.get(name)
    if img is not None:
        return click_image_on(name, img, list_cs2_windows(), action_label="Auto reconnect")
    return 0


def auto_clicks(by_name, suppress_reconnect=True):
    """One pass of both always-on accepts (ready-check + invite confirm)."""
    return {
        "ready": accept_ready_check(by_name),
        "invite": accept_invite(by_name, suppress_reconnect=suppress_reconnect),
    }
