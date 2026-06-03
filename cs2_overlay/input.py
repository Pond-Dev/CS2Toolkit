"""Synthetic input — keyboard + mouse events sent into the CS2 window.

Every action checks ``cs2_is_foreground()`` first so we never fire input at the
wrong app (e.g. while the user has alt-tabbed). The clicker scans every ``.png``
in ``pic/`` against a single screenshot and clicks the first button it matches.
"""
import os
import time

import cv2
import numpy as np
import win32api
import win32clipboard
import win32con
from PIL import ImageGrab

from .config import (
    CLICK_SUPPRESSED_BY,
    DISCONNECT_KEY_VK,
    MATCH_SCALES,
    MATCH_THRESHOLD,
)
from .cs2_window import cs2_is_foreground
from .log_setup import d_print, log
from .paths import PIC_DIR


def send_disconnect():
    if not cs2_is_foreground():
        d_print("send_disconnect skipped — CS2 not foreground")
        return
    win32api.keybd_event(DISCONNECT_KEY_VK, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(DISCONNECT_KEY_VK, 0, 2, 0)


def _click(x, y):
    win32api.SetCursorPos((x, y))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)


def load_templates(only=None, exclude=None):
    """Load .png files in pic/ as (name, grayscale image) pairs.

    ``only``/``exclude`` (collections of file names) let the parallel clicker and
    the derank cycle each load just the buttons they own. Name matching is
    case-insensitive so accept.PNG and accept.png are treated alike."""
    if not os.path.isdir(PIC_DIR):
        log(f"[WARN] pic folder not found: {PIC_DIR}")
        return []
    only = {n.lower() for n in only} if only is not None else None
    exclude = {n.lower() for n in exclude} if exclude is not None else None
    templates = []
    for name in sorted(os.listdir(PIC_DIR)):
        low = name.lower()
        if not low.endswith(".png"):
            continue
        if only is not None and low not in only:
            continue
        if exclude is not None and low in exclude:
            continue
        img = cv2.imread(os.path.join(PIC_DIR, name), cv2.IMREAD_GRAYSCALE)
        if img is None:
            log(f"[WARN] Could not read image: {name}")
            continue
        # Store the normalized (lowercase) name so config-based matching —
        # CLICK_SUPPRESSED_BY, DERANK_IMAGES — works regardless of how the file
        # is cased on disk (e.g. correct.PNG vs correct.png).
        templates.append((low, img))
    if not templates:
        log(f"[WARN] No usable .png images in {PIC_DIR}")
    return templates


def _locate(template, screen_gray):
    """Return the center (x, y) of the best match, or None if below threshold."""
    result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < MATCH_THRESHOLD:
        return None
    h, w = template.shape
    return max_loc[0] + w // 2, max_loc[1] + h // 2


# Per-image memory of the scale that last matched, so steady-state scanning only
# runs one matchTemplate per template instead of the whole MATCH_SCALES sweep.
# Keyed by template name (lowercase); see _locate_all.
_scale_cache = {}


def _scaled_templates(template, scales):
    """Yield (scale, resized_template) for each requested scale.

    1.0 reuses the original (no resize). Scales that shrink the template below a
    usable size are skipped — a few-pixel patch matches noise everywhere."""
    h, w = template.shape
    for s in scales:
        if s == 1.0:
            yield 1.0, template
            continue
        nw, nh = max(1, round(w * s)), max(1, round(h * s))
        if nw < 8 or nh < 8:
            continue
        interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
        yield s, cv2.resize(template, (nw, nh), interpolation=interp)


def _best_scale_result(template, screen_gray, scales):
    """Run matchTemplate at each scale; return the highest-scoring
    (max_val, scale, resized_template, result) tuple, or None if none fit."""
    sh, sw = screen_gray.shape
    best = None
    for scale, tmpl in _scaled_templates(template, scales):
        th, tw = tmpl.shape
        if th > sh or tw > sw:
            continue
        result = cv2.matchTemplate(screen_gray, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if best is None or max_val > best[0]:
            best = (max_val, scale, tmpl, result)
    return best


def _locate_all(template, screen_gray, name=None, threshold=MATCH_THRESHOLD, scales=MATCH_SCALES):
    """Return centers (x, y) of *every* match above threshold.

    With several CS2 windows on different monitors the same button appears more
    than once in one screenshot, so we can't use minMaxLoc (one best match).
    matchTemplate fires many near-duplicate hits per button, so we greedily keep
    the highest-scoring point and drop any later point within half a template of
    one already kept (simple non-max suppression).

    Multi-scale: the template is matched at each MATCH_SCALES size and the
    best-scoring scale wins, so buttons still match when CS2 runs windowed at a
    different size than the .png was cropped at. The winning scale is cached per
    ``name`` and tried first next time, so a locked-in scale costs one match.
    """
    scales = tuple(scales)
    cached = _scale_cache.get(name) if name else None
    best = None
    if cached is not None and cached in scales:
        best = _best_scale_result(template, screen_gray, (cached,))
        if best is None or best[0] < threshold:
            best = None  # window resized / cache stale — fall back to full sweep
    if best is None:
        best = _best_scale_result(template, screen_gray, scales)
    if best is None or best[0] < threshold:
        if best is not None and name:
            d_print(
                f"no match {name}: best {best[0]:.3f} @ {best[1]:.2f}x "
                f"(need {threshold})"
            )
        return []
    _, scale, tmpl, result = best
    if name:
        _scale_cache[name] = scale
    h, w = tmpl.shape
    ys, xs = np.where(result >= threshold)
    if len(xs) == 0:
        return []
    order = np.argsort(result[ys, xs])[::-1]
    kept = []
    for idx in order:
        cx = int(xs[idx]) + w // 2
        cy = int(ys[idx]) + h // 2
        if all(abs(cx - kx) > w // 2 or abs(cy - ky) > h // 2 for kx, ky in kept):
            kept.append((cx, cy))
    return kept


def _scale_to_cursor(x, y, cap_w, cap_h, screen_w, screen_h, origin_x=0, origin_y=0):
    """Map a screenshot point to SetCursorPos coordinates.

    ImageGrab captures *physical* pixels, but the overlay process is DPI-unaware
    so the cursor uses *logical* pixels. They differ whenever Windows display
    scaling isn't 100% (e.g. 125% → capture 2560 wide, cursor space 2048 wide),
    so a raw match point would click the wrong spot without this rescale.

    ``origin_x/origin_y`` is the virtual desktop's top-left in cursor space; it's
    non-zero (and can be negative) once a multi-monitor capture spans monitors
    that sit left of / above the primary one.
    """
    if not cap_w or not cap_h:
        return x, y
    return (
        origin_x + round(x * screen_w / cap_w),
        origin_y + round(y * screen_h / cap_h),
    )


def _point_in_rect(x, y, rect):
    left, top, right, bottom = rect
    return left <= x < right and top <= y < bottom


def any_match_in(matches, rect):
    """True if a precomputed ``scan_matches`` dict has any point inside ``rect``."""
    if not matches:
        return False
    return any(
        _point_in_rect(x, y, rect)
        for points in matches.values()
        for x, y in points
    )


def scan_matches(templates, threshold=MATCH_THRESHOLD, scales=MATCH_SCALES):
    """Screenshot all monitors once and return ``{name: [(x, y), ...]}`` of every
    match above threshold, in cursor coords. ``None`` if the grab failed."""
    try:
        screen = np.array(ImageGrab.grab(all_screens=True))
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)
    except Exception as e:
        d_print(f"screen grab failed: {e}")
        return None

    cap_h, cap_w = screen_gray.shape[:2]
    # Virtual desktop spans all monitors; its top-left can be negative when a
    # monitor sits left of / above the primary one.
    origin_x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    origin_y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    virt_w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    virt_h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

    matches = {}
    for name, template in templates:
        try:
            points = _locate_all(
                template,
                screen_gray,
                name,
                threshold=threshold,
                scales=scales,
            )
        except Exception as e:
            d_print(f"match {name} failed: {e}")
            continue
        mapped = [
            _scale_to_cursor(px, py, cap_w, cap_h, virt_w, virt_h, origin_x, origin_y)
            for px, py in points
        ]
        if mapped:
            matches[name] = mapped
    return matches


def scan_best_matches(templates, scales=MATCH_SCALES):
    """Best score/scale/position for each template in one screenshot.

    Used for diagnostics: unlike ``scan_matches`` this reports the best attempt
    even when it is below threshold, so command output can show why a template
    did not fire.
    """
    try:
        screen = np.array(ImageGrab.grab(all_screens=True))
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)
    except Exception as e:
        d_print(f"screen grab failed: {e}")
        return {}

    cap_h, cap_w = screen_gray.shape[:2]
    origin_x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    origin_y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    virt_w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    virt_h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

    best_by_name = {}
    for name, template in templates:
        try:
            best = _best_scale_result(template, screen_gray, scales)
        except Exception as e:
            d_print(f"best match {name} failed: {e}")
            continue
        if best is None:
            continue
        score, scale, tmpl, result = best
        _, _, _, max_loc = cv2.minMaxLoc(result)
        cx = max_loc[0] + tmpl.shape[1] // 2
        cy = max_loc[1] + tmpl.shape[0] // 2
        best_by_name[name] = {
            "score": float(score),
            "scale": scale,
            "point": _scale_to_cursor(
                cx,
                cy,
                cap_w,
                cap_h,
                virt_w,
                virt_h,
                origin_x,
                origin_y,
            ),
        }
    return best_by_name


def _blocked_in_rect(name, matches, rect):
    """Whether ``name``'s CLICK_SUPPRESSED_BY blocker is also matched in ``rect``
    (so ``name`` must not be clicked there). Needs the blocker to be present in
    ``matches`` — callers that want suppression must scan the blocker too."""
    blocker = CLICK_SUPPRESSED_BY.get(name)
    return bool(blocker) and any(
        _point_in_rect(bx, by, rect) for bx, by in matches.get(blocker, [])
    )


def find_and_click_in_rect(templates, rect, skip_click=()):
    """Click matching buttons whose center falls inside ``rect`` (one monitor).

    Every click is scoped to a single monitor so each instance is serviced one
    at a time. ``CLICK_SUPPRESSED_BY`` still applies within the rect (e.g. don't
    click correct.png while reconnect.png shows on it) — so pass the blocker
    image in ``templates`` even if it's in ``skip_click``. Names in
    ``skip_click`` are scanned (for suppression) but never clicked, letting the
    clicker honor reconnect.png without stealing it from the derank cycle.
    Returns the list of clicked template names."""
    skip = {n.lower() for n in skip_click}
    matches = scan_matches(templates)
    if not matches:
        return []
    clicked = []
    for name, _template in templates:
        if name in skip:
            continue
        blocked = _blocked_in_rect(name, matches, rect)
        for cx, cy in matches.get(name, []):
            if not _point_in_rect(cx, cy, rect):
                continue
            if blocked:
                d_print(f"skip {name} in rect — blocker still visible")
                continue
            _click(cx, cy)
            clicked.append(name)
    return clicked


def has_match_in_rect(templates, rect):
    """True if any of ``templates`` currently matches inside ``rect`` (no click)."""
    return any_match_in(scan_matches(templates), rect)


def count_distinct_in_rect(named_templates, rect):
    """Count distinct positions matched by any of ``named_templates`` inside
    ``rect``, de-duplicating hits that land on the same spot.

    ``_locate_all`` already de-dupes within one template; this also de-dupes
    *across* templates, so a lobby slot matched by more than one image (repeated
    frame colors, overlapping avatars) is counted once. Used to count how many
    player slots are filled."""
    matches = scan_matches(named_templates)
    if not matches:
        return 0
    sizes = {name.lower(): tmpl.shape[:2] for name, tmpl in named_templates}
    points = []
    for name, pts in matches.items():
        h, w = sizes.get(name, (20, 20))
        radius = max(w, h) // 2
        for x, y in pts:
            if _point_in_rect(x, y, rect):
                points.append((x, y, radius))
    kept = []
    for x, y, radius in points:
        if all(abs(x - kx) > radius or abs(y - ky) > radius for kx, ky in kept):
            kept.append((x, y))
    return len(kept)


def click_point(x, y):
    """Single left click at cursor coords. Caller ensures the right window is
    focused (the invite macro focuses the host first)."""
    _click(x, y)


def locate_in_rect(name, template, rect):
    """Center (x, y) of the first match of one template inside ``rect``, or None.
    Used to anchor offset clicks (e.g. the search-result row below the code box)."""
    matches = scan_matches([(name, template)])
    if not matches:
        return None
    for x, y in matches.get(name, []):
        if _point_in_rect(x, y, rect):
            return x, y
    return None


_NO_CLIPBOARD_TEXT = object()


def _get_clipboard_text():
    win32clipboard.OpenClipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return _NO_CLIPBOARD_TEXT
        return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _set_clipboard_text(text):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _press_ctrl_v():
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord("V"), 0, 0, 0)
    time.sleep(0.02)
    win32api.keybd_event(ord("V"), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.15)


def _paste_via_clipboard(
    text,
    get_clipboard_text=_get_clipboard_text,
    set_clipboard_text=_set_clipboard_text,
    press_paste=_press_ctrl_v,
):
    previous = _NO_CLIPBOARD_TEXT
    try:
        previous = get_clipboard_text()
    except Exception as e:
        d_print(f"clipboard read failed: {e}")

    set_clipboard_text(text)
    try:
        press_paste()
    finally:
        if previous is not _NO_CLIPBOARD_TEXT:
            try:
                set_clipboard_text(previous)
            except Exception as e:
                d_print(f"clipboard restore failed: {e}")


def paste_text(text):
    """Paste text into the focused CS2 text field.

    This avoids VkKeyScan/current-keyboard-layout issues when the active layout
    is Thai or another non-Latin layout. Falls back to per-key typing if the
    clipboard path is unavailable.
    """
    if not cs2_is_foreground():
        d_print("paste_text skipped — CS2 not foreground")
        return
    try:
        _paste_via_clipboard(text)
    except Exception as e:
        d_print(f"paste_text failed ({e}); falling back to key typing")
        type_text(text)


def type_text(text):
    """Type ``text`` into the focused field via synthetic keystrokes.

    Uses VkKeyScan, so the host's active keyboard layout must be Latin/EN (friend
    codes are A-Z/0-9/'-'). No-op unless a CS2 window is foreground."""
    if not cs2_is_foreground():
        d_print("type_text skipped — CS2 not foreground")
        return
    for ch in text:
        vk = win32api.VkKeyScan(ch)
        if vk == -1:
            d_print(f"type_text: no key for {ch!r}")
            continue
        code = vk & 0xFF
        shift = (vk >> 8) & 0x01
        if shift:
            win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
        win32api.keybd_event(code, 0, 0, 0)
        time.sleep(0.02)
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)
        if shift:
            win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)


def clear_text_field():
    """Select-all (Ctrl+A) then Delete to empty the focused text field."""
    if not cs2_is_foreground():
        return
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord("A"), 0, 0, 0)
    time.sleep(0.02)
    win32api.keybd_event(ord("A"), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)
    win32api.keybd_event(win32con.VK_DELETE, 0, 0, 0)
    time.sleep(0.02)
    win32api.keybd_event(win32con.VK_DELETE, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)


def click_image_in_rect(name, template, rect, all_matches=True):
    """Click one template's matches inside ``rect``; return how many were clicked.

    Used by the invite macro to drive one button per step. ``all_matches`` clicks
    every hit (e.g. an add button per online friend); otherwise just the first."""
    matches = scan_matches([(name, template)])
    if not matches:
        return 0
    points = [p for p in matches.get(name, []) if _point_in_rect(p[0], p[1], rect)]
    if not all_matches:
        points = points[:1]
    for cx, cy in points:
        _click(cx, cy)
    return len(points)
