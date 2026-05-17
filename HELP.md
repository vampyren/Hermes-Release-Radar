# Hermes Release Radar Help

Short operational help for installing and running Hermes Release Radar as a local user service.

## What it does

Hermes Release Radar shows what changed upstream in Hermes Agent without updating Hermes.

It is intentionally safe:
- It reads `/home/spawn/.hermes/hermes-agent`.
- It may run `git fetch origin --quiet` when you press refresh.
- It regenerates local HTML output in `/home/spawn/.hermes/release-radar/`.
- It saves review markers in `/home/spawn/.hermes/release-radar/state.json`.
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
- Existing Hermes Agent checkout at `/home/spawn/.hermes/hermes-agent`.
- Do not expose port `8765` outside localhost without authentication.

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
Documentation=file:/home/spawn/.hermes/release-radar/index.html
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/spawn/.hermes/release-radar
ExecStart=/usr/bin/python3 /home/spawn/.hermes/release-radar/serve.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

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
~/.hermes/release-radar/state.json       Review markers and checkpoints
~/.hermes/release-radar/index.html       Current radar page
~/.hermes/release-radar/history.html     Installed-update history
~/.hermes/release-radar/runs/            Raw run snapshots
~/.config/systemd/user/hermes-release-radar.service
```

## Safety checklist

Before publishing or changing the service, verify:
- `python3 -m py_compile ~/.hermes/release-radar/generate.py ~/.hermes/release-radar/serve.py` passes.
- `python3 ~/.hermes/release-radar/generate.py` regenerates `index.html`.
- `systemctl --user status hermes-release-radar.service` is healthy.
- `curl -s http://127.0.0.1:8765/api/status` returns `"ok": true`.
- The helper still binds only to `127.0.0.1`.
- No command in this project runs `hermes update`.
