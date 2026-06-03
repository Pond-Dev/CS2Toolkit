"""Host party-invite actions (invite by friend code).

A library of steps the state machine (controller.py) calls during the INVITE
phase. The host (window ``HOST_MONITOR_INDEX``) invites each code in
``ALT_FRIEND_CODES``:

    open People -> People-Add        (INVITE_OPEN_IMAGES)
    click the friend-code box, clear it, type the code
    click the search-result row     (a fixed offset below the box, since the
                                      row is a different avatar per alt)
    click Invite on the card that opens   (INVITE_BUTTON_IMAGE)

The dialog is reopened per code so the code box is always empty (and therefore
locatable by code_field.png) regardless of what the previous invite left behind.
"""
import time

from .config import (
    ALT_FRIEND_CODES,
    FOCUS_DELAY,
    HOST_MONITOR_INDEX,
    INVITE_BUTTON_IMAGE,
    INVITE_CANCEL_IMAGE,
    INVITE_CODE_FIELD_FALLBACK_POS,
    INVITE_CODE_FIELD_IMAGE,
    INVITE_OPEN_IMAGES,
    INVITE_RESULT_DX,
    INVITE_RESULT_DY,
    INVITE_RESULT_ROW_POS,
    INVITE_STEP_WAIT,
)
from .cs2_window import focus_window, list_cs2_windows, window_client_rect
from .input import (
    clear_text_field,
    click_image_in_rect,
    click_point,
    locate_in_rect,
    paste_text,
)
from .log_setup import log

INVITE_CANCEL_ATTEMPTS = 5
INVITE_CANCEL_RETRY_WAIT = 0.35
INVITE_VERIFY_ATTEMPTS = 8
INVITE_VERIFY_WAIT = 0.25


def host_window():
    """The configured host window, or None if it isn't open yet."""
    windows = list_cs2_windows()
    if len(windows) > HOST_MONITOR_INDEX:
        return windows[HOST_MONITOR_INDEX]
    return None


def _open_dialog(rect, by_name):
    """Click People -> People-Add to open a fresh, empty friend-code dialog.
    Returns False if an open-step image is missing from pic/."""
    steps = tuple(INVITE_OPEN_IMAGES)
    for index, name in enumerate(steps):
        img = by_name.get(name.lower())
        if img is None:
            log(f"[WARN] Invite: missing {name} in pic/ — abort")
            return False
        click_image_in_rect(name.lower(), img, rect, all_matches=False)
        if index + 1 < len(steps):
            next_name = steps[index + 1]
            if not _wait_for_image(next_name, by_name, rect):
                log(f"[WARN] Invite: {next_name} did not appear after clicking {name}")
                return False
        time.sleep(INVITE_STEP_WAIT)
    return True


def _fallback_code_field_pos(rect):
    left, top, right, bottom = rect
    rel_x, rel_y = INVITE_CODE_FIELD_FALLBACK_POS
    return (
        left + round((right - left) * rel_x),
        top + round((bottom - top) * rel_y),
    )


def _code_field_pos(by_name, rect):
    field_name = INVITE_CODE_FIELD_IMAGE.lower()
    img = by_name.get(field_name)
    if img is not None:
        pos = locate_in_rect(field_name, img, rect)
        if pos is not None:
            return pos
        log("[WARN] Invite: code field template not found — using fallback position")
    else:
        log(f"[WARN] Invite: missing {INVITE_CODE_FIELD_IMAGE} — using fallback position")
    pos = _fallback_code_field_pos(rect)
    log(f"[*] Invite: fallback code field click at {pos}")
    return pos


def _result_row_pos(field_pos, rect):
    if INVITE_RESULT_ROW_POS is not None:
        left, top, right, bottom = rect
        rel_x, rel_y = INVITE_RESULT_ROW_POS
        return (
            left + round((right - left) * rel_x),
            top + round((bottom - top) * rel_y),
        )
    fx, fy = field_pos
    return fx + INVITE_RESULT_DX, fy + INVITE_RESULT_DY


def _wait_for_image(name, by_name, rect, attempts=INVITE_VERIFY_ATTEMPTS):
    image_name = name.lower()
    img = by_name.get(image_name)
    if img is None:
        return False
    for attempt in range(attempts):
        if locate_in_rect(image_name, img, rect) is not None:
            return True
        if attempt < attempts - 1:
            time.sleep(INVITE_VERIFY_WAIT)
    return False


def _wait_for_image_gone(name, by_name, rect, attempts=INVITE_VERIFY_ATTEMPTS):
    image_name = name.lower()
    img = by_name.get(image_name)
    if img is None:
        return True
    for attempt in range(attempts):
        if locate_in_rect(image_name, img, rect) is None:
            return True
        if attempt < attempts - 1:
            time.sleep(INVITE_VERIFY_WAIT)
    return False


def _close_invite_dialog(by_name, rect):
    cancel_name = INVITE_CANCEL_IMAGE.lower()
    cancel_img = by_name.get(cancel_name)
    if cancel_img is None:
        log(f"[WARN] Invite: missing {INVITE_CANCEL_IMAGE} in pic/ — add cancel.png to pic/ to enable inviting")
        return False
    for attempt in range(INVITE_CANCEL_ATTEMPTS):
        clicked = click_image_in_rect(cancel_name, cancel_img, rect, all_matches=False)
        if clicked and _wait_for_image_gone(cancel_name, by_name, rect):
            log("[+] Invite: dialog closed")
            return True
        if attempt < INVITE_CANCEL_ATTEMPTS - 1:
            time.sleep(INVITE_CANCEL_RETRY_WAIT)
    log(f"[WARN] Invite: cancel button not found after invite")
    return False


def _invite_one(by_name, rect, code):
    """Type one friend code, click the result row, then Invite on the card."""
    pos = _code_field_pos(by_name, rect)
    fx, fy = pos

    click_point(fx, fy)  # focus the field
    time.sleep(0.3)
    clear_text_field()
    paste_text(code)
    time.sleep(INVITE_STEP_WAIT)

    rx, ry = _result_row_pos((fx, fy), rect)
    log(f"[*] Invite: result row click at {(rx, ry)}")
    click_point(rx, ry)  # result row -> card
    time.sleep(INVITE_STEP_WAIT)

    btn_name = INVITE_BUTTON_IMAGE.lower()
    btn_img = by_name.get(btn_name)
    if btn_img is None or not _wait_for_image(btn_name, by_name, rect):
        log(f"[WARN] Invite: Invite button not found for {code}")
        _close_invite_dialog(by_name, rect)
        return False
    clicked = click_image_in_rect(btn_name, btn_img, rect, all_matches=False)
    if not clicked:
        log(f"[WARN] Invite: Invite button not found for {code}")
        _close_invite_dialog(by_name, rect)
        return False
    log(f"[+] Auto invite: {btn_name} clicked for {code} count={clicked}")
    time.sleep(INVITE_STEP_WAIT)
    if not _close_invite_dialog(by_name, rect):
        return False
    log(f"[+] Invite sent: {code}")
    return True


def run_invite(hwnd, rect, by_name):
    """Invite every code in ALT_FRIEND_CODES from the host window."""
    if not ALT_FRIEND_CODES:
        log("[*] Invite: ALT_FRIEND_CODES empty — nothing to invite")
        return False

    log(f"[*] Invite: inviting {len(ALT_FRIEND_CODES)} code(s) from host at {rect[:2]}")
    focus_window(hwnd)
    time.sleep(FOCUS_DELAY)
    rect = window_client_rect(hwnd) or rect
    log(f"[*] Invite: using host client rect {rect[:2]}..{rect[2:]}")

    # Reopen the dialog per code so the code box is always empty (and therefore
    # locatable by code_field.png) regardless of what the last invite left behind.
    for code in ALT_FRIEND_CODES:
        if not _open_dialog(rect, by_name):
            return False
        if not _invite_one(by_name, rect, code):
            return False
        time.sleep(INVITE_STEP_WAIT)
    return True
