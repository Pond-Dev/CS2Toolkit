"""CS2 Game State Integration (GSI) listener — optional, off by default.

Runs a tiny localhost HTTP server on a daemon thread that CS2 POSTs its game
state to, and exposes the latest map phase so the automation can trigger on the
real game state instead of matching warmup.png on screen.

Read-only by design: the listener thread only stores the latest state; it never
clicks or sends input, so it does not violate the single-clicker rule (see
CLAUDE.md "State and threading"). The main automation thread reads triggered()/
snapshot() and performs all input itself.

Limitations (confirmed against a real match):
- ``phase_countdowns`` is empty for your own matchmaking client, so the
  "everyone joined / pre-match" moment cannot be distinguished from early
  warmup. The reliable boundary is ``map.phase == "live"`` (match committed).
- With several CS2 instances every client POSTs to the same endpoint; they can
  only be told apart by ``provider.steamid`` (exposed in snapshot()).
  Single-instance Derank AFK needs no such mapping.

See gsi_probe.py for a standalone probe that prints the live phase stream.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def read_state(payload):
    """Pull the fields the automation cares about out of a GSI payload,
    tolerating missing blocks — CS2 only sends sections that changed."""
    m = payload.get("map") or {}
    r = payload.get("round") or {}
    p = payload.get("player") or {}
    prov = payload.get("provider") or {}
    return {
        "map_phase": m.get("phase"),      # warmup / live / intermission / gameover
        "round_phase": r.get("phase"),    # freezetime / live / over
        "activity": p.get("activity"),    # menu / playing / textinput
        "steamid": prov.get("steamid"),   # which client sent this (multi-instance)
    }


class GsiListener:
    """Owns the HTTP server thread and the latest parsed game state.

    Use ``start()`` once, then poll ``triggered()`` / ``snapshot()`` from the
    automation thread. Thread-safe: state is read/written under a lock."""

    def __init__(self, host="127.0.0.1", port=3000, token=None,
                 trigger_phase="live", log_func=None):
        self._host = host
        self._port = port
        self._token = token
        self._trigger_phase = trigger_phase
        self._log = log_func
        self._lock = threading.Lock()
        # steamid -> latest state. We track each CS2 client separately rather
        # than keeping one "latest" so interleaved POSTs from several instances
        # don't make the state flap (an alt still posting 'warmup' must not undo
        # the host's 'live'). The "primary" reader is therefore dynamic — whoever
        # reaches the trigger phase first fires it.
        self._states = {}
        self._server = None
        self._thread = None

    def update_from_payload(self, payload):
        """Validate the token and store the parsed state, keyed by steamid. Public
        so it can be unit-tested without standing up a socket."""
        if self._token is not None:
            token = (payload.get("auth") or {}).get("token")
            if token != self._token:
                return False
        s = read_state(payload)
        # Clients without a provider block (steamid None) share one bucket.
        key = s.get("steamid") or "_default"
        with self._lock:
            self._states[key] = s
        return True

    def snapshot(self):
        """A copy of every tracked client's latest state, keyed by steamid
        (empty before the first POST)."""
        with self._lock:
            return {k: dict(v) for k, v in self._states.items()}

    def triggered(self):
        """True once ANY tracked client has reached the configured trigger phase
        (default ``map.phase == "live"`` — the match has committed). Since the
        derank party is all in one match, one client reaching live means the
        match is live, so we disconnect every window."""
        with self._lock:
            return any(
                st.get("map_phase") == self._trigger_phase
                for st in self._states.values()
            )

    def start(self):
        """Bind the server and serve on a daemon thread. Returns self."""
        listener = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                # Answer 200 immediately — CS2 stalls its next update until we reply.
                self.send_response(200)
                self.end_headers()
                try:
                    payload = json.loads(raw or b"{}")
                except ValueError:
                    return
                listener.update_from_payload(payload)

            def log_message(self, *_):  # silence default per-request stderr spam
                pass

        self._server = ThreadingHTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="gsi-listener"
        )
        self._thread.start()
        if self._log:
            self._log(
                f"[*] GSI listener on http://{self._host}:{self._port} "
                f"(disconnect when map.phase='{self._trigger_phase}')"
            )
        return self

    def stop(self):
        """Shut the server down (mainly for tests; the loop runs until exit)."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
