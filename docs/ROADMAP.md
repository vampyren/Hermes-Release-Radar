# Roadmap

## Near term

- Package the repo cleanly with stable install/update instructions.
- Add an install script only if needed; keep manual commands as the canonical transparent path.
- Add a small smoke-test script for local verification.
- Keep the help page rendered and readable on desktop and mobile.

## Later

- Optional config file for custom Hermes checkout/runtime paths if environment variables stop being enough.
- Optional authenticated LAN mode, only if needed.
- Better release-card grouping based on user relevance.
- Exportable update reports for note-taking tools.
- More robust rendered Markdown pipeline for docs/help pages.

## De-scoped

- Separate GitHub Pages/public demo generator and scheduled rebuild workflow. This was removed intentionally to keep one generator, avoid drift, and keep the product focused on local installed-vs-upstream comparison.

## Must not drift

- Do not turn Release Radar into an updater.
- Do not bind outside localhost by default.
- Do not maintain two generator scripts for local vs public output.
- Do not publish a user's local `state.json`, review markers, helper status, service API, local paths, or installed checkout details.
- Do not hide raw commit audit data.
- Do not show already-installed release bodies as pending update information.
