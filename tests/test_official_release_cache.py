#!/usr/bin/env python3
"""Tests for the #official last-official-release cache (v0.4.11-local)."""
from __future__ import annotations

import copy
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_generate(root: Path):
    os.environ["RELEASE_RADAR_ROOT"] = str(root)
    os.environ["RELEASE_RADAR_HERMES_REPO"] = str(REPO_ROOT)
    sys.modules.pop("generate", None)
    return importlib.import_module("generate")


REL_V17 = {
    "name": "Hermes Agent v0.17.0",
    "tag_name": "v2026.6.19",
    "html_url": "https://example.test/v0.17.0",
    "published_at": "2026-06-19T00:00:00Z",
    "body_excerpt": "The Reach Release body framing.",
    "highlights": [{"title": "iMessage via Photon", "text": "photon spectrum line pool"}],
    "commit": "aaaa1111",
}
REL_V18 = {
    "name": "Hermes Agent v0.18.0",
    "tag_name": "v2026.7.1",
    "html_url": "https://example.test/v0.18.0",
    "published_at": "2026-07-01T00:00:00Z",
    "body_excerpt": "Next release body framing.",
    "highlights": [{"title": "Brand new thing", "text": "shiny upgrade"}],
    "commit": "bbbb2222",
}


def base_data(reachable, *, generated="2026-06-21T02:40:40+02:00", behind=227):
    return {
        "repo_ok": True,
        "current_version": {"raw": "Hermes Agent v0.16.0 (2026.6.5)"},
        "latest_release": {"name": "Hermes Agent v0.17.0", "html_url": "https://example.test/v0.17.0"},
        "reachable_releases": list(reachable),
        "behind": behind,
        "generated_at": generated,
    }


class OfficialReleaseCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="release-radar-official-cache-")
        self.generate = load_generate(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # 1. reachable release exists -> cache updated and official tab renders current release
    def test_reachable_updates_cache_and_renders_live(self) -> None:
        data = base_data([REL_V17])
        state: dict = {}
        self.generate.update_official_release_cache(state, data)

        cache = state["last_official_release_notes"]
        self.assertEqual(cache["name"], "Hermes Agent v0.17.0")
        self.assertEqual(cache["tag_name"], "v2026.6.19")
        self.assertEqual(cache["highlights"][0]["title"], "iMessage via Photon")
        self.assertEqual(cache["commit"], "aaaa1111")
        self.assertEqual(cache["installed_raw"], "Hermes Agent v0.16.0 (2026.6.5)")
        self.assertEqual(cache["cached_at"], "2026-06-21T02:40:40+02:00")

        out = self.generate.render_official_release(data, state)
        self.assertIn("Next release ahead", out)
        self.assertIn("Hermes Agent v0.17.0", out)
        self.assertNotIn("Last official release", out)

    # 2a. no reachable + cache + behind == 0 -> "You are up to date" wording is OK
    def test_no_reachable_cache_behind_zero_says_up_to_date(self) -> None:
        state: dict = {}
        self.generate.update_official_release_cache(state, base_data([REL_V17]))

        out = self.generate.render_official_release(base_data([], behind=0), state)
        self.assertIn("Last official release", out)
        self.assertIn("You are up to date; showing the last official release notes for reference", out)
        self.assertNotIn("No newer official release is reachable", out)
        self.assertIn("Hermes Agent v0.17.0", out)
        self.assertIn("iMessage via Photon", out)
        # reference-only: not a pending/next release, and no claim about pending commits
        self.assertNotIn("Next release ahead", out)
        self.assertNotIn("pending commits", out)

    # 2b. no reachable + cache + behind > 0 -> must NOT say "up to date"
    def test_no_reachable_cache_behind_positive_not_up_to_date(self) -> None:
        state: dict = {}
        self.generate.update_official_release_cache(state, base_data([REL_V17]))

        out = self.generate.render_official_release(base_data([], behind=12), state)
        self.assertIn("Last official release", out)
        self.assertIn("No newer official release is reachable; showing the last official release notes for reference", out)
        self.assertNotIn("You are up to date", out)
        self.assertIn("Hermes Agent v0.17.0", out)
        # does not imply there are no pending commits
        self.assertNotIn("pending commits", out)
        self.assertNotIn("Next release ahead", out)

    # 2c. cached installed_raw must NOT be shown as the current installed version
    def test_cached_card_uses_live_installed_not_cached_installed_raw(self) -> None:
        state: dict = {}
        self.generate.update_official_release_cache(state, base_data([REL_V17]))
        # cache carries the install context from when it was written
        self.assertEqual(state["last_official_release_notes"]["installed_raw"], "Hermes Agent v0.16.0 (2026.6.5)")

        # after a Hermes update, current_version is newer; the card must show the live value
        data = base_data([], behind=0)
        data["current_version"] = {"raw": "Hermes Agent v0.17.0 (2026.6.19)"}
        out = self.generate.render_official_release(data, state)
        self.assertIn("Hermes Agent v0.17.0 (2026.6.19)", out)
        self.assertNotIn("Hermes Agent v0.16.0 (2026.6.5)", out)

    # 3. no reachable + no cache -> existing no-new-release behavior remains
    def test_no_reachable_no_cache_keeps_existing_behavior(self) -> None:
        out = self.generate.render_official_release(base_data([]), {})
        self.assertIn("No newer GitHub release tag is currently reachable", out)
        self.assertNotIn("Last official release", out)

        # and the cache is not written when nothing is reachable
        state: dict = {}
        self.generate.update_official_release_cache(state, base_data([]))
        self.assertNotIn("last_official_release_notes", state)

    # 4. newer reachable release replaces older cache
    def test_newer_release_replaces_cache(self) -> None:
        state: dict = {}
        self.generate.update_official_release_cache(state, base_data([REL_V17]))
        self.assertEqual(state["last_official_release_notes"]["name"], "Hermes Agent v0.17.0")

        self.generate.update_official_release_cache(state, base_data([REL_V18]))
        self.assertEqual(state["last_official_release_notes"]["name"], "Hermes Agent v0.18.0")
        self.assertEqual(state["last_official_release_notes"]["commit"], "bbbb2222")

    # empty reachable preserves a previously cached release (fetch error / up-to-date)
    def test_empty_reachable_preserves_existing_cache(self) -> None:
        state = {"last_official_release_notes": {"name": "kept", "commit": "keepsha"}}
        self.generate.update_official_release_cache(state, base_data([]))
        self.assertEqual(state["last_official_release_notes"]["name"], "kept")

    # 5. #matters/raw/review markers/history are unaffected by the cache update
    def test_cache_update_is_isolated_to_one_state_field(self) -> None:
        state = {
            "schema": 2,
            "review_markers": [{"commit": "x", "label": "reviewed"}],
            "history": [{"from_version": "a", "to_version": "b"}],
            "baseline_commit": "deadbeef",
        }
        before = copy.deepcopy(state)
        self.generate.update_official_release_cache(state, base_data([REL_V17]))

        self.assertEqual(state["review_markers"], before["review_markers"])
        self.assertEqual(state["history"], before["history"])
        self.assertEqual(state["baseline_commit"], before["baseline_commit"])
        self.assertEqual(
            set(state.keys()) - set(before.keys()),
            {"last_official_release_notes"},
        )


if __name__ == "__main__":
    unittest.main()
