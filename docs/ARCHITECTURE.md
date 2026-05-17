# Architecture

## Components

- `src/generate.py`: reads Hermes git/release data and writes generated pages.
- `src/serve.py`: local-only HTTP helper on `127.0.0.1:8765`.
- `state.json`: durable local state in `~/.hermes/release-radar/`.
- `index.html`: current pending-update radar page.
- `history.html`: installed-update history page.
- `help.html`: operator help page.
- `systemd/hermes-release-radar.service`: user service unit.

## Data flow

1. Browser opens `http://127.0.0.1:8765/`.
2. `serve.py` serves static files and API endpoints.
3. Page calls `/api/status` on load.
4. Refresh button calls `/api/refresh`.
5. `/api/refresh` runs `git fetch origin --quiet` in `~/.hermes/hermes-agent` and then regenerates the page.
6. Marker buttons call `/api/markers`.
7. `/api/markers` writes `review_markers` into `state.json` and regenerates the page.

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

Allowed writes are limited to the Release Radar runtime folder.

Forbidden without separate explicit approval:

- `hermes update`
- destructive git operations
- package installation
- Hermes service restarts
- public network binding
