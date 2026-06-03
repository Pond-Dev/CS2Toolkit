"""Coordinated derank state machine.

Replaces the independent clicker/derank/invite loops with ONE ordered flow so
each phase only does its own work and they never overlap. One pass:

    INVITE -> host invites the alts (invite.run_invite); alts accept the popup
              (ACCEPT_INVITE_IMAGE) on their own monitors
    GO     -> host clicks GO_IMAGE to start matchmaking
    SEARCH -> wait for the match; when the ready-check (READY_ACCEPT_IMAGE) shows
              up, accept it on every monitor, until the game actually starts
              (host memory reports in-game)
    DERANK -> derank.run_cycle: disconnect <-> reconnect each instance until the
              match ends (reconnect gone), then loop back to INVITE

If the host is already in a match when started, it goes straight to DERANK. All
clicks are per-monitor (focus the window, then click) so they stay pinned to one
instance at a time.
"""
import time

from .autoclick import auto_clicks, click_image_on
from .config import (
    AUTO_INVITE,
    FOCUS_DELAY,
    GO_IMAGE,
    GO_PRE_IMAGES,
    GO_TIMEOUT,
    INVITE_ACCEPT_SECS,
    LOBBY_LEAVE_IMAGE,
    LOBBY_READY_IMAGE,
    SEARCH_TIMEOUT,
    SEARCH_WARMUP_DELAY,
    STATE_POLL,
)
from .cs2_window import any_cs2_window, focus_window, list_cs2_windows, window_client_rect, window_monitor_rect
from .derank import run_cycle
from .input import any_match_in, load_templates, locate_in_rect, scan_matches, send_disconnect
from .invite import host_window, run_invite
from .log_setup import log


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
    """Navigate play → premier → GO on the host, then start matchmaking."""
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


def _any_warmup(by_name):
    """True when warmup.png is visible on any CS2 window."""
    warmup_tmpl = [(n, img) for n, img in by_name.items() if n.startswith("warmup")]
    if not warmup_tmpl:
        return False
    matches = scan_matches(warmup_tmpl)
    return any(any_match_in(matches, window_monitor_rect(w)) for w in list_cs2_windows())


def _disconnect_all(windows):
    """Press Z on every CS2 window."""
    for hwnd in windows:
        if focus_window(hwnd):
            time.sleep(FOCUS_DELAY)
            send_disconnect()
            log(f"[+] Search: disconnect pressed window {hwnd}")


def _state_search_and_start(by_name):
    """Click accept on all windows; after SEARCH_WARMUP_DELAY check for warmup."""
    log("[*] State: SEARCH")
    start = time.monotonic()
    deadline = start + SEARCH_TIMEOUT
    while time.monotonic() < deadline:
        auto_clicks(by_name)
        if time.monotonic() - start >= SEARCH_WARMUP_DELAY and _any_warmup(by_name):
            log("[+] State: warmup detected — waiting 3s then disconnecting all")
            time.sleep(3)
            _disconnect_all(list_cs2_windows())
            return True
        time.sleep(STATE_POLL)
    log("[WARN] Controller: match never started — restarting from INVITE")
    return False


def controller_loop():
    by_name = dict(load_templates())
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
            if not _state_search_and_start(by_name):
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
            if not _state_search_and_start(by_name):
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
