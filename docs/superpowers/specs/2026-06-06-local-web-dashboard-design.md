# Local Web Dashboard Design

Date: 2026-06-06

## Goal

Build a local web dashboard for CS2 Toolkit that replaces the current "watch a console and edit config.json by hand" workflow with a small control panel.

The first version should let the user:

- Start, stop, and restart the automation process.
- Pick one of the existing runtime modes before starting.
- Edit the most common `config.json` settings safely.
- Watch live automation logs from the same page.
- See whether the dashboard itself is running as Administrator and whether an automation subprocess is active.

The dashboard must preserve the current automation architecture. It should supervise `overlay.py` as a subprocess instead of moving the clicker, template matching, or flow state machine into the web server.

## Recommended Approach

Use a local Python HTTP server built from the standard library.

This avoids adding install steps beyond the dependencies the project already documents. The dashboard can serve a static HTML/CSS/JavaScript page and expose a small JSON API for process control, state, logs, and config updates.

Rejected alternatives:

- Flask/FastAPI: cleaner routing, but adds dependencies and another setup step.
- Windows desktop GUI: avoids a browser, but is more likely to compete with CS2 for focus and gives less flexible UI.
- Runner-only dashboard: fast, but too limited because users would still edit `config.json` manually.
- Full setup manager in v1: useful later, but too broad for the first implementation.

## User Experience

The dashboard opens at a loopback URL, for example `http://127.0.0.1:8765`.

The main page has two regions:

- Left control rail: `Start`, `Stop`, `Restart`, mode selection, and basic health badges.
- Main work area: status cards, config controls, and a live log panel.

Initial controls:

- Mode selector:
  - Auto Derank
  - Derank AFK
  - AFK Reconnect
- Process actions:
  - Start: disabled while a subprocess is already running.
  - Stop: enabled only while a subprocess is running.
  - Restart: enabled only while a subprocess is running.
- Status cards:
  - Dashboard admin status.
  - Automation process status and PID.
  - Selected mode.
  - CS2 window count if available.
  - Warning count.
- Config editor:
  - `AUTO_INVITE`
  - `HOST_MONITOR_INDEX`
  - `GAME_MODE`
  - `ALT_FRIEND_CODES`
  - `MATCH_THRESHOLD`
  - `MATCH_SCALES`
  - `STARTUP_DELAY_SECS`
  - `DEBUG`
- Live logs:
  - Last 300 lines from the current subprocess.
  - A clear indication when no process has been started yet.

The UI should feel like an operational tool, not a landing page: compact, scan-friendly, and clear about current state.

## Architecture

Add a dashboard entry point, `dashboard.py`, plus a package module, `cs2_overlay/dashboard.py`.

The dashboard process owns:

- HTTP server.
- Static asset serving.
- JSON API routing.
- One automation subprocess at a time.
- In-memory log ring buffer.
- Safe config read/write helpers.

The automation subprocess remains `overlay.py`.

The existing `launcher.py` supervisor remains valid for console users. The dashboard does not need to replace it in v1.

## Process Lifecycle

The dashboard starts `overlay.py` with `subprocess.Popen`.

Mode is passed through the same environment variables used by `run.bat` and `config.py`:

- Auto Derank:
  - `CS2_TOOLKIT_DERANK_AFK=0`
  - `CS2_TOOLKIT_AUTO_RECONNECT=0`
- Derank AFK:
  - `CS2_TOOLKIT_DERANK_AFK=1`
  - `CS2_TOOLKIT_AUTO_RECONNECT=0`
- AFK Reconnect:
  - `CS2_TOOLKIT_DERANK_AFK=1`
  - `CS2_TOOLKIT_AUTO_RECONNECT=1`

Only one child process may be active. If `POST /api/start` is called while a process is running, the API returns a conflict response and leaves the existing process alone.

Stopping should mirror the current `launcher._terminate` behavior:

1. Call `terminate()`.
2. Wait briefly.
3. Kill only that child process if it does not exit.

The dashboard should not kill unrelated Python processes.

## API

Use JSON endpoints under `/api`.

`GET /api/state`

Returns dashboard and automation state:

- `admin`: boolean
- `running`: boolean
- `pid`: number or null
- `mode`: selected mode
- `returncode`: number or null
- `warnings`: array of strings
- `cs2WindowCount`: number or null

`POST /api/start`

Starts `overlay.py` in the selected mode. Body:

```json
{ "mode": "auto_derank" }
```

`POST /api/stop`

Stops the active subprocess if one exists.

`POST /api/restart`

Stops the active subprocess, then starts a new one with the requested or current mode.

`GET /api/config`

Returns editable settings and their current values. Defaults may be read from `cs2_overlay.config`, with `config.json` overrides applied by the existing module.

`POST /api/config`

Validates and writes allowed settings to `config.json`.

`GET /api/logs`

Returns recent log lines from the in-memory ring buffer.

## Config Handling

The config editor should be allowlisted. It must not write arbitrary keys.

Allowed values:

- `GAME_MODE`: only `competitive` or `premier`.
- `HOST_MONITOR_INDEX`: integer greater than or equal to 0.
- `MATCH_THRESHOLD`: number between 0 and 1.
- `MATCH_SCALES`: non-empty array of positive numbers.
- `ALT_FRIEND_CODES`: array of strings.
- Boolean settings: strict booleans.
- Numeric timings: non-negative numbers.

When writing `config.json`, preserve valid existing unknown keys only if they were already present, but warn that they are not editable from the dashboard. New unknown keys from the API must be rejected.

Config changes should affect the next automation start. The v1 dashboard does not need hot reload of a running automation subprocess.

## Error Handling

User-facing errors should be plain and actionable:

- Not running as Administrator.
- `overlay.py` missing.
- Subprocess failed to start.
- Config JSON is invalid.
- Config validation failed.
- Port already in use.
- CS2 dependencies unavailable.

The dashboard should continue serving even when the automation subprocess crashes. The process status should show the exit code and logs should retain the recent crash output.

## Security And Scope

The server binds to `127.0.0.1` by default.

No remote access, authentication, or multi-user support is in scope for v1.

The API only exposes local process control for this project and only controls the child process it started.

## Testing

Local automated tests should avoid requiring CS2.

Cover:

- Mode to environment-variable mapping.
- Start conflict when a process is already running.
- Stop behavior terminates only the managed child process.
- Log ring buffer stores stdout/stderr lines.
- Config validation accepts valid inputs and rejects invalid inputs.
- `GET /api/state` reflects admin/process/config status.
- Static dashboard assets are served.

Existing smoke checks remain:

```powershell
python -m unittest discover -s tests
python -m compileall -q launcher.py overlay.py cs2_overlay tests
```

## Out Of Scope For V1

- Template image checker.
- Screenshot previews.
- Multi-process/multi-profile automation.
- Remote access.
- Authentication.
- Replacing `launcher.py`.
- Hot reloading config into an already-running subprocess.
- Packaging as a Windows app.
