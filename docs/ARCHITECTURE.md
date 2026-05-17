# Architecture

## Components

- `src/generate.py`: reads a user's local Hermes git/release data and writes generated pages.
- `src/serve.py`: local-only HTTP helper on `127.0.0.1:8765` by default.
- `state.json`: durable local state in `~/.hermes/release-radar/` by default.
- `index.html`: current pending-update radar page.
- `history.html`: installed-update history page.
- `help.html`: operator help page.
- `systemd/hermes-release-radar.service`: user service unit.

## Configuration

The defaults are generic per-user local paths:

```text
RELEASE_RADAR_HERMES_REPO=~/.hermes/hermes-agent
RELEASE_RADAR_ROOT=~/.hermes/release-radar
RELEASE_RADAR_HOST=127.0.0.1
RELEASE_RADAR_PORT=8765
```

A normal install does not need to set these. They exist so users with a non-default Hermes checkout, runtime folder, host, or port do not need to edit source code.

## GitHub presentation

The product is local-first. GitHub presentation is README/docs/screenshots only.

A separate public GitHub Pages generator and rebuild workflow were intentionally removed. Keeping one generator avoids drift and keeps the product focused on the user's own installed-vs-upstream comparison, local review markers, and local update decisions.

## Data flow

1. Browser opens `http://127.0.0.1:8765/` by default.
2. `serve.py` serves static files and API endpoints from `RELEASE_RADAR_ROOT`.
3. Page calls `/api/status` on load.
4. Refresh button calls `/api/refresh`.
5. `/api/refresh` runs `git fetch origin --quiet` in `RELEASE_RADAR_HERMES_REPO` and then regenerates the page.
6. Marker buttons call `/api/markers`.
7. `/api/markers` writes `review_markers` into `state.json` and regenerates the page.
8. On first run, `src/generate.py` initializes `state.json` from the current `HEAD` of the user's configured Hermes checkout.

## API

- `GET /api/status`: service and state metadata.
- `GET /api/state`: full local state for inspection.
- `POST /api/refresh`: fetch upstream refs and regenerate.
- `POST /api/markers`: persist review markers and regenerate.

## UI design choices

- Dark, calm theme.
- Three main tabs: Official release notes, What actually matters, Raw categorized commits.
- `#matters` cards stay calm; freshness is shown with compact pills instead of bright card borders.
- Representative commits render as wrapped chips.
- Representative commit dates show the commit date range represented by a card.
- Help page command blocks use one clean command panel, not nested inline-code boxes.
- Help command blocks include copy buttons and line-continuation wrapping for long paths.

## Safety boundaries

Allowed writes are limited to the configured Release Radar runtime folder.

Local-only safety boundaries:

- Do not turn Release Radar into an updater.
- Do not bind outside localhost by default.
- Do not publish a user's private runtime folder, local paths, service state, markers, or local checkout details.
- Do not maintain a separate public demo generator or generated public artifacts; README/docs/screenshots are enough for GitHub presentation.

Forbidden without separate explicit approval:

- `hermes update`
- destructive git operations
- package installation
- Hermes service restarts
- public network binding
