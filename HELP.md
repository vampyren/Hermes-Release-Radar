# Hermes Release Radar Help

Short operational help for installing and running Hermes Release Radar as a local user service.

## What it does

Hermes Release Radar shows what changed upstream in Hermes Agent without updating Hermes.

It is intentionally safe:
- It reads `~/.hermes/hermes-agent` by default.
- It may run `git fetch origin --quiet` when you press refresh.
- It regenerates local HTML output in `~/.hermes/release-radar/` by default.
- It saves review markers in `~/.hermes/release-radar/state.json`.
- It does not run `hermes update`.
- It does not install packages.
- It does not reset, stash, or modify the Hermes checkout.

Local page:

```text
http://127.0.0.1:8765/
```

## Requirements

- Linux with user systemd.
- Python 3 at `/usr/bin/python3`.
- Git available.
- Existing Hermes Agent checkout at `~/.hermes/hermes-agent`, or set `RELEASE_RADAR_HERMES_REPO` to the checkout path.
- Do not expose port `8765` outside localhost without authentication.

## Configuration

The defaults work for a normal Hermes install:

```text
RELEASE_RADAR_HERMES_REPO=~/.hermes/hermes-agent
RELEASE_RADAR_ROOT=~/.hermes/release-radar
RELEASE_RADAR_HOST=127.0.0.1
RELEASE_RADAR_PORT=8765
```

Set these environment variables only if your Hermes checkout, runtime folder, host, or port differs.

If the Hermes checkout is missing on first run, Release Radar still generates a page. The page shows a setup-needed message with the checked path and the `RELEASE_RADAR_HERMES_REPO` override instead of failing with a traceback. It still does not run `hermes update`.

## Short installation

Clone the project:

```bash
git clone https://github.com/vampyren/Hermes-Release-Radar.git ~/Apps/Hermes-Release-Radar
```

Create the runtime folder:

```bash
mkdir -p ~/.hermes/release-radar/runs ~/.config/systemd/user
```

Copy the runtime files:

```bash
cp ~/Apps/Hermes-Release-Radar/src/generate.py \
  ~/.hermes/release-radar/generate.py
cp ~/Apps/Hermes-Release-Radar/src/serve.py \
  ~/.hermes/release-radar/serve.py
cp ~/Apps/Hermes-Release-Radar/src/state.py \
  ~/.hermes/release-radar/state.py
cp ~/Apps/Hermes-Release-Radar/VERSION \
  ~/.hermes/release-radar/VERSION
cp ~/Apps/Hermes-Release-Radar/HELP.md \
  ~/.hermes/release-radar/HELP.md
cp ~/Apps/Hermes-Release-Radar/docs/help.html \
  ~/.hermes/release-radar/help.html
```

Generate the first page:

```bash
python3 ~/.hermes/release-radar/generate.py
```

Install the user service:

```bash
cp ~/Apps/Hermes-Release-Radar/systemd/hermes-release-radar.service \
  ~/.config/systemd/user/hermes-release-radar.service
systemctl --user daemon-reload
systemctl --user enable --now hermes-release-radar.service
```

Open:

```text
http://127.0.0.1:8765/
```

## Service file

The installed service should be:

```ini
[Unit]
Description=Hermes Release Radar local helper
Documentation=file:%h/.hermes/release-radar/index.html
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/.hermes/release-radar
ExecStart=/usr/bin/python3 %h/.hermes/release-radar/serve.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
# Optional overrides:
# Environment=RELEASE_RADAR_HERMES_REPO=%h/.hermes/hermes-agent
# Environment=RELEASE_RADAR_ROOT=%h/.hermes/release-radar
# Environment=RELEASE_RADAR_HOST=127.0.0.1
# Environment=RELEASE_RADAR_PORT=8765

[Install]
WantedBy=default.target
```

## Useful commands

Check service status:

```bash
systemctl --user status hermes-release-radar.service --no-pager --lines=30
```

Start the service:

```bash
systemctl --user start hermes-release-radar.service
```

Stop the service:

```bash
systemctl --user stop hermes-release-radar.service
```

Restart the service after changing `serve.py` or the service file:

```bash
systemctl --user restart hermes-release-radar.service
```

Reload systemd after changing the service file:

```bash
systemctl --user daemon-reload
systemctl --user restart hermes-release-radar.service
```

View recent logs:

```bash
journalctl --user -u hermes-release-radar.service -n 80 --no-pager
```

Check the helper API:

```bash
curl -s http://127.0.0.1:8765/api/status
```

Run the safe smoke test from the repo checkout:

```bash
cd ~/Apps/Hermes-Release-Radar
python3 scripts/smoke_test.py
```

The smoke test checks repo files, Python syntax, a temporary-root generator run, the missing-checkout first-run page, installed runtime files, `state.json`, and the local helper API when it is running. It does not run `hermes update`, fetch upstream, restart services, install packages, or mutate the Hermes checkout.

Refresh upstream data and regenerate the page:

```bash
curl -s -X POST http://127.0.0.1:8765/api/refresh
```

Regenerate the page without fetching upstream:

```bash
python3 ~/.hermes/release-radar/generate.py
```

## What "reload" means

There are two different reload-style actions:
- Service file changed: run `systemctl --user daemon-reload`, then restart the service.
- Radar data changed: run the browser refresh button or `curl -s -X POST http://127.0.0.1:8765/api/refresh`.

The service does not currently implement `systemctl --user reload hermes-release-radar.service`; use restart instead.

## File locations

```text
~/.hermes/release-radar/generate.py      Generator
~/.hermes/release-radar/serve.py         Local helper server
~/.hermes/release-radar/state.py         Shared state helpers
~/.hermes/release-radar/VERSION          Release Radar app version (top-bar badge)
~/.hermes/release-radar/state.json       Review markers and checkpoints
~/.hermes/release-radar/index.html       Current radar page
~/.hermes/release-radar/history.html     Installed-update history
~/.hermes/release-radar/runs/            Raw run snapshots
~/.config/systemd/user/hermes-release-radar.service
```

## Safety checklist

Before publishing or changing the service, verify:
- `python3 scripts/smoke_test.py` passes from the repo checkout.
- `python3 -m py_compile src/generate.py src/serve.py src/state.py scripts/render_help.py scripts/smoke_test.py` passes.
- `python3 ~/.hermes/release-radar/generate.py` regenerates `index.html`.
- `systemctl --user status hermes-release-radar.service` is healthy.
- `curl -s http://127.0.0.1:8765/api/status` returns `"ok": true`.
- The helper still binds only to `127.0.0.1`.
- No command in this project runs `hermes update`.
