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

Release Radar uses a compact dark-teal operational design language. Keep every generated page calm, readable, and local-tool-like rather than marketing-glossy.

### Core layout

- Three main current-page tabs: Official release notes, What actually matters, Raw categorized commits.
- Keep the local helper status text and long path details on their own row. Helper actions belong below that text, left-aligned and wrapped, so paths never compete with buttons or cause layout shift.
- Use compact cards with rounded corners, subtle borders, and restrained shadows. Avoid large padded hero blocks.
- Keep mobile safe: no horizontal overflow, `min-width:0` on grid/flex children, wrapped paths/code, and auto-fit grids that collapse to one column.
- `#matters` and Raw overview boxes should share the same understated container treatment; do not add a heavy left-edge accent to overview containers.

### Color and contrast

- Page background: near-black navy `#0b1014` with a soft dark-teal radial accent (`#18342f`) near the top-left.
- Panel/card surfaces: `#121a21`, `#101820`, or gradients around `#101c24` → `#0d151b`.
- Primary text: muted blue-gray `#c7d7dc`, not near-white. Muted text: `#91a4af`.
- Accent/callout color: cyan-teal `#62e6c8`; links may use soft cyan such as `#a8e9ff`.
- Borders: dark blue-gray `#26343d`; active/update edges may use subtle green/teal such as `#2b6d60` or `#2b8f78`.
- Avoid harsh yellow/brown boxes, bright yellow borders, or glowing warning panels. Yellow may appear only as a small medium-signal text accent when needed.
- Error/offline/danger states may use muted reds (`#3a1b22`, `#7d3543`, `#ffb3b3`) but should not dominate the page.

### Typography and sizing

- Base font: system UI stack at about `15px/1.45`.
- Main heading: responsive `clamp(24px, 6vw, 32px)`.
- Signal labels: small uppercase text around `11px`, letter-spaced, font weight around `650`.
- Buttons: compact `8px 10px` padding, rounded `10px`, readable but not oversized.
- Category jump tiles: minimum width around `260px`, normal height around `58px`, with the label kept readable and counts aligned to the right.
- Refresh/change pills: small, round, about `12px`, moderate weight around `650`; avoid fat `800+` weights and avoid text/glow shadows.

### Refresh and category language

- Category and `#matters` refresh deltas use small muted reddish `+N` pills (`#3a1f25` background, rose text/border) while keeping the tile/card edge cyan-teal. Do not use big `new upstream commits` banners.
- Raw and `#matters` category counts must use one primary category per pending commit, so visible category totals add up to the unique `HEAD..origin/main` count.
- `#matters` cards mirror Raw categories, show signal labels (`Critical`, `Medium`, `Low`) with small dots, and deep-link to matching Raw sections.
- `#matters` cards must stay range-correct: cards and representative commits come from the current missing range, not broad historical releases or arbitrary date windows.
- Representative commits render as a label line followed by wrapped chips. Representative commit dates show the commit date range represented by a card.
- Secondary explanatory copy belongs behind `<details>`/`<summary>` controls to preserve vertical density.

### Help and history pages

- Help page command blocks use one clean command panel, not nested inline-code boxes.
- Help command blocks include copy buttons and line-continuation wrapping for long paths.
- History/help/current pages should reuse the same dark navy/teal palette, muted primary text, soft cyan links, and app-brand treatment unless a page has a deliberate reason to differ.

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
