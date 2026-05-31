# Release Log

## Unreleased

No unreleased changes.

## 0.4.10-local - 2026-05-31

- Each category in the Raw categorized commits tab is now individually collapsible, the same way the Review markers card works: every category is a native `<details>` with a rotating chevron, open by default, so you can collapse/expand a category on its own without affecting the others. Layout and the per-category `Mark reviewed` / `Show all` behavior are unchanged; the `Mark reviewed` button no longer toggles the card when clicked.
- Added `Expand all` and `Collapse all` buttons (chevron icon + label) on the `Raw categorized commits` heading row, aligned to the right within the content frame, to open or close every category at once. They affect only the Raw-tab category cards.
- No behavioral change to release detection, review markers, or history. Release Radar still never runs `hermes update` and does not mutate the Hermes checkout.

## 0.4.9-local - 2026-05-30

- Fixed the History page showing operational error text such as `hermes command not found -> hermes command not found` as installed-update titles. Those came from archive records written before the baseline-label fix (v0.4.5-local), when version detection was failing; the bad text was stored durably in `history[].from_version` / `to_version`.
- Added a safe history migration (`migrate_history_version_labels`) that repairs only invalid history labels: it derives the real version from each record's baseline commit by reading `hermes_cli/__init__.py` at that commit with a read-only `git show` (never checking out or mutating the Hermes repo), and falls back to a neutral `Checkpoint <shortsha>` when a version cannot be reliably derived. Valid labels, commits, baselines, counts, dates, releases, and archived review markers are left untouched, and no history entries are added, removed, or reordered.
- Added a defensive render-side fallback so `render_history()` never displays operational error text even if a record has not been (or cannot be) repaired — it shows `Checkpoint <shortsha>` instead.
- The current installed records that previously showed `hermes command not found` map reliably to `Hermes Agent v0.14.0 (2026.5.16)` from the checkout metadata at their baseline commits.
- Removed the redundant `Use <date>` button from the Review-markers controls: it only pre-filled the label input with today's date, which `Mark all categories reviewed` already uses by default when the label is empty. The remaining `Mark all categories reviewed` and `Clear all markers` buttons fill its place. Marker labelling behavior is otherwise unchanged.
- Review-marker pruning behavior from v0.4.8-local is unchanged. Release Radar still never runs `hermes update` and does not mutate the Hermes checkout (read-only git inspection only).

## 0.4.8-local - 2026-05-30

- Fixed stale `Review markers` lingering after a Hermes update + Release Radar refresh: review markers are now reconciled server/generator-side against the current pending `HEAD..origin/main` view before `state.json` is saved and before the page is rendered (not only in the browser).
- When there are no pending upstream commits (`behind == 0`), all current-page review markers are cleared — there is nothing left to review.
- When commits are still pending (`behind > 0`), a marker is kept only when its target is still rendered (a global `top` marker, a category target from `category_counts`, or a raw commit target from `recent_commits`) and, for non-`top` markers carrying a commit hash, only when that commit is still in the pending set; markers whose category/commit has been implemented are pruned.
- Installed-update history is untouched: `archive_if_head_advanced()` still snapshots the full marker set into history when HEAD advances, and pruning runs after archival so no archived marker information is lost.
- Release Radar still never runs `hermes update`, never mutates the Hermes checkout, and performs only read-only git inspection.

## 0.4.7-local - 2026-05-30

- Fixed a visual regression where the History page no longer felt seamless with the main page: its top bar and frame used a flat background and a narrower (`1100px`) content width instead of the main page's radial-gradient background and `1180px` width.
- Extracted a single shared page shell (`SHELL_CSS`) used by both the current and history pages — same background gradient, content width, top bar, brand, version badge, card, base resets, and `h1` rhythm — so the two pages stay in sync instead of duplicating near-identical wrapper styles.
- Unified the top-bar brand: the history page now shows the same `Hermes Release Radar` brand (no `History` suffix) and the same top bar layout as the current page, so switching pages no longer shifts the header. You are still clearly on History via the page `h1`.
- Made the top nav a single page-toggle link in one shared slot: the current page shows `History (N)` (to `history.html`) and the history page shows `Current` (to `index.html`); neither page self-links. The `?` help icon stays on both pages and the brand/logo remains a way back to the main page.
- Aligned the history page heading: moved the `h1` rule into the shared shell so `Installed update history` lines up with the current page's heading rhythm instead of sitting lower (the page no longer feels jumpy when navigating).
- Added frame-aligned toast notifications (top-right of the ~1180px content frame, not the viewport edge) so the helper-bar buttons give visible confirmation: `Check status` now reports online/offline with marker count and last-generated time, `Refresh from upstream` shows an in-progress toast and a `Refreshed ✓` toast that survives the page reload, and review-marker save/clear actions confirm whether the change was persisted to `state.json`, held only until reload (helper offline), or failed. Toasts are subtle (dark theme, soft border), auto-dismiss, are click-to-dismiss, and never fire on automatic page load.
- Removed the redundant `Open service` link from the helper bar: it duplicated the brand/logo when viewing through the local helper (the normal case), so the brand/logo remains the single way to the app root.
- Display-only: the top-bar version badge drops the internal `-local` channel suffix (shows `0.4.7` instead of `0.4.7-local`); the raw `VERSION` value is unchanged for source/runtime logic.
- Added regression coverage for the shared shell (history embeds the same shell, gradient, `1180px` width, shared `h1` rhythm, unified brand, and help icon; no stale `1100px` width), for the page-toggle nav (history shows a `Current` link to `index.html` and does not self-link to `history.html`), and for the badge display formatting, plus smoke-test checks that the history page shares the main page's frame and that the helper-bar buttons expose the frame-aligned toast layer with the `Open service` link removed.
- Hardened the smoke test so the category/`#matters` UI contracts only run when the inspected checkout is behind upstream; an up-to-date checkout (`behind == 0`) renders no category/`#matters` cards, so requiring their markers was a false failure unrelated to the generator.

## 0.4.6-local - 2026-05-30

- Removed the redundant `Current` link from the top navigation on both the current and history pages; the brand/logo/title still links back to `index.html`, so there is always a way back to the main page. The top nav is now just `History (N)` and the `?` help icon.
- Added a discreet Release Radar app-version badge next to the brand in the top bar on both pages (small, muted, compact pill — no extra card or summary item).
- Clarified that the badge is the Release Radar **app** version (read from the repo `VERSION` file, single source of truth), not the inspected Hermes Agent version shown in the page content; the badge carries a `Hermes Release Radar app version` tooltip to avoid confusion.
- `generate.py` reads `VERSION` cleanly from either the repo checkout or the installed runtime, and the badge degrades gracefully (hidden) if no `VERSION` file is present. Runtime install/update now copies `VERSION` into `~/.hermes/release-radar/`; README, HELP.md, docs/help.html, and the smoke test runtime-file check were updated accordingly.
- Safety: no `hermes update`, package install, force-push, destructive git operation (reset/stash/restore/clean), Hermes-checkout mutation, public helper exposure, or service restart was performed.

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
