# Architecture

## Components

- `src/generate.py`: reads Hermes git/release data and writes generated pages.
- `src/serve.py`: local-only HTTP helper on `127.0.0.1:8765`.
- `state.json`: durable local state in `~/.hermes/release-radar/`.
- `index.html`: current pending-update radar page.
- `history.html`: installed-update history page.
- `help.html`: operator help page.
- `systemd/hermes-release-radar.service`: user service unit.

## Planned public GitHub Pages mode

GitHub Pages should be a separate public/demo build path, not the local Rex workflow.

Intended shape:

- Public output lives under a dedicated generated folder such as `public/` or `docs/public/`.
- GitHub Actions runs on a schedule and on manual dispatch.
- The workflow checks out/fetches public Hermes Agent data, runs a public-mode generator, and commits generated static files only when content changes.
- The generated public page must not include helper API controls, local service status, local filesystem paths, Rex's `state.json`, review markers, or installed-checkout-specific claims.
- The public page should warn clearly: this is a public static demo. To compare your own installed Hermes checkout and track your own review markers, run Release Radar locally.
- Local mode remains the canonical personal workflow and stays bound to `127.0.0.1`.

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

Public Pages safety boundaries:

- Never publish Rex's private runtime folder, local paths, service state, markers, or local checkout details.
- GitHub Actions may write generated public artifacts and commit them back to the repository when the workflow is explicitly added for public mode.
- The public site must not imply it can update Hermes. Updates happen only in a user's local environment after they run their own install/update process.

Forbidden without separate explicit approval:

- `hermes update`
- destructive git operations
- package installation
- Hermes service restarts
- public network binding
