# CS2 Toolkit

Launcher + overlay for launching the HS Tracker and Status Overlay from `scripts/overlay.py`

## Project Status

This iteration has been restructured to be closer to a production-ready product, but it should still be considered a beta/internal build before commercial release.

The program reads game memory and sends keyboard/mouse input, which carries potential risks related to platform policies and customer support.

---

## Installation

1. Install Python 3.10 or later
2. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

3. Run with Administrator privileges:

```powershell
.\launcher.bat
```

---

## Build as EXE

Run this command from the project folder:

```powershell
.\build_exe.bat
```

The output will be located at:

```text
dist\CS2Toolkit\launcher.exe
```

You must keep the following items in the same folder:

- `launcher.exe`
- `overlay.exe`
- `_internal`
- `data`
- `tools`

If running from the `dist\CS2Toolkit` folder, launch:

```text
Run CS2 Toolkit.bat
```

This file will elevate privileges to Administrator and then launch `launcher.exe`.

---

## Config

When `launcher.py` is started for the first time, the program will create `data/config.json` using default values.

If Steam/CS2 is not installed in the default path, specify the path manually:

```json
{
  "auto_dump": true,
  "cs2_exe": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Counter-Strike Global Offensive\\game\\bin\\win64\\cs2.exe",
  "dump_check_interval_seconds": 3600,
  "dump_timeout_seconds": 120
}
```

---

## Important Files

| File                            | Description                                                    |
| ------------------------------- | -------------------------------------------------------------- |
| `launcher.py`                   | Main UI, process manager, and auto dump watcher                |
| `launcher.bat`                  | Launches the launcher in portable mode from the current folder |
| `scripts/overlay.py`            | The actual runtime overlay                                     |
| `scripts/archive/`              | Old prototypes kept for reference                              |
| `data/offsets.json`             | Offsets currently used by the overlay                          |
| `data/logs/launcher.log`        | Launcher logs                                                  |
| `data/logs/overlay.log`         | Overlay stdout/stderr logs                                     |
| `data/logs/overlay-runtime.log` | Logs written directly by the overlay during runtime            |

---

## Notes

- Administrator privileges are required for memory access and input handling.
- Windows Defender or antivirus software may flag the executable due to memory reading/input behavior.
- This project is intended for internal/testing purposes until stability and support workflows are finalized.
