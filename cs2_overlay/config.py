"""Tunables and Win32 constants.

The values below are *defaults*. To change settings without touching code, edit
``config.json`` at the project root — any key matching a name here overrides it
(see ``_apply_json_overrides`` at the bottom). Missing/invalid file → defaults.
"""
import json
import os

VERSION = "1.4"

# ================= CONFIGURATION =================
DEBUG = False
STARTUP_DELAY_SECS = 5.0
DERANK_AFK_MODE = False
AUTO_RECONNECT = False   # AFK reconnect mode: click reconnect.png automatically
DISCONNECT_KEY_VK = 0x5A      # Z
WIN = "Counter-Strike 2"

# Image scanner: scan pic/ this often; pause after each click so the same
# button isn't spam-clicked while the UI transitions.
SCAN_INTERVAL = 0.5
CLICK_COOLDOWN = 2.0
MATCH_THRESHOLD = 0.8
# Template matching is NOT scale-invariant: a button only matches when the .png
# is the same pixel size as it appears on screen. With CS2 in small windowed mode
# (e.g. 800x600), buttons are physically smaller than templates cropped from a
# bigger/fullscreen window, so they never match at 1.0x. We therefore try each of
# these scales (resizing the template) and keep the best-scoring one. Covers
# roughly fullscreen (1.0) down to a small window (~0.3). The scale that hits is
# cached per image so steady-state cost stays ~one match per template. Set to
# (1.0,) to disable multi-scale (faster, original behavior).
MATCH_SCALES = (1.0,)

# While a "blocker" button is on screen, suppress clicking the blocked button
# even if it also matches. Maps blocked image -> blocker image. Example: do not
# click correct.png as long as reconnect.png is still visible.
CLICK_SUPPRESSED_BY = {
    "correct.png": "reconnect.png",
}

# ---- Multi-instance derank cycle (derank.py) ----
# Images the derank cycle drives. Only reconnect.png — correct.png is handled by
# the controller's INVITE phase (it's the generic CS2 confirm: reconnect dialog
# AND party-invite popup), not by the derank cycle.
DERANK_IMAGES = ("reconnect.png",)
# After focusing a window, wait this long before sending the disconnect key so
# the window is actually frontmost when Z lands.
FOCUS_DELAY = 0.2
# Keep pressing the disconnect key until it succeeds; give up after this long.
DISCONNECT_TIMEOUT = 15.0
# Wait between disconnect-key press attempts.
DISCONNECT_RETRY = 0.5
# Seconds to wait after clicking reconnect before pressing Z.
RECONNECT_WAIT_SECS = 8.0

# ---- Host party-invite macro (invite.py, driven by controller.py) ----
# Which CS2 window is the host (party owner that sends invites), as an index into
# the on-screen order from list_cs2_windows(): top row first, left-to-right. 0 =
# upper-left.
HOST_MONITOR_INDEX = 0
# Friend codes of the alts to invite. The host types each into the "Find a user
# by their friend code" dialog and invites them one by one. One string per alt,
# exactly as shown in CS2 (uppercase, with the dash). Empty -> macro disabled.
# Paste your real codes below (the first is the one from the screenshot):
ALT_FRIEND_CODES = (
    "SC7EX-2EMN",
    # "AAAAA-1111",
    # "BBBBB-2222",
    # "CCCCC-3333",
    # "DDDDD-4444",
)
# Buttons clicked in order to open the friend-code dialog (People -> People-Add).
INVITE_OPEN_IMAGES = ("people.png", "people_add.png")
# The friend-code text box: clicked to focus, and used as the anchor for the
# search-result row. The row can't be template-matched (a different avatar per
# alt), so we click a fixed offset below this box instead.
INVITE_CODE_FIELD_IMAGE = "code_field.png"
# Fallback click position for the friend-code text box when template matching
# misses because the CS2 UI is scaled differently. Values are relative to the
# host client rect: (0.49, 0.50) lands on the textbox in the dialog shown after
# People -> People-Add on the current CS2 lobby UI.
INVITE_CODE_FIELD_FALLBACK_POS = (0.49, 0.50)
# Result row click position relative to the host client rect. Tuned for 800x600:
# x=0.40 lands in the avatar/name area; y=0.505 lands in the user result row,
# well above the bottom "Send friend request" button.
INVITE_RESULT_ROW_POS = (0.40, 0.505)
# Legacy offset from the code box center to the clickable user result row. Kept
# as a fallback if INVITE_RESULT_ROW_POS is disabled by setting it to null/None.
INVITE_RESULT_DX = -55
INVITE_RESULT_DY = 40
# Clicking the result row opens the user's card; this is its Invite button.
INVITE_BUTTON_IMAGE = "invite.png"
# After inviting one code, close the dialog/card so the next loop can reopen
# People -> People-Add cleanly.
INVITE_CANCEL_IMAGE = "cancel.png"
# Pause after each click / keystroke group while the UI catches up.
INVITE_STEP_WAIT = 0.8

# ---- Coordinated derank state machine (controller.py) ----
# The whole run is ONE ordered state machine (not independent loops), so phases
# never overlap:
#   INVITE -> host invites alts; alts accept the popup (ACCEPT_INVITE_IMAGE)
#   GO     -> host clicks GO_IMAGE to start matchmaking
#   SEARCH -> accept the ready-check (READY_ACCEPT_IMAGE) on every monitor, then
#             wait until warmup.png is detected (the game has started)
#   DERANK -> disconnect<->reconnect each instance until the match ends, then loop
#
# Master on/off for the auto-invite flow:
#   True  -> full loop: INVITE -> GO -> SEARCH -> DERANK -> (repeat)
#   False -> DERANK only: wait until a game is on, derank it, repeat. You set up
#            the lobby / queue yourself; the bot never invites, clicks GO, or
#            accepts the ready-check.
AUTO_INVITE = True
GO_IMAGE = "start_search.png"        # host clicks this to start matchmaking
# Game mode to queue: "competitive" or "premier".
# Controls which navigation images are clicked before GO_IMAGE.
GAME_MODE = "competitive"
_GAME_MODE_PRE_IMAGES = {
    "competitive": ("play.png", "competitive.png"),
    "premier": ("play.png", "premier.png"),
}
GO_PRE_IMAGES = _GAME_MODE_PRE_IMAGES["competitive"]
ACCEPT_INVITE_IMAGE = "correct.png"  # alts accept the party-invite popup
READY_ACCEPT_IMAGE = "accept.png"    # accept the match ready-check (all monitors)
# How often the state machine polls while waiting in a state.
STATE_POLL = 0.5
# Image that signals all alts are ready in the lobby (e.g. the green checkmark
# or "Ready" indicator visible on the host). When found, INVITE proceeds to GO
# immediately instead of waiting out INVITE_ACCEPT_SECS. Set to "" to disable.
LOBBY_READY_IMAGE = "people_ready.png"
# Clicked on the host to leave the lobby when INVITE times out without ready.
LOBBY_LEAVE_IMAGE = "leave.png"
# Max seconds INVITE waits before leaving lobby and restarting.
INVITE_ACCEPT_SECS = 45.0
# Give up clicking GO (and restart from INVITE) after this long without success.
GO_TIMEOUT = 30.0
# Give up waiting for the match to be found / start, and restart, after this long.
SEARCH_TIMEOUT = 300.0
# Seconds of auto-accept before warmup detection activates.
SEARCH_WARMUP_DELAY = 120.0
# =================================================


# ---- config.json overrides (project root) ----
# config.py is cs2_overlay/config.py; the root is one level up.
CONFIG_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.json",
)


def _coerce_override(key, default, value):
    """Validate (and lightly coerce) a config.json value against the default's
    type, so a mistyped setting fails loudly here instead of deep inside cv2/win32
    later. Returns (ok, coerced_value). ``None`` always passes — several settings
    document null to disable them (e.g. INVITE_RESULT_ROW_POS)."""
    if value is None:
        return True, None
    # bool must come before int/float: bool is a subclass of int.
    if isinstance(default, bool):
        if not isinstance(value, bool):
            print(f"[WARN] config.json: {key} must be true/false — ignored")
            return False, None
    elif isinstance(default, tuple):
        if not isinstance(value, list):
            print(f"[WARN] config.json: {key} must be a list — ignored")
            return False, None
        value = tuple(value)  # JSON has only lists; keep tuple-typed settings tuples
    elif isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            print(f"[WARN] config.json: {key} must be a number — ignored")
            return False, None
    elif isinstance(default, str):
        if not isinstance(value, str):
            print(f"[WARN] config.json: {key} must be a string — ignored")
            return False, None
    return True, value


def _apply_json_overrides():
    """Override any constant above with a matching key in config.json (optional).
    JSON lists replace tuple-typed settings; unknown or mistyped keys are warned
    and ignored. A missing or invalid file leaves the defaults untouched.
    Returns the list of keys actually applied."""
    if not os.path.isfile(CONFIG_JSON):
        return []
    try:
        with open(CONFIG_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[WARN] config.json ignored (invalid): {e}")
        return []
    g = globals()
    applied = []
    for key, value in data.items():
        if key not in g:
            print(f"[WARN] config.json: unknown setting {key!r} ignored")
            continue
        ok, coerced = _coerce_override(key, g[key], value)
        if not ok:
            continue
        g[key] = coerced
        applied.append(key)
    return applied


def _env_bool(name):
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


def _apply_env_overrides():
    """Small launcher-facing overrides that should not require editing JSON."""
    afk = _env_bool("CS2_TOOLKIT_DERANK_AFK")
    if afk is not None:
        globals()["DERANK_AFK_MODE"] = afk
    reconnect = _env_bool("CS2_TOOLKIT_AUTO_RECONNECT")
    if reconnect is not None:
        globals()["AUTO_RECONNECT"] = reconnect


_json_overridden = _apply_json_overrides()
_apply_env_overrides()

# Recompute GO_PRE_IMAGES from GAME_MODE after overrides — but only when
# config.json didn't set GO_PRE_IMAGES directly, so an explicit override wins.
if "GO_PRE_IMAGES" not in _json_overridden and GAME_MODE in _GAME_MODE_PRE_IMAGES:
    GO_PRE_IMAGES = _GAME_MODE_PRE_IMAGES[GAME_MODE]
