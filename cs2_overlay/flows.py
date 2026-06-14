"""Automation behaviors, built on the primitives in ``core.py``.

Everything runs on ONE thread, so there is never a second clicker fighting for
focus. The pieces:

- always-on accepts  — accept the ready-check / invite popup on every monitor
                       (called from every phase below)
- invite macro       — host invites each friend code (open dialog, type, invite)
- derank cycle       — disconnect <-> reconnect the host until the match ends
- controller         — the coordinated state machine: INVITE -> GO -> SEARCH ->
                       DERANK -> repeat (the normal mode)
- afk loop           — the alternate "derank AFK" mode: accept + disconnect when
                       GSI reports the match live, or accept + reconnect

See controller_loop / afk_loop for the two top-level entry points.
"""
import time

from .config import (
    ACCEPT_INVITE_IMAGE,
    ALT_FRIEND_CODES,
    AUTO_INVITE,
    AUTO_RECONNECT,
    DERANK_IMAGES,
    DISCONNECT_RETRY,
    DISCONNECT_TIMEOUT,
    FOCUS_DELAY,
    GO_IMAGE,
    GO_PRE_IMAGES,
    GO_TIMEOUT,
    HOST_MONITOR_INDEX,
    INVITE_ACCEPT_SECS,
    INVITE_BUTTON_IMAGE,
    INVITE_CANCEL_IMAGE,
    INVITE_CODE_FIELD_FALLBACK_POS,
    INVITE_CODE_FIELD_IMAGE,
    INVITE_OPEN_IMAGES,
    INVITE_RESULT_DX,
    INVITE_RESULT_DY,
    INVITE_RESULT_ROW_POS,
    INVITE_STEP_WAIT,
    LOBBY_LEAVE_IMAGE,
    LOBBY_READY_IMAGE,
    READY_ACCEPT_IMAGE,
    RECONNECT_WAIT_SECS,
    SEARCH_TIMEOUT,
    STATE_POLL,
)
from .core import (
    any_cs2_window,
    any_match_in,
    clear_text_field,
    click_image_in_rect,
    click_point,
    d_print,
    find_and_click_in_rect,
    focus_window,
    has_match_in_rect,
    list_cs2_windows,
    load_templates,
    locate_in_rect,
    log,
    paste_text,
    scan_matches,
    send_disconnect,
    window_client_rect,
    window_is_foreground,
    window_monitor_rect,
)
from .config import GSI_HOST, GSI_PORT, GSI_TOKEN, GSI_TRIGGER_PHASE
from .gsi import GsiListener

RECONNECT_IMAGE = "reconnect.png"


def start_gsi():
    """Start the one GSI listener that both derank loops read from (the single
    'reader'; every CS2 window is just an actuator the loop disconnects)."""
    return GsiListener(
        host=GSI_HOST, port=GSI_PORT, token=GSI_TOKEN,
        trigger_phase=GSI_TRIGGER_PHASE, log_func=log,
    ).start()


# ===== always-on per-monitor accepts =======================================
def click_image_on(name, img, windows, action_label=None):
    """Focus each window whose monitor shows ``img`` and click it there.
    Returns the number of clicks."""
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
        clicked = len(find_and_click_in_rect([(name, img)], rect, matches=matches))
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
            {RECONNECT_IMAGE: matches.get(RECONNECT_IMAGE, [])}, rect
        )
        if not correct_here or reconnect_here:
            continue
        focus_window(hwnd)
        time.sleep(FOCUS_DELAY)
        clicked = len(find_and_click_in_rect([(name, img)], rect, matches=matches))
        if clicked:
            log(f"[+] Auto accept: {name} clicked window {hwnd} count={clicked}")
        total += clicked
    return total


def accept_reconnect(by_name):
    """Click reconnect.png on host window (index 0) only."""
    name = RECONNECT_IMAGE.lower()
    img = by_name.get(name)
    if img is None:
        return 0
    windows = list_cs2_windows()
    if HOST_MONITOR_INDEX >= len(windows):
        return 0
    return click_image_on(name, img, [windows[HOST_MONITOR_INDEX]], action_label="Auto reconnect")


def auto_clicks(by_name, suppress_reconnect=True):
    """One pass of both always-on accepts (ready-check + invite confirm)."""
    return {
        "ready": accept_ready_check(by_name),
        "invite": accept_invite(by_name, suppress_reconnect=suppress_reconnect),
    }


# ===== host party-invite macro (INVITE phase) ==============================
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
    log("[WARN] Invite: cancel button not found after invite")
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


# ===== derank cycle (DERANK phase) =========================================
def _press_disconnect(hwnd):
    if not focus_window(hwnd):
        d_print(f"focus failed for hwnd={hwnd}")
        return False
    time.sleep(FOCUS_DELAY)
    send_disconnect()
    log(f"[+] Derank: disconnect pressed window {hwnd}")
    return True


def run_cycle():
    """Host-only: see reconnect.png -> click -> wait -> press Z, until reconnect
    is gone (match over)."""
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


# ===== coordinated state machine (normal mode) =============================
def _check_image_on_host(host, by_name, image_name):
    """True when image_name is visible on the host monitor."""
    name = image_name.lower()
    img = by_name.get(name)
    if img is None:
        return False
    rect = window_client_rect(host) or window_monitor_rect(host)
    return locate_in_rect(name, img, rect) is not None


def _lobby_ready(host, by_name):
    return LOBBY_READY_IMAGE and _check_image_on_host(host, by_name, LOBBY_READY_IMAGE)


def _is_searching(host, by_name):
    return _check_image_on_host(host, by_name, "stop_search.png")


def _state_invite(host, by_name):
    """Host invites the alts; the alts accept the invite popup (auto_clicks) until
    LOBBY_READY_IMAGE appears on the host or INVITE_ACCEPT_SECS elapses."""
    log("[*] State: INVITE")
    if not run_invite(host, window_monitor_rect(host), by_name):
        log("[WARN] Controller: invite flow incomplete; restarting from INVITE")
        return False

    deadline = time.monotonic() + INVITE_ACCEPT_SECS
    while time.monotonic() < deadline:
        auto_clicks(by_name)
        if _lobby_ready(host, by_name):
            log("[+] State: lobby ready — go")
            return True
        time.sleep(STATE_POLL)

    log("[WARN] Controller: INVITE timeout — leaving lobby and restarting")
    leave_name = LOBBY_LEAVE_IMAGE.lower()
    leave_img = by_name.get(leave_name)
    if leave_img is not None:
        click_image_on(leave_name, leave_img, [host])
    else:
        log(f"[WARN] Controller: {LOBBY_LEAVE_IMAGE} not in pic/ — can't leave lobby")
    return False


def _state_go(host, by_name):
    """Navigate play -> premier/competitive -> GO on the host, then start matchmaking."""
    log("[*] State: GO")
    go_name = GO_IMAGE.lower()
    go_img = by_name.get(go_name)
    if go_img is None:
        log(f"[WARN] Controller: missing {GO_IMAGE} in pic/ — can't start match")
        return False

    for nav_image in GO_PRE_IMAGES:
        nav_name = nav_image.lower()
        nav_img = by_name.get(nav_name)
        if nav_img is None:
            log(f"[*] State: GO nav: {nav_image} not in pic/ — skipping")
            continue
        if click_image_on(nav_name, nav_img, [host]):
            log(f"[+] State: GO nav: clicked {nav_image}")
        time.sleep(STATE_POLL)

    deadline = time.monotonic() + GO_TIMEOUT
    while time.monotonic() < deadline:
        auto_clicks(by_name)
        if click_image_on(go_name, go_img, [host]):
            log("[+] State: GO clicked")
            return True
        time.sleep(STATE_POLL)
    log("[WARN] Controller: GO not found — restarting from INVITE")
    return False


def _disconnect_all(windows):
    """Press Z on every CS2 window."""
    for hwnd in windows:
        if focus_window(hwnd):
            time.sleep(FOCUS_DELAY)
            send_disconnect()
            log(f"[+] Search: disconnect pressed window {hwnd}")


def _state_search_and_start(by_name, gsi):
    """Click accept on all windows until GSI reports the match has gone live,
    then disconnect every window."""
    log("[*] State: SEARCH")
    deadline = time.monotonic() + SEARCH_TIMEOUT
    while time.monotonic() < deadline:
        auto_clicks(by_name)
        if gsi.triggered():
            log("[+] State: match live (gsi) — waiting 3s then disconnecting all")
            time.sleep(3)
            _disconnect_all(list_cs2_windows())
            return True
        time.sleep(STATE_POLL)
    log("[WARN] Controller: match never started — restarting from INVITE")
    return False


def controller_loop():
    # Runs on the MAIN thread (see overlay.py): if anything in here raises, the
    # process exits and the launcher/run.bat supervisor restarts it with back-off.
    # That is the recovery path — we deliberately do NOT swallow errors here, so a
    # real failure surfaces in the console instead of spinning silently.
    by_name = dict(load_templates())
    gsi = start_gsi()
    log("[*] Controller: derank state machine started")
    while True:
        if not any_cs2_window():
            time.sleep(STATE_POLL)
            continue
        host = host_window()
        if host is None:
            time.sleep(STATE_POLL)
            continue

        # AUTO_INVITE off: don't invite/go/search — just derank games you set up
        # yourself. Auto-clicks still run (accept ready-check + invite confirm) so
        # a manually queued match is accepted, then wait for the game.
        if not AUTO_INVITE:
            auto_clicks(by_name)
            time.sleep(STATE_POLL)
            continue

        # reconnect.png visible — in a match, go straight to DERANK.
        if _check_image_on_host(host, by_name, "reconnect.png"):
            log("[*] State: reconnect detected — skipping to DERANK")
            run_cycle()
            time.sleep(3)
            continue

        # Already in queue — skip INVITE+GO, wait for game to start.
        if _is_searching(host, by_name):
            log("[*] State: already searching — skipping to SEARCH")
            if not _state_search_and_start(by_name, gsi):
                continue
            log("[*] State: DERANK")
            run_cycle()
            time.sleep(3)
            continue

        # Lobby already ready — skip INVITE, go straight to GO.
        if _lobby_ready(host, by_name):
            log("[+] State: lobby already ready — skipping INVITE")
            if not _state_go(host, by_name):
                continue
            if not _state_search_and_start(by_name, gsi):
                continue
            log("[*] State: DERANK")
            run_cycle()
            time.sleep(3)
            continue

        if not _state_invite(host, by_name):
            continue
        if not _state_go(host, by_name):
            continue
        if not _state_search_and_start(by_name):
            continue
        log("[*] State: DERANK")
        run_cycle()
        time.sleep(3)
        # match over -> loop back to INVITE


# ===== derank AFK mode (alternate top-level loop) ==========================
DISCONNECT_FOCUS_DELAY = 0.05  # short focus settle before pressing Z on each window

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


def disconnect_on_live(
    windows,
    is_live,
    focus_func=focus_window,
    is_foreground_func=window_is_foreground,
    press_disconnect=send_disconnect,
    sleep=time.sleep,
    log_func=log,
):
    """Disconnect every CS2 window when GSI reports the match has gone live.

    Takes ``is_live`` from the GSI listener (any tracked client at the trigger
    phase) instead of scanning warmup.png, so the trigger comes from the game's
    real state and is unaffected by window size / display scaling."""
    # Prune closed windows so stale hwnd entries don't suppress log lines.
    active = set(windows)
    for stale in [h for h in list(_last_window_state) if h not in active]:
        del _last_window_state[stale]

    label = "LIVE" if is_live else "NOT-LIVE"
    for hwnd in windows:
        prev = _last_window_state.get(hwnd)
        if prev != label:
            _last_window_state[hwnd] = label
            log_func(f"[*] DERANK AFK: hwnd={hwnd} -> {label}")

    if not is_live:
        return 0

    return _press_disconnect_on_windows(
        windows,
        focus_func=focus_func,
        is_foreground_func=is_foreground_func,
        press_disconnect=press_disconnect,
        sleep=sleep,
        log_func=log_func,
        reason="live (gsi)",
        focus_delay=DISCONNECT_FOCUS_DELAY,
    )


def afk_tick(by_name, gsi):
    """One AFK pass: accept popups, then either reconnect (AUTO_RECONNECT) or
    disconnect every window once GSI reports the match has gone live."""
    if AUTO_RECONNECT:
        auto_clicks(by_name)  # suppress_reconnect=True: don't confirm reconnect dialogs on alt monitors
        accept_reconnect(by_name)
        return 0
    auto_clicks(by_name, suppress_reconnect=False)
    return disconnect_on_live(list_cs2_windows(), gsi.triggered())


def afk_loop():
    by_name = dict(load_templates())
    # AFK Reconnect mode never disconnects on live, so it needs no GSI listener
    # (and shouldn't bind the port). Only the disconnect path starts one.
    gsi = None if AUTO_RECONNECT else start_gsi()
    log("[*] DERANK AFK: auto accept + disconnect mode started")
    log(f"[*] Templates loaded ({len(by_name)}): {', '.join(sorted(by_name)) or 'NONE'}")
    while True:
        afk_tick(by_name, gsi)
        time.sleep(STATE_POLL)
