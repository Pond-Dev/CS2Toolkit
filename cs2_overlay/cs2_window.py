"""CS2 window discovery — find HWND, client rect, foreground check.

The HWND is cached for 1s; FindWindow isn't expensive but doing it on
every poll burns a syscall."""
import time

import win32api
import win32con
import win32gui
import win32process

from . import state
from .config import WIN


def get_cs2_hwnd():
    """Return CS2's HWND (or 0). Cached for 1s."""
    now = time.monotonic()
    cache = state._cs2_hwnd_cache
    if now - cache["checked"] < 1.0 and cache["hwnd"]:
        if win32gui.IsWindow(cache["hwnd"]):
            return cache["hwnd"]
    hwnd = win32gui.FindWindow(None, WIN)
    cache["hwnd"] = hwnd
    cache["checked"] = now
    return hwnd


def get_cs2_rect():
    hwnd = get_cs2_hwnd()
    if not hwnd:
        return None
    try:
        rect = win32gui.GetClientRect(hwnd)
        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        return pt[0], pt[1], rect[2], rect[3]
    except Exception:
        return None


def window_client_rect(hwnd):
    """Client rect for a specific CS2 window as (left, top, right, bottom)."""
    try:
        rect = win32gui.GetClientRect(hwnd)
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        return left, top, left + rect[2], top + rect[3]
    except Exception:
        return None


def cs2_is_foreground():
    try:
        fg = win32gui.GetForegroundWindow()
        if not fg:
            return False
        return win32gui.GetWindowText(fg) == WIN
    except Exception:
        return False


def window_is_foreground(hwnd):
    """True only when this exact HWND is the current foreground window."""
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def any_cs2_window():
    """True if at least one CS2 window exists anywhere (any monitor / instance).

    Used by the multi-instance clicker instead of cs2_is_foreground(): with
    several sandboxed CS2 windows spread across monitors, only one can ever be
    foreground, so we gate on "a CS2 is open" rather than "CS2 is focused".
    """
    found = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == WIN:
            found.append(hwnd)
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return False
    return bool(found)


def window_monitor_rect(hwnd):
    """(left, top, right, bottom) of the monitor the window mostly sits on,
    in logical (cursor-space) coordinates."""
    try:
        hmon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        return tuple(win32api.GetMonitorInfo(hmon)["Monitor"])
    except Exception:
        return (0, 0, 0, 0)


def list_cs2_windows():
    """Every visible CS2 top-level window, ordered by on-screen position.

    Top row windows come first, left-to-right; lower rows follow. This makes
    HOST_MONITOR_INDEX=0 target the upper-left CS2 window in tiled layouts."""
    found = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == WIN:
            found.append(hwnd)
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return []
    return sorted(found, key=_window_position_key)


def _window_position_key(hwnd):
    """Sort key for tiled CS2 windows: top-to-bottom, then left-to-right."""
    rect = window_client_rect(hwnd) or window_monitor_rect(hwnd)
    left, top, _right, _bottom = rect
    return top, left


def window_pid(hwnd):
    """The process id owning a window (0 on failure)."""
    try:
        _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return 0


def _tap_alt():
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


def _attach_thread_input(hwnd):
    """Temporarily attach this thread to the foreground/target UI threads."""
    attached = []
    try:
        current_thread = win32api.GetCurrentThreadId()
        foreground = win32gui.GetForegroundWindow()
        thread_ids = []
        if foreground:
            thread_ids.append(win32process.GetWindowThreadProcessId(foreground)[0])
        thread_ids.append(win32process.GetWindowThreadProcessId(hwnd)[0])
        for tid in thread_ids:
            if tid and tid != current_thread and tid not in attached:
                win32process.AttachThreadInput(current_thread, tid, True)
                attached.append(tid)
    except Exception:
        pass
    return attached


def _detach_thread_input(attached):
    try:
        current_thread = win32api.GetCurrentThreadId()
        for tid in reversed(attached):
            try:
                win32process.AttachThreadInput(current_thread, tid, False)
            except Exception:
                pass
    except Exception:
        pass


def focus_window(hwnd):
    """Bring a CS2 window to the foreground so keyboard input lands on it.

    Windows refuses SetForegroundWindow from a background process while another
    app holds the foreground lock; a synthetic ALT tap is the usual unlock."""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        for _ in range(5):
            if window_is_foreground(hwnd):
                return True
            _tap_alt()
            attached = _attach_thread_input(hwnd)
            try:
                try:
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
                win32gui.SetForegroundWindow(hwnd)
            finally:
                _detach_thread_input(attached)
            time.sleep(0.08)
        return window_is_foreground(hwnd)
    except Exception:
        return False
