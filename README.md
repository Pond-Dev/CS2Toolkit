# CS2 Toolkit

A command-line tool for Counter-Strike 2 that reads game memory, shows a transparent
status overlay, and runs an automatic **disconnect ↔ reconnect** loop for deranking.

## How it works

1. Reads CS2 process memory to detect the current state — `LOBBY`, `WARMUP`, or `IN GAME`
2. When you reach `IN GAME`, it presses the **disconnect key (Z)**
3. A background scanner watches the screen for `pic/reconnect.png`; when the reconnect
   prompt appears, it clicks it — putting you back in the match
4. Back in game → disconnect again → reconnect again → **loops until the match ends**

The current state is shown as a transparent label on top of the game. The launcher runs
in a console window: status changes, disconnects, and clicks are printed there, and
**Ctrl+C** stops everything.

---

## Setup (one-time)

### 1. Install Python 3.10+

### 2. Install dependencies

```powershell
py -3 -m pip install pywin32 opencv-python Pillow Pymem
```

### 3. Bind Z to disconnect in CS2  ⚠️ required

The tool sends the **Z** key to disconnect, so Z must be bound to the `disconnect` command:

1. Enable the console: **Settings → Game → Enable Developer Console → Yes**
2. Press `` ~ `` to open the console and run:

   ```
   bind z disconnect
   ```

### 4. Check the reconnect button image

`pic/reconnect.png` must match the **RECONNECT** button as it looks on *your* screen.
If your resolution or UI differs, crop a fresh screenshot of the button and replace it.

> Only `pic/reconnect.png` is active. Optional buttons (`accept`, `go`, `ok`) are parked
> in `pic_disabled/`. Move them into `pic/` if you also want the tool to auto-queue and
> auto-accept new matches (full cross-match automation).

---

## Running

Double-click **`Run Latest CS2 Toolkit.bat`** — it elevates to Administrator (required to
read game memory) and opens a console. You can also run `python launcher.py` from an
already-elevated terminal.

Then just play: queue and accept a match yourself, and once you're in, the loop takes over.

```
CS2 Toolkit v1.4
Overlay starting. Press Ctrl+C to stop.
[+] Attached to CS2
[*] Watching for buttons: reconnect.PNG
[*] IN GAME
[*] In game — sending disconnect
[*] LOBBY
[+] Clicked reconnect.PNG
[*] IN GAME
...
```

| Step | What happens |
|---|---|
| You enter a match | overlay shows `WARMUP` → `IN GAME` |
| `IN GAME` | the tool presses **Z** (disconnect) |
| Reconnect prompt appears | the tool clicks **RECONNECT** → back in game |
| Repeats | disconnect ↔ reconnect until the match ends |
| Match ends → menu | no reconnect button → the loop stops on its own |
| To quit | press **Ctrl+C** in the console |

> CS2 must be the focused (foreground) window — the tool won't send input while you're
> alt-tabbed to another app.

---

## Updating offsets after a CS2 update

If the status reads wrong after CS2 patches, the memory offsets may be stale.
Update `DEFAULT_OFFSETS` in `cs2_overlay/config.py` with the new values (or override
them in `data/offsets.json`).

---

## Local checks

These do not require CS2 to be running:

```powershell
python -m unittest discover -s tests
python -m compileall -q launcher.py scripts tests
```

---

## File reference

| File | Description |
|---|---|
| `install.bat` | First-time setup — installs Python dependencies |
| `Run Latest CS2 Toolkit.bat` | Recommended launcher (auto-elevates, opens console) |
| `launcher.py` | CLI supervisor — runs and restarts the overlay |
| `scripts/overlay.py` | Status overlay + disconnect/clicker threads |
| `pic/reconnect.png` | Reconnect button image the clicker looks for |
| `pic_disabled/` | Parked button images (accept / go / ok) — not scanned |
| `data/offsets.json` | Fallback offsets (auto-created from defaults if missing) |

---

## Notes & troubleshooting

- **Windows only**, and must run as **Administrator** (memory access + synthetic input).
- **Nothing happens at the menu** — the loop only acts once you're actually in a match.
- **Z does nothing?** Make sure `bind z disconnect` is set in CS2.
- **Clicks miss the button?** The clicker auto-corrects for Windows display scaling; if it
  still misses, re-crop `pic/reconnect.png` from a current screenshot.
- No log files are written — everything prints to the console.
