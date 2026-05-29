# Release Log

## Unreleased

No unreleased changes.

## 0.4.5-local - 2026-05-30

- Migrated stale persisted baseline checkpoint labels so the "Current installed state" card no longer shows operational error text like `hermes command not found` after the installed-version fallback fix recovered the real version.
- When an invalid `baseline_label` is found in `state.json` and the stored `baseline_commit` still matches current HEAD with a valid detected version, the label is repaired to the real current version string (for example `Hermes Agent v0.15.0 (2026.5.28)`); otherwise it falls back to a neutral `Checkpoint <shortsha>`. The `baseline_commit` value is never mutated by this migration.
- Blocked future invalid labels: `archive_if_head_advanced()` now stores a version label only when the version parsed and the raw text is not a command-not-found/unavailable error, using `Checkpoint <shortsha>` otherwise via the shared `is_valid_checkpoint_label()` / `checkpoint_label_for()` helpers.
- Added regression coverage for repairing `hermes command not found` to the valid current version when the baseline matches HEAD, repairing to `Checkpoint <shortsha>` when it cannot be mapped, leaving valid labels untouched, and never writing invalid raw version text during checkpoint archival.
- Safety: no `hermes update`, package install, force-push, destructive git operation (reset/stash/restore/clean), public helper exposure, or service restart was performed; the Hermes checkout was inspected read-only and not mutated.

## 0.4.4-local - 2026-05-23

- Fixed the Installed summary card showing `unknown` when the local helper service could inspect the Hermes checkout but could not find the `hermes` console script on its systemd `PATH`.
- Added a direct, read-only fallback that reads `hermes_cli/__init__.py` from the configured `RELEASE_RADAR_HERMES_REPO` checkout for `__version__` and `__release_date__` when `hermes --version` is unavailable or unparsable.
- Preserved the preferred CLI source of truth when available; the fallback only prevents a local wrapper/PATH issue from hiding the actual checked-out Hermes version.
- Added regression coverage for the minimal-`PATH` helper scenario so generated pages keep showing the local version instead of degrading to `Unknown` after branch switching or local feature testing.
- Runtime testing installed the fixed generator locally after backing up the previous runtime generator; no `hermes update`, package install, force-push, destructive git operation, public helper exposure, or service restart was performed.

## 0.4.3-local - 2026-05-19

- Fixed P0 helper security issues by removing wildcard CORS behavior, rejecting CORS preflight, enforcing local-only POSTs with Host/Origin/peer loopback checks, and replacing whole-runtime static serving with an explicit HTML whitelist.
- Added follow-up hardening for `/api/state`, review marker payload validation, maximum JSON body size, disabled directory listings before first generation, bounded `is_ancestor` git calls, and shared atomic/corrupt-state recovery helpers.
- Added regression coverage for hostile `/api/state` reads, directory-listing prevention, marker validation, request body limits, and temp-file cleanup on failed state writes.
- Updated runtime packaging docs, rendered help, and smoke checks to include the shared `state.py` helper required by installed `generate.py` and `serve.py`.
- Verification and hardening did not run `hermes update`, restart services, install packages, or perform destructive git operations.

## 0.4.2-local - 2026-05-19

- Polished the top summary strip: the Status card now keeps the Online/Offline badge centered on the right while the status text remains readable, and the Latest card has enough room for the current release label without truncation.

## 0.4.1-local - 2026-05-19

- Added `scripts/smoke_test.py` for safe one-command health verification of repo files, Python syntax, temporary-root generation, installed runtime state, and local helper API status.
- Added smoke-test guards for the core generated UI contracts: helper controls below status text, range-correct primary-category counts, active-tab preservation, and pending-range `#matters` cards.
- Fixed `Refresh from upstream` tab preservation by reloading to the active tab hash and mapping raw category/commit anchors back to the Raw tab.
- Fixed category jump and raw-section counts to use one primary category per pending commit, so visible category totals match the unique `HEAD..origin/main` commit count.
- Softened category refresh highlighting and widened/evened category tiles to reduce harsh yellow/brown contrast, awkward line breaks, and uneven grid gaps.
- Tuned refresh highlight pills to avoid heavy/glowy text while keeping the cyan tile edge accent and using a muted reddish `+N` badge.
- Overhauled `#matters` into category-grounded update area cards that mirror the Raw tab buckets, avoid stale refresh-count framing, and deep-link into raw category details.
- Demoted the Raw tab safety note to a quiet footnote unless local Hermes modified files need prominent review.
- Fixed `#matters` card bullets and representative dates so they are grounded in commits from the current `HEAD..origin/main` missing range.
- Standardized `#matters` cards on the green/teal edge treatment and replaced the generic `Update area` label with subtle low/medium/critical signal labels.
- Collapsed secondary `#matters` and Raw category context copy by default, applied the same subtle green jump-tile edge to Raw and Matters, softened near-white text into a muted blue-gray, and matched the `#matters` overview box to the Raw jump box without a left-edge accent.
- Added graceful first-run handling when the configured Hermes checkout is missing or not a git worktree, including setup guidance in the generated page.
- Added a smoke-test guard for the missing-checkout first-run page.
- Documented smoke-test usage in README and operator help.
- Added explicit design-language documentation in README and architecture docs for the dark teal/navy palette, muted text, compact sizing, helper layout, range-correct category cards, and restrained refresh badges.
- Aligned the generated history page and rendered help page with the same muted blue-gray primary text used by the current page.

## 0.4.0-local - 2026-05-17

- Removed the separate public GitHub Pages demo path to keep one generator and avoid drift.
- Deleted the public demo generator, generated public artifacts, and public rebuild workflow.
- Added environment-variable configuration for Hermes checkout, Release Radar runtime root, host, and port while preserving local defaults.
- Re-centered README and architecture docs around the local helper/generator product flow.

## 0.3.1-public - 2026-05-17

- Fixed the public demo workflow to enable GitHub Pages before deployment.

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
