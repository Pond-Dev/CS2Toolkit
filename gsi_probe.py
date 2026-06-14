"""GSI probe — standalone prototype to inspect CS2 Game State Integration without
reading the screen.

This does NOT touch the automation. It runs a tiny localhost HTTP server that
CS2 POSTs its game state to, and logs whenever a meaningful phase changes
(warmup -> live, the pre-match countdown, menu <-> in-game). Use it to confirm
which states GSI can distinguish before wiring it into the state machine.

Run with -v / --verbose to also dump the full JSON payload on every change —
handy for discovering what your client actually emits (e.g. the pre-match
"Match starting" countdown in phase_countdowns).

Setup (one time):
  1. Copy gamestate_integration_cs2toolkit.cfg into CS2's config folder:
       ...\\steamapps\\common\\Counter-Strike Global Offensive\\game\\csgo\\cfg\\
  2. Restart CS2 (it only loads GSI configs at startup).
  3. Run:  python -u gsi_probe.py          (add -v for full JSON dumps)
  4. Load into a match and watch the warmup -> pre-match -> live transitions.

Stop with Ctrl+C. No Administrator needed — it only listens on localhost.

Note: in your own matchmaking game GSI cannot count connected players (the
``allplayers`` block is spectator/GOTV only), so "everyone has joined" has to be
inferred from the warmup -> live transition or the phase_countdowns countdown,
not from a player count.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 3000
# Must match the "token" in gamestate_integration_cs2toolkit.cfg. Set to None to
# skip the check and accept any sender (handy when debugging the config).
AUTH_TOKEN = "cs2toolkit"
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def label_state(s):
    """Turn the raw GSI fields into one clear state label for the log.

    The PRE-MATCH rule is the working hypothesis: while map.phase is still
    'warmup' but phase_countdowns has flipped to count down to 'live', everyone
    has joined and the match is about to start. Confirm against a real match —
    if the label is wrong, the raw fields next to it show why."""
    if s["map_phase"] == "warmup":
        if s["pc_phase"] == "live":
            return "PRE-MATCH (players in, match starting)"
        return "WARMUP (waiting for players)"
    if s["map_phase"] == "live":
        return "LIVE (match started)"
    if s["map_phase"] == "intermission":
        return "HALFTIME"
    if s["map_phase"] == "gameover":
        return "GAMEOVER (match ended)"
    if s["activity"] == "menu":
        return "MENU (in menu/lobby)"
    return f"? (activity={s['activity']!r})"


def read_state(payload):
    """Pull the fields that matter for the derank state machine out of a GSI
    payload, tolerating missing blocks — CS2 only sends sections that changed."""
    m = payload.get("map") or {}
    r = payload.get("round") or {}
    p = payload.get("player") or {}
    pc = payload.get("phase_countdowns") or {}
    return {
        "map_phase": m.get("phase"),       # warmup / live / intermission / gameover
        "round_phase": r.get("phase"),     # freezetime / live / over
        "activity": p.get("activity"),     # menu / playing / textinput
        "pc_phase": pc.get("phase"),       # phase the countdown is for
        "pc_ends_in": pc.get("phase_ends_in"),  # seconds left (string)
    }


class _Handler(BaseHTTPRequestHandler):
    last_sig = None  # class-level: only log when an interesting field changes

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        # Answer 200 immediately — CS2 stalls its next update until we reply.
        self.send_response(200)
        self.end_headers()
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            print("[!] bad JSON from CS2")
            return
        if AUTH_TOKEN is not None:
            token = (payload.get("auth") or {}).get("token")
            if token != AUTH_TOKEN:
                print(f"[!] rejected: bad/missing auth token ({token!r})")
                return
        s = read_state(payload)
        # phase_ends_in ticks every post, so exclude it from the change signature
        # (it would log on every single update); show its current value instead.
        sig = (s["map_phase"], s["round_phase"], s["activity"], s["pc_phase"])
        if sig == _Handler.last_sig:
            return
        _Handler.last_sig = sig
        print(
            f"[GSI] >>> {label_state(s)}\n"
            f"      raw: map={s['map_phase']!r} round={s['round_phase']!r} "
            f"activity={s['activity']!r} countdown={s['pc_phase']!r}"
            f"({s['pc_ends_in']}s)"
        )
        if VERBOSE:
            print(json.dumps(payload, indent=2, ensure_ascii=False))

    def log_message(self, *_):  # silence the default per-request stderr logging
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    print(f"[*] GSI probe listening on http://{HOST}:{PORT}"
          f"{'  (verbose)' if VERBOSE else ''}")
    print("[*] Load CS2 into a match and watch the phase changes below.")
    print("[*] Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
