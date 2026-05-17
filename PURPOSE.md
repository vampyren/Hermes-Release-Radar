# Purpose

Hermes Release Radar exists to make Hermes Agent updates understandable before a user decides whether to update.

The project is not an updater. It is an intelligence and review layer.

## Problem

Hermes Agent moves quickly. A raw commit list is too noisy, while a GitHub release page can be too broad or stale for a local install.

A user needs to know:

- What is ahead of my current local Hermes checkout?
- Which changes affect my daily workflows?
- Is there a new official release actually ahead of me?
- What have I already reviewed?
- What changed since the last refresh?
- What did I install in a previous update?

## Principles

- Local first: bind only to `127.0.0.1`.
- Safe by design: never run `hermes update`.
- Range correct: pending update info must come from `HEAD..origin/main`.
- Human first: explain why changes matter, not only what commits exist.
- Auditable: keep raw categorized commits available.
- Durable review state: `state.json` is canonical, not browser localStorage.
- Calm UI: use subtle pills and clear grouping, not noisy alert styling.
- Small surface area: Python stdlib, static HTML, user systemd.

## Non-goals

- Public web hosting.
- Multi-user auth.
- Updating Hermes directly.
- Package management.
- Replacing GitHub releases.
- Replacing a full dashboard/plugin system.

## Current status

The current implementation is a local helper service plus generated static pages.

The main page shows current pending upstream information. The history page records installed ranges after the local Hermes checkout advances. The help page documents service setup and useful commands.
