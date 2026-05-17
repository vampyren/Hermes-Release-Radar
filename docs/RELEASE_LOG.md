# Release Log

## Unreleased

- Nothing yet.

## 0.3.0-public - 2026-05-17

- Implemented `src/generate_public.py` as a separate GitHub Pages/static demo generator.
- Added `public/index.html` and `public/snapshot.json` as public-only generated artifacts.
- Added a scheduled/manual GitHub Actions workflow that regenerates, privacy-scans, commits, and deploys public artifacts.
- Documented public demo vs local mode warnings in README and architecture docs.

## 0.2.8-docs - 2026-05-17

- Added README screenshots for the `What actually matters` and raw categorized commits views.
- Sanitized screenshot paths so public images show generic `~/.hermes/...` paths instead of local machine paths.
- Rewrote `#matters` card intro text to describe the feature/change directly instead of repeating `This matters because`.

## 0.2.7-ui - 2026-05-17

- Added original self-contained SVG app icon to the top-left page brand.
- Added the same icon as a local SVG favicon data URI.
- Applied branding consistently to the current page and history page.
- Removed default link underline from the app title for a more polished app feel.
- Added `VERSION` and documented the release/tagging workflow.

## 0.2.6-docs-ui - 2026-05-17

- Added operator help page as `HELP.md` and rendered `docs/help.html`.
- Added top-nav `?` help link in the generated radar page.
- Fixed auto-status detection so marker rendering cannot block `/api/status` checks when a legacy marker lacks a commit value.
- Restyled help command blocks to avoid nested boxes.
- Added copy buttons and wrapped long install commands with continuation lines.
- Prepared the public repository layout with source, systemd unit, docs, and helper scripts.

## 0.2.5-correctness - 2026-05-17

- Made Official release notes and What Actually Matters range-correct against `HEAD..origin/main`.
- Prevented already-installed release bodies from appearing as pending update information.
- Reduced client-side state embedded in `index.html`.

## 0.2.0 - 2026-05-17

- Added local helper service and durable server-side marker state.

## 0.1.0 - 2026-05-16

- Built static Release Radar MVP.
