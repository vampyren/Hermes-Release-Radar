# Hermes Release Radar

Hermes Release Radar is a local, safe update-intelligence page for Hermes Agent.

It answers: what changed upstream since the Hermes checkout I am running now, and what actually matters?

Published project version: `0.4.0-local`.

## Local URL

```text
http://127.0.0.1:8765/
```

## Product direction

Release Radar is a local product, not a hosted demo.

A user downloads this repo, runs the helper locally, and Release Radar checks that user's own Hermes checkout. First run initializes that user's own `state.json` from their own checkout, then future refreshes preserve their review markers and installed-update history.

If the Hermes checkout is missing on first run, the generated page now opens in a setup-needed state instead of crashing. It explains which path was checked, how to set `RELEASE_RADAR_HERMES_REPO`, and confirms that Release Radar still does not run `hermes update`.

GitHub presentation is handled by README/docs/screenshots. The previous separate public demo generator and GitHub Pages rebuild path were intentionally removed to keep one generator and avoid drift.

## What it does

- Inspects the local Hermes Agent checkout at `~/.hermes/hermes-agent` by default.
- Compares local `HEAD` with `origin/main`.
- Generates a calm browser page with:
  - Official release notes, only when a newer release tag is actually ahead.
  - `What actually matters` cards for human review.
  - Raw categorized commits for auditability.
  - Durable review markers stored in `state.json`.
  - Installed-update history once Hermes actually advances.
- Runs as a local-only helper service on `127.0.0.1:8765` by default.

## Configuration

The defaults work for a normal Hermes install:

```text
RELEASE_RADAR_HERMES_REPO=~/.hermes/hermes-agent
RELEASE_RADAR_ROOT=~/.hermes/release-radar
RELEASE_RADAR_HOST=127.0.0.1
RELEASE_RADAR_PORT=8765
```

Set these environment variables only if your Hermes checkout, runtime folder, host, or port differs. The defaults are generic per-user paths, not project-private state.

## Screenshots

### What actually matters

Human-readable impact cards summarize the important change clusters first, with representative commits still visible for auditability.

![What actually matters view](docs/assets/screenshots/what-actually-matters.png)

### Raw categorized commits

The raw view keeps the full commit trail grouped by category, with review markers and safety notes available in the same page.

![Raw categorized commits view](docs/assets/screenshots/raw-categorized-commits.png)

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

Run the safe smoke test from the repo checkout:

```bash
python3 scripts/smoke_test.py
```

The smoke test checks repo files, Python syntax, a temporary-root generator run, the missing-checkout first-run page, installed runtime files, `state.json`, and the local helper API when it is running. It does not update Hermes, fetch upstream, restart services, install packages, or mutate the Hermes checkout.

## Repository layout

```text
src/generate.py                          Local page generator
src/serve.py                             Local-only helper server
systemd/hermes-release-radar.service     User systemd service
docs/help.html                           Rendered help page
docs/RELEASE_LOG.md                      Project changelog
scripts/render_help.py                   Markdown-to-help HTML renderer
scripts/smoke_test.py                    Safe health/smoke verification
HELP.md                                  Operator help
README.md                                Project overview
PURPOSE.md                               Project purpose and principles
VERSION                                  Current project version
```

## Versioning and releases

Release Radar uses semantic-ish project versions separate from Hermes Agent versions.

- Major: architecture or safety-model changes.
- Minor: user-facing features, generated page structure changes, helper API changes, or state-model additions.
- Patch/suffix: UI polish, docs, correctness fixes, or reliability improvements.

Git tags use the current project version with a leading `v`, for example `v0.2.7-ui`.

Release checklist:

```bash
python3 -m py_compile src/generate.py src/serve.py scripts/render_help.py
git status --short --branch
git tag -a vX.Y.Z-suffix -m "vX.Y.Z-suffix"
git push origin vX.Y.Z-suffix
gh release create vX.Y.Z-suffix --title "vX.Y.Z-suffix" --notes-file /tmp/release-notes.md
```

## Verification

```bash
python3 scripts/smoke_test.py
python3 -m py_compile src/generate.py src/serve.py scripts/render_help.py scripts/smoke_test.py
```
