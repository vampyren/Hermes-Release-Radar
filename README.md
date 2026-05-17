# Hermes Release Radar

Hermes Release Radar is a local, safe update-intelligence page for Hermes Agent.

It answers: what changed upstream since the Hermes checkout I am running now, and what actually matters?

## Current local URL

```text
http://127.0.0.1:8765/
```

## What it does

- Inspects the local Hermes Agent checkout at `~/.hermes/hermes-agent`.
- Compares local `HEAD` with `origin/main`.
- Generates a calm browser page with:
  - Official release notes, only when a newer release tag is actually ahead.
  - `What actually matters` cards for human review.
  - Raw categorized commits for auditability.
  - Durable review markers stored in `state.json`.
  - Installed-update history once Hermes actually advances.
- Runs as a local-only helper service on `127.0.0.1:8765`.

## Safety contract

Release Radar does not update Hermes.

It may run:

```bash
git fetch origin --quiet
python3 ~/.hermes/release-radar/generate.py
```

It must not run:

```bash
hermes update
git reset
git stash
git restore
```

It must not install packages, restart Hermes services, or bind outside localhost without a separate explicit approval process.

## Quick install

See the full help page:

- `HELP.md`
- `docs/help.html`

Short version:

```bash
git clone https://github.com/vampyren/Hermes-Release-Radar.git ~/Apps/Hermes-Release-Radar
mkdir -p ~/.hermes/release-radar/runs ~/.config/systemd/user
cp ~/Apps/Hermes-Release-Radar/src/generate.py ~/.hermes/release-radar/generate.py
cp ~/Apps/Hermes-Release-Radar/src/serve.py ~/.hermes/release-radar/serve.py
cp ~/Apps/Hermes-Release-Radar/HELP.md ~/.hermes/release-radar/HELP.md
cp ~/Apps/Hermes-Release-Radar/docs/help.html ~/.hermes/release-radar/help.html
python3 ~/.hermes/release-radar/generate.py
cp ~/Apps/Hermes-Release-Radar/systemd/hermes-release-radar.service ~/.config/systemd/user/hermes-release-radar.service
systemctl --user daemon-reload
systemctl --user enable --now hermes-release-radar.service
```

Open:

```text
http://127.0.0.1:8765/
```

## Useful commands

```bash
systemctl --user status hermes-release-radar.service --no-pager --lines=30
systemctl --user restart hermes-release-radar.service
journalctl --user -u hermes-release-radar.service -n 80 --no-pager
curl -s http://127.0.0.1:8765/api/status
curl -s -X POST http://127.0.0.1:8765/api/refresh
```

## Repository layout

```text
src/generate.py                         Static page generator
src/serve.py                            Local-only helper server
systemd/hermes-release-radar.service    User systemd service
docs/help.html                          Rendered help page
scripts/render_help.py                  Markdown-to-help HTML renderer
HELP.md                                 Operator help
README.md                               Project overview
PURPOSE.md                              Project purpose and principles
```

## Verification

```bash
python3 -m py_compile src/generate.py src/serve.py
python3 ~/.hermes/release-radar/generate.py
curl -s http://127.0.0.1:8765/api/status
```
