# CS2 Toolkit

A Windows command-line tool that automates Counter-Strike 2 deranking by driving the
game's UI. It screenshots your monitors, finds buttons by matching the images in `pic/`,
clicks them, and presses the **disconnect key (Z)** — no memory reading, no overlay.

## How it works

It watches the screen for CS2's buttons (`pic/*.png`) and acts on whatever it sees, across
every open CS2 window / monitor:

- Accepts match ready-checks (`accept.png`) and party-invite confirms (`correct.png`).
- In a match: presses **Z** to disconnect, then clicks **RECONNECT** (`reconnect.png`) when
  it appears — looping disconnect ↔ reconnect until the match ends.
- Optionally runs the whole flow for you: invite alts → queue → accept → derank.

The launcher runs in a console window; everything it does is printed there, and **Ctrl+C**
stops it.

---

## Setup (one-time)

### 1. Install Python 3.10+

### 2. Install dependencies

```powershell
py -3 -m pip install pywin32 opencv-python Pillow
```

### 3. Bind Z to disconnect in CS2  ⚠️ required

1. Enable the console: **Settings → Game → Enable Developer Console → Yes**
2. Press `` ~ `` to open the console and run:

   ```
   bind z disconnect
   ```

### 4. Check the button images in `pic/`

Each `pic/*.png` must match the button as it looks on *your* screen (matching is grayscale).
At minimum `reconnect.png` must match. If your resolution or UI differs, crop a fresh
screenshot of the button and replace the image.

---

## Running

Double-click **`run.bat`** — it elevates to Administrator (required for synthetic input),
asks which mode to run, and starts the launcher. You can also run `python launcher.py` from
an already-elevated terminal.

| Mode | What it does |
|---|---|
| **1. Auto Derank** | Full loop: invite the alts in `config.json` → queue → accept → derank → repeat |
| **2. Derank AFK** | Accept popups, and disconnect whenever warmup is detected |
| **3. AFK Reconnect** | Accept popups, and click reconnect on the host |

> CS2 must be the focused (foreground) window — the tool won't send input while you're
> alt-tabbed to another app.

### Dashboard

To use the local browser dashboard instead of the console-only launcher, run from an
elevated terminal:

```powershell
python dashboard.py
```

The dashboard opens on `http://127.0.0.1:8765` by default. It can start, stop, and
restart the automation subprocess, choose the runtime mode, edit common `config.json`
settings, and show recent logs.

Use `--no-browser` if you only want to start the server:

```powershell
python dashboard.py --no-browser
```

---

## Configuration

Settings live in `config.json` at the project root (optional — defaults apply if absent).
Common keys: `AUTO_INVITE`, `ALT_FRIEND_CODES`, `HOST_MONITOR_INDEX`, `GAME_MODE`
(`competitive`/`premier`), and the various timeouts. See `config.example.json`.

---

## Local checks

These do not require CS2 to be running:

```powershell
python -m unittest discover -s tests
python -m compileall -q launcher.py overlay.py dashboard.py cs2_overlay tests
```

---

## File reference

| File | Description |
|---|---|
| `run.bat` | Launcher — auto-elevates, asks for a mode, starts `launcher.py` |
| `launcher.py` | CLI supervisor — runs and restarts the automation process |
| `dashboard.py` | Local browser dashboard for process control, config editing, and logs |
| `overlay.py` | Automation entry point (historical name; draws no overlay) |
| `cs2_overlay/` | The package: `config`, `core`, `flows`, `runtime` |
| `pic/*.png` | Button images the clicker looks for |
| `config.json` | Your settings (overrides the defaults in `cs2_overlay/config.py`) |

---

## Notes & troubleshooting

- **Windows only**, and must run as **Administrator** (synthetic keyboard/mouse input).
- **Nothing happens?** Make sure CS2 is the focused window and the relevant `pic/*.png`
  actually matches your screen.
- **Z does nothing?** Make sure `bind z disconnect` is set in CS2.
- **Clicks miss the button?** The clicker auto-corrects for Windows display scaling; if it
  still misses, re-crop the image from a current screenshot.
- No log files are written — everything prints to the console.
