#!/usr/bin/env python3
"""State-file regression tests for generator/helper state handling."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


class StateRecoveryTests(unittest.TestCase):
    def load_generate_with_root(self, root: Path, hermes_repo: Path | None = None):
        os.environ["RELEASE_RADAR_ROOT"] = str(root)
        os.environ["RELEASE_RADAR_HERMES_REPO"] = str(hermes_repo or REPO_ROOT)
        sys.modules.pop("generate", None)
        return importlib.import_module("generate")

    def test_generate_load_state_recovers_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-state-test-") as tmp:
            root = Path(tmp)
            state_path = root / "state.json"
            state_path.write_text("{broken", encoding="utf-8")
            generate = self.load_generate_with_root(root)

            state = generate.load_state()

            self.assertEqual(state["schema"], 2)
            self.assertEqual(state["review_markers"], [])
            self.assertIn("state_warning", state)
            self.assertFalse(state_path.exists())
            self.assertTrue((root / "state.json.corrupt").exists())

    def test_generate_save_state_writes_valid_json_atomically(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-state-test-") as tmp:
            root = Path(tmp)
            generate = self.load_generate_with_root(root)

            generate.save_state({"review_markers": [{"id": "one"}]})

            saved = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["schema"], 2)
            self.assertEqual(saved["review_markers"], [{"id": "one"}])
            self.assertEqual(list(root.glob("state.json.*.tmp")), [])

    def test_generate_save_state_cleans_temp_file_on_json_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-state-test-") as tmp:
            root = Path(tmp)
            generate = self.load_generate_with_root(root)

            with self.assertRaises(TypeError):
                generate.save_state({"bad": object()})

            self.assertFalse((root / "state.json").exists())
            self.assertEqual(list(root.glob("state.json.*.tmp")), [])

    def test_sh_check_false_handles_missing_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-state-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))

            output = generate.sh(["definitely-not-a-real-command-release-radar"], check=False)

            self.assertIn("command not found", output)

    def test_version_output_falls_back_to_local_source_when_hermes_cli_missing_from_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-version-test-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            package_dir = hermes_repo / "hermes_cli"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text(
                '__version__ = "9.8.7"\n__release_date__ = "2099.1.2"\n',
                encoding="utf-8",
            )
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = "/usr/bin:/bin"
            try:
                generate = self.load_generate_with_root(root, hermes_repo)

                output = generate.resolve_version_output()
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(output, "Hermes Agent v9.8.7 (2099.1.2)")


class BaselineLabelMigrationTests(unittest.TestCase):
    def load_generate_with_root(self, root: Path, hermes_repo: Path | None = None):
        os.environ["RELEASE_RADAR_ROOT"] = str(root)
        os.environ["RELEASE_RADAR_HERMES_REPO"] = str(hermes_repo or REPO_ROOT)
        sys.modules.pop("generate", None)
        return importlib.import_module("generate")

    def make_git_repo(self, path: Path) -> tuple[str, str]:
        """Create a tiny git repo with two commits; return (first, second) SHAs."""
        path.mkdir(parents=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=str(path), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout.strip()

        git("init", "-q")
        (path / "a.txt").write_text("one\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "first")
        first = git("rev-parse", "HEAD")
        (path / "a.txt").write_text("two\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "second")
        second = git("rev-parse", "HEAD")
        return first, second

    def test_is_valid_checkpoint_label_rejects_operational_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-label-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            for bad in ["", "unknown", "hermes command not found", "Hermes CLI version unavailable", "Hermes checkout unavailable"]:
                self.assertFalse(generate.is_valid_checkpoint_label(bad), bad)
            for good in ["Hermes Agent v0.15.0 (2026.5.28)", "Checkpoint 680478a98750", "Initial Release Radar baseline"]:
                self.assertTrue(generate.is_valid_checkpoint_label(good), good)

    def test_migrate_repairs_bad_label_to_current_version_when_baseline_is_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-migrate-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            head = "680478a98750" + "0" * 28
            state = {"baseline_commit": head, "baseline_label": "hermes command not found"}
            data = {"head": head, "current_version": generate.parse_version("Hermes Agent v0.15.0 (2026.5.28)")}

            generate.migrate_baseline_label(state, data)

            self.assertEqual(state["baseline_label"], "Hermes Agent v0.15.0 (2026.5.28)")
            self.assertEqual(state["baseline_commit"], head)

    def test_migrate_repairs_bad_label_to_checkpoint_when_not_mappable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-migrate-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            baseline = "680478a98750" + "0" * 28
            head = "11d93096b39e" + "1" * 28
            state = {"baseline_commit": baseline, "baseline_label": "hermes command not found"}
            data = {"head": head, "current_version": generate.parse_version("Hermes Agent v0.15.0 (2026.5.28)")}

            generate.migrate_baseline_label(state, data)

            self.assertEqual(state["baseline_label"], "Checkpoint 680478a98750")
            self.assertEqual(state["baseline_commit"], baseline)

    def test_migrate_leaves_valid_label_untouched(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-migrate-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            head = "abc" + "0" * 37
            state = {"baseline_commit": head, "baseline_label": "Hermes Agent v0.14.0 (2026.4.1)"}
            data = {"head": head, "current_version": generate.parse_version("Hermes Agent v0.15.0 (2026.5.28)")}

            generate.migrate_baseline_label(state, data)

            self.assertEqual(state["baseline_label"], "Hermes Agent v0.14.0 (2026.4.1)")

    def test_version_badge_strips_local_suffix_for_display(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-badge-display-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            # Raw version keeps the internal channel suffix; the badge does not.
            self.assertTrue(generate.APP_VERSION.endswith("-local"))
            self.assertEqual(generate.APP_VERSION_DISPLAY, generate.APP_VERSION.removesuffix("-local"))
            self.assertNotIn("-local", generate.APP_VERSION_BADGE)
            self.assertIn(f">{generate.APP_VERSION_DISPLAY}<", generate.APP_VERSION_BADGE)

    def test_history_page_shares_main_page_shell(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-shell-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            history_html = generate.render_history({"history": []})
            # History embeds the one shared shell verbatim instead of a divergent copy.
            self.assertIn(generate.SHELL_CSS, history_html)
            # Same frame as the main page: gradient background + 1180px content width.
            self.assertIn("radial-gradient(circle at 15% 0,#18342f 0,#0b1014 34rem)", generate.SHELL_CSS)
            self.assertIn("max-width:1180px", generate.SHELL_CSS)
            # Shared page-header rhythm so the h1 lines up instead of sitting lower.
            self.assertIn("h1{font-size:clamp(24px,6vw,32px);margin:0 0 4px}", generate.SHELL_CSS)
            # The old divergent history shell (flat bg / 1100px) must be gone.
            self.assertNotIn("max-width:1100px", history_html)
            # Page toggle: history shows a "Current" link to index.html and does
            # not self-link to history.html (the current page shows "History (N)").
            self.assertIn('<a href="index.html">Current</a>', history_html)
            self.assertNotIn('href="history.html"', history_html)
            # Brand text stays unified ("Hermes Release Radar"), no "History" suffix.
            self.assertNotIn("<span>Hermes Release Radar History</span>", history_html)
            self.assertIn("<span>Hermes Release Radar</span>", history_html)
            # Same topbar layout as the current page: brand links home + help icon.
            self.assertIn('class="brand" href="index.html"', history_html)
            self.assertIn('class="help-icon"', history_html)

    def test_app_version_prefers_repo_version_over_stale_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-version-badge-test-") as tmp:
            root = Path(tmp)
            # Simulate a stale VERSION sitting in RELEASE_RADAR_ROOT.
            (root / "VERSION").write_text("9.9.9-stale\n", encoding="utf-8")
            generate = self.load_generate_with_root(root)

            repo_version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip().splitlines()[0].strip()

            # Running from repo src/generate.py must report the repo's own VERSION,
            # not the stale RELEASE_RADAR_ROOT/VERSION.
            self.assertEqual(generate.read_app_version(), repo_version)
            self.assertNotEqual(generate.read_app_version(), "9.9.9-stale")
            # The module-load constant (used to build the badge) reflects it too.
            self.assertEqual(generate.APP_VERSION, repo_version)

    def test_archive_if_head_advanced_never_stores_invalid_raw_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-archive-test-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            first, second = self.make_git_repo(hermes_repo)
            generate = self.load_generate_with_root(root, hermes_repo)

            state = {"baseline_commit": first, "baseline_label": "Hermes Agent v0.14.0 (2026.4.1)", "review_markers": [], "history": []}
            data = {
                "repo_ok": True,
                "head": second,
                "generated_at": "2026-05-30T00:00:00+00:00",
                "current_version": generate.parse_version("hermes command not found"),
                "latest_release": {},
                "reachable_releases": [],
            }

            generate.archive_if_head_advanced(state, data)

            self.assertEqual(state["baseline_commit"], second)
            self.assertNotEqual(state["baseline_label"], "hermes command not found")
            self.assertTrue(generate.is_valid_checkpoint_label(state["baseline_label"]))
            self.assertEqual(state["baseline_label"], f"Checkpoint {second[:12]}")

    def _pending_data(self, generate, recent, categories):
        return {
            "repo_ok": True,
            "behind": len(recent),
            "category_counts": {cat: 1 for cat in categories},
            "recent_commits": recent,
        }

    def test_prune_keeps_markers_still_in_pending_view(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-prune-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            recent = [{"full": "a" * 40, "short": "aaaaaaa"}, {"full": "b" * 40, "short": "bbbbbbb"}]
            data = self._pending_data(generate, recent, ["CLI/TUI"])
            cat_target = generate.anchor_id("cat", "CLI/TUI")
            state = {"review_markers": [
                {"id": "1", "target_id": "top", "commit": "a" * 40},          # global -> keep
                {"id": "2", "target_id": cat_target, "commit": "a" * 40},     # category rendered + commit pending -> keep
                {"id": "3", "target_id": "commit-bbbbbbb", "commit": "b" * 40},  # raw commit still pending -> keep
            ], "history": []}

            generate.prune_review_markers(state, data)

            self.assertEqual([m["id"] for m in state["review_markers"]], ["1", "2", "3"])

    def test_prune_removes_markers_for_disappeared_targets_and_commits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-prune-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            recent = [{"full": "a" * 40, "short": "aaaaaaa"}]
            data = self._pending_data(generate, recent, ["CLI/TUI"])
            cli_target = generate.anchor_id("cat", "CLI/TUI")
            gone_cat_target = generate.anchor_id("cat", "Docs")
            state = {"review_markers": [
                {"id": "top", "target_id": "top", "commit": "a" * 40},               # keep
                {"id": "gone-cat", "target_id": gone_cat_target, "commit": "a" * 40},  # category no longer rendered -> drop
                {"id": "gone-commit", "target_id": "commit-zzzzzzz", "commit": "z" * 40},  # raw commit gone -> drop
                {"id": "impl", "target_id": cli_target, "commit": "c" * 40},          # category rendered but commit implemented -> drop
            ], "history": []}

            generate.prune_review_markers(state, data)

            self.assertEqual([m["id"] for m in state["review_markers"]], ["top"])

    def test_prune_clears_all_markers_when_behind_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-prune-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            data = {"repo_ok": True, "behind": 0, "category_counts": {}, "recent_commits": []}
            state = {"review_markers": [
                {"id": "top", "target_id": "top", "commit": "a" * 40},
                {"id": "cat", "target_id": generate.anchor_id("cat", "CLI/TUI"), "commit": "a" * 40},
            ], "history": [{"some": "history"}]}

            generate.prune_review_markers(state, data)

            self.assertEqual(state["review_markers"], [])
            # Installed-update history must not be touched by pruning.
            self.assertEqual(state["history"], [{"some": "history"}])

    def test_prune_skips_when_repo_not_ok(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-prune-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            markers = [{"id": "1", "target_id": "top", "commit": "a" * 40}]
            state = {"review_markers": list(markers), "history": []}
            # A failed repo read (repo_ok False, behind 0) must NOT wipe markers.
            generate.prune_review_markers(state, {"repo_ok": False, "behind": 0, "category_counts": {}, "recent_commits": []})
            self.assertEqual(state["review_markers"], markers)

    def test_archive_preserves_review_markers_in_history_then_prune_no_ops(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-archive-prune-test-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            first, second = self.make_git_repo(hermes_repo)
            generate = self.load_generate_with_root(root, hermes_repo)

            existing_markers = [{"id": "m1", "target_id": "top", "commit": first}]
            state = {"baseline_commit": first, "baseline_label": "Hermes Agent v0.14.0 (2026.4.1)", "review_markers": list(existing_markers), "history": []}
            data = {"repo_ok": True, "head": second, "generated_at": "2026-05-30T00:00:00+00:00",
                    "current_version": generate.parse_version("Hermes Agent v0.15.0 (2026.5.28)"),
                    "latest_release": {}, "reachable_releases": [], "behind": 0, "category_counts": {}, "recent_commits": []}

            generate.archive_if_head_advanced(state, data)
            # Archive snapshots the full marker set into history and clears the live set.
            self.assertEqual(state["history"][-1]["review_markers_archived"], existing_markers)
            self.assertEqual(state["review_markers"], [])

            # Pruning after archive is a no-op on the now-empty live set; history intact.
            generate.prune_review_markers(state, data)
            self.assertEqual(state["review_markers"], [])
            self.assertEqual(state["history"][-1]["review_markers_archived"], existing_markers)

    def make_versioned_git_repo(self, path: Path, versions):
        """Create a git repo with one commit per (version, date), writing
        hermes_cli/__init__.py each time. Returns the list of commit SHAs."""
        path.mkdir(parents=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=str(path), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout.strip()

        git("init", "-q")
        (path / "hermes_cli").mkdir()
        shas = []
        for ver, date in versions:
            (path / "hermes_cli" / "__init__.py").write_text(f'__version__ = "{ver}"\n__release_date__ = "{date}"\n', encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", f"release {ver}")
            shas.append(git("rev-parse", "HEAD"))
        return shas

    def test_migrate_history_repairs_invalid_labels_from_commit_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-histlabel-test-") as tmp:
            hermes = Path(tmp) / "hermes-agent"
            sha_a, sha_b = self.make_versioned_git_repo(hermes, [("0.14.0", "2026.5.16"), ("0.15.0", "2026.5.28")])
            generate = self.load_generate_with_root(Path(tmp) / "runtime", hermes)
            state = {"history": [{
                "from_version": "hermes command not found", "to_version": "hermes command not found",
                "old_baseline": sha_a, "new_baseline": sha_b, "commit_count": 5, "commits": [{"short": "x"}],
            }]}

            generate.migrate_history_version_labels(state, {"repo_ok": True})

            self.assertEqual(state["history"][0]["from_version"], "Hermes Agent v0.14.0 (2026.5.16)")
            self.assertEqual(state["history"][0]["to_version"], "Hermes Agent v0.15.0 (2026.5.28)")
            # Other fields and the entry itself are preserved.
            self.assertEqual(state["history"][0]["commit_count"], 5)
            self.assertEqual(state["history"][0]["commits"], [{"short": "x"}])
            self.assertEqual(len(state["history"]), 1)

    def test_migrate_history_leaves_underivable_labels_for_render_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-histlabel-test-") as tmp:
            hermes = Path(tmp) / "hermes-agent"
            self.make_versioned_git_repo(hermes, [("0.14.0", "2026.5.16")])
            generate = self.load_generate_with_root(Path(tmp) / "runtime", hermes)
            missing = "d" * 40
            state = {"history": [{"from_version": "unknown", "to_version": "hermes command not found",
                                  "old_baseline": missing, "new_baseline": missing,
                                  "commit_count": 2, "commits": [], "category_counts": {}, "releases": []}]}

            generate.migrate_history_version_labels(state, {"repo_ok": True})

            # Not derivable -> durable labels left untouched (no casual rewrite of history).
            self.assertEqual(state["history"][0]["from_version"], "unknown")
            self.assertEqual(state["history"][0]["to_version"], "hermes command not found")
            # ...but render shows a neutral checkpoint and never the operational text.
            html_out = generate.render_history(state)
            self.assertNotIn("hermes command not found", html_out)
            self.assertIn(f"Checkpoint {missing[:12]}", html_out)

    def test_migrate_history_leaves_valid_labels_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-histlabel-test-") as tmp:
            hermes = Path(tmp) / "hermes-agent"
            sha_a, sha_b = self.make_versioned_git_repo(hermes, [("0.14.0", "2026.5.16"), ("0.15.0", "2026.5.28")])
            generate = self.load_generate_with_root(Path(tmp) / "runtime", hermes)
            # Stored labels are valid but deliberately different from what the commits would derive.
            state = {"history": [{"from_version": "Hermes Agent v0.13.0 (2026.5.7)", "to_version": "Hermes Agent v0.14.0 (2026.5.16)",
                                  "old_baseline": sha_a, "new_baseline": sha_b}]}

            generate.migrate_history_version_labels(state, {"repo_ok": True})

            self.assertEqual(state["history"][0]["from_version"], "Hermes Agent v0.13.0 (2026.5.7)")
            self.assertEqual(state["history"][0]["to_version"], "Hermes Agent v0.14.0 (2026.5.16)")

    def test_migrate_history_skips_and_preserves_when_repo_not_ok(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-histlabel-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            original = [{"from_version": "hermes command not found", "to_version": "unknown",
                         "old_baseline": "a" * 40, "new_baseline": "b" * 40, "commit_count": 3}]
            state = {"history": [dict(original[0])]}

            generate.migrate_history_version_labels(state, {"repo_ok": False})

            self.assertEqual(state["history"], original)  # not derived/rewritten when checkout unreadable

    def test_render_history_never_shows_operational_error_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-histlabel-test-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            bad = generate.render_history({"history": [{
                "from_version": "hermes command not found", "to_version": "unavailable",
                "old_baseline": "1e71b7180e5b" + "0" * 28, "new_baseline": "680478a98750" + "0" * 28,
                "commit_count": 5, "commits": [], "category_counts": {}, "releases": [],
            }]})
            self.assertNotIn("hermes command not found", bad)
            self.assertNotIn("unavailable", bad)
            self.assertIn("Checkpoint 1e71b7180e5b", bad)
            self.assertIn("Checkpoint 680478a98750", bad)

            good = generate.render_history({"history": [{
                "from_version": "Hermes Agent v0.14.0 (2026.5.16)", "to_version": "Hermes Agent v0.15.0 (2026.5.28)",
                "old_baseline": "a" * 40, "new_baseline": "b" * 40,
                "commit_count": 1, "commits": [], "category_counts": {}, "releases": [],
            }]})
            self.assertIn("Hermes Agent v0.14.0 (2026.5.16)", good)
            self.assertIn("Hermes Agent v0.15.0 (2026.5.28)", good)

    # ---- history gap detection / recovery (divergent upstream history) ----

    def make_divergent_git_repo(self, path: Path) -> tuple[str, str, str]:
        """Build a repo whose stored baseline is NOT an ancestor of HEAD.

        Shape:  base ──A           (A = stale baseline on a side branch)
                     └─B──C        (C = current HEAD on the main line)
        merge-base(A, C) == base; A is not an ancestor of C and vice versa.
        Returns (base, stale_baseline_A, head_C).
        """
        path.mkdir(parents=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=str(path), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout.strip()

        git("init", "-q")
        (path / "a.txt").write_text("base\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        main_branch = git("rev-parse", "--abbrev-ref", "HEAD")
        # side branch: the commit that becomes the stale (later rewritten-away) baseline
        git("checkout", "-q", "-b", "side")
        (path / "a.txt").write_text("stale\n", encoding="utf-8")
        git("commit", "-q", "-am", "stale baseline A")
        stale = git("rev-parse", "HEAD")
        # main line advances independently to HEAD
        git("checkout", "-q", main_branch)
        (path / "a.txt").write_text("main-b\n", encoding="utf-8")
        git("commit", "-q", "-am", "main B")
        (path / "a.txt").write_text("main-c\n", encoding="utf-8")
        git("commit", "-q", "-am", "main C")
        head = git("rev-parse", "HEAD")
        return base, stale, head

    def test_divergent_baseline_records_gap_and_recovers_baseline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-gap-test-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            base, stale, head = self.make_divergent_git_repo(hermes_repo)
            generate = self.load_generate_with_root(root, hermes_repo)

            prior = {"archived_at": "2026-05-23T00:00:00+00:00", "old_baseline": "x" * 40,
                     "new_baseline": stale, "from_version": "Hermes Agent v0.13.0 (2026.5.7)",
                     "to_version": "Hermes Agent v0.14.0 (2026.5.16)", "commit_count": 1,
                     "commits": [], "category_counts": {}, "releases": []}
            state = {"baseline_commit": stale, "baseline_label": "Hermes Agent v0.14.0 (2026.5.16)",
                     "review_markers": [{"id": "m"}], "history": [prior],
                     "checkpoint_warning": "stale warning from a prior run"}
            # HEAD == origin/main => trusted lineage
            data = {"repo_ok": True, "head": head, "upstream": head, "generated_at": "2026-06-21T00:00:00+00:00",
                    "current_version": generate.parse_version("Hermes Agent v0.17.0 (2026.6.19)"),
                    "latest_release": {}, "reachable_releases": []}

            generate.archive_if_head_advanced(state, data)

            # existing history preserved + one gap record appended
            self.assertEqual(len(state["history"]), 2)
            self.assertIs(state["history"][0], prior)
            gap = state["history"][1]
            self.assertEqual(gap.get("kind"), "gap")
            self.assertEqual(gap["old_baseline"], stale)
            self.assertEqual(gap["new_baseline"], head)
            self.assertEqual(gap["merge_base"], base)
            self.assertTrue(gap.get("commit_count_approximate"))
            # baseline recovered so future updates archive normally again
            self.assertEqual(state["baseline_commit"], head)
            self.assertEqual(state["review_markers"], [])
            # stale warning cleared; recovery notice set
            self.assertNotIn("checkpoint_warning", state)
            self.assertIn("gap", state.get("checkpoint_notice", "").lower())

            # idempotent: a second run (baseline == head now) adds no duplicate gap
            generate.archive_if_head_advanced(state, data)
            self.assertEqual(len(state["history"]), 2)
            self.assertEqual(state["baseline_commit"], head)

    def test_divergent_gap_does_not_invent_version_labels(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-gap-labels-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            base, stale, head = self.make_divergent_git_repo(hermes_repo)
            generate = self.load_generate_with_root(root, hermes_repo)
            # no hermes_cli/__init__.py in these commits and no valid stored label =>
            # nothing reliably derivable, so it must fall back to a neutral checkpoint
            state = {"baseline_commit": stale, "baseline_label": "",
                     "review_markers": [], "history": []}
            data = {"repo_ok": True, "head": head, "upstream": head, "generated_at": "2026-06-21T00:00:00+00:00",
                    "current_version": generate.parse_version("Hermes Agent v0.17.0 (2026.6.19)"),
                    "latest_release": {}, "reachable_releases": []}

            generate.archive_if_head_advanced(state, data)
            gap = state["history"][-1]
            # to_version is the real current version; from_version falls back to a neutral
            # checkpoint (NOT an invented intermediate version)
            self.assertEqual(gap["to_version"], "Hermes Agent v0.17.0 (2026.6.19)")
            self.assertEqual(gap["from_version"], f"Checkpoint {stale[:12]}")
            self.assertNotIn("v0.15", gap["from_version"])
            self.assertNotIn("v0.16", gap["from_version"])

    def test_head_behind_baseline_warns_and_does_not_fabricate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-rollback-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            first, second = self.make_git_repo(hermes_repo)
            generate = self.load_generate_with_root(root, hermes_repo)
            # stored baseline is AHEAD of HEAD (rollback): second -> first
            state = {"baseline_commit": second, "baseline_label": "Hermes Agent v0.17.0 (2026.6.19)",
                     "review_markers": [], "history": []}
            data = {"repo_ok": True, "head": first, "generated_at": "2026-06-21T00:00:00+00:00",
                    "current_version": generate.parse_version("Hermes Agent v0.16.0 (2026.6.5)"),
                    "latest_release": {}, "reachable_releases": []}

            generate.archive_if_head_advanced(state, data)
            # no gap fabricated, baseline untouched, warning set
            self.assertEqual(state["history"], [])
            self.assertEqual(state["baseline_commit"], second)
            self.assertIn("behind", state.get("checkpoint_warning", "").lower())

    def test_normal_ancestor_archive_has_no_gap_kind(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-normal-arch-") as tmp:
            root = Path(tmp) / "runtime"
            hermes_repo = Path(tmp) / "hermes-agent"
            first, second = self.make_git_repo(hermes_repo)
            generate = self.load_generate_with_root(root, hermes_repo)
            state = {"baseline_commit": first, "baseline_label": "Hermes Agent v0.16.0 (2026.6.5)",
                     "review_markers": [], "history": []}
            data = {"repo_ok": True, "head": second, "generated_at": "2026-06-21T00:00:00+00:00",
                    "current_version": generate.parse_version("Hermes Agent v0.17.0 (2026.6.19)"),
                    "latest_release": {}, "reachable_releases": []}

            generate.archive_if_head_advanced(state, data)
            self.assertEqual(len(state["history"]), 1)
            self.assertNotEqual(state["history"][0].get("kind"), "gap")
            self.assertEqual(state["baseline_commit"], second)

    def test_render_history_gap_uses_neutral_wording_over_old_note(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-gap-render-") as tmp:
            generate = self.load_generate_with_root(Path(tmp))
            out = generate.render_history({
                "checkpoint_warning": "Current HEAD abc is behind stored baseline def (possible Hermes rollback); not auto-archiving.",
                "history": [
                    {  # legacy gap record carrying the OLD asserted-as-fact note
                        "kind": "gap", "archived_at": "2026-06-21T00:00:00+00:00",
                        "old_baseline": "a" * 40, "new_baseline": "b" * 40, "merge_base": "c" * 40,
                        "from_version": "Checkpoint aaaaaaaaaaaa", "to_version": "Hermes Agent v0.17.0 (2026.6.19)",
                        "commit_count": 3119, "commit_count_approximate": True,
                        "commits": [], "category_counts": {}, "releases": [],
                        "note": "Upstream history was rewritten: the previously recorded baseline ...",
                    },
                    {  # an ordinary old archive must still render unchanged
                        "from_version": "Hermes Agent v0.13.0 (2026.5.7)", "to_version": "Hermes Agent v0.14.0 (2026.5.16)",
                        "old_baseline": "d" * 40, "new_baseline": "e" * 40,
                        "commit_count": 7, "commits": [], "category_counts": {}, "releases": [],
                    },
                ],
            })
            # gap card distinct + approximate
            self.assertIn("History gap", out)
            self.assertIn("3119", out)
            self.assertIn("(approximate)", out)
            # neutral canonical wording displayed; old asserted-as-fact note NOT displayed
            self.assertIn("diverged from the current trusted origin/main lineage", out)
            self.assertNotIn("Upstream history was rewritten", out)
            # ordinary old record still renders; warning visible
            self.assertIn("Hermes Agent v0.13.0 (2026.5.7)", out)
            self.assertIn("possible Hermes rollback", out)

    # ---- trust gating for automatic gap recovery (ChatGPT safety blocker) ----

    def make_trust_repo(self, path: Path) -> dict:
        """Build a repo with main lineage, a side branch, and an orphan history.

            base ── A                 (side branch)
                 └─ B ── C            (main line / origin/main tip)
            (orphan root) O           (unrelated history, no merge-base with C)

        Returns dict of SHAs: base, A, B, C, orphan, main_branch.
        """
        path.mkdir(parents=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")

        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=str(path), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout.strip()

        git("init", "-q")
        (path / "a.txt").write_text("base\n", encoding="utf-8")
        git("add", "a.txt"); git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        main_branch = git("rev-parse", "--abbrev-ref", "HEAD")
        git("checkout", "-q", "-b", "side")
        (path / "a.txt").write_text("side\n", encoding="utf-8"); git("commit", "-q", "-am", "A")
        A = git("rev-parse", "HEAD")
        git("checkout", "-q", main_branch)
        (path / "a.txt").write_text("b\n", encoding="utf-8"); git("commit", "-q", "-am", "B")
        B = git("rev-parse", "HEAD")
        (path / "a.txt").write_text("c\n", encoding="utf-8"); git("commit", "-q", "-am", "C")
        C = git("rev-parse", "HEAD")
        git("checkout", "-q", "--orphan", "orphanb")
        (path / "o.txt").write_text("orphan\n", encoding="utf-8")
        git("add", "o.txt"); git("commit", "-q", "-m", "orphan root")
        orphan = git("rev-parse", "HEAD")
        git("checkout", "-q", main_branch)
        return {"base": base, "A": A, "B": B, "C": C, "orphan": orphan, "main_branch": main_branch}

    def _diverge_data(self, generate, head, upstream):
        return {"repo_ok": True, "head": head, "upstream": upstream, "generated_at": "2026-06-21T00:00:00+00:00",
                "current_version": generate.parse_version("Hermes Agent v0.17.0 (2026.6.19)"),
                "latest_release": {}, "reachable_releases": []}

    def _assert_no_recovery(self, state, before_baseline, before_markers, before_history_len, warn_substr):
        # warn-only: nothing mutated
        self.assertEqual(len(state["history"]), before_history_len)
        self.assertEqual(state["baseline_commit"], before_baseline)
        self.assertEqual(state["review_markers"], before_markers)
        self.assertIn(warn_substr, state.get("checkpoint_warning", "").lower())

    def test_head_not_on_origin_main_lineage_warns_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-trust-branch-") as tmp:
            r = self.make_trust_repo(Path(tmp) / "hermes-agent")
            generate = self.load_generate_with_root(Path(tmp) / "runtime", Path(tmp) / "hermes-agent")
            # baseline=B, HEAD=A (local side branch), origin/main=C
            state = {"baseline_commit": r["B"], "baseline_label": "Hermes Agent v0.16.0 (2026.6.5)",
                     "review_markers": [{"id": "m"}], "history": []}
            generate.archive_if_head_advanced(state, self._diverge_data(generate, r["A"], r["C"]))
            self._assert_no_recovery(state, r["B"], [{"id": "m"}], 0, "not on the trusted origin/main lineage")

    def test_detached_local_commit_not_on_origin_main_warns_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-trust-detached-") as tmp:
            r = self.make_trust_repo(Path(tmp) / "hermes-agent")
            generate = self.load_generate_with_root(Path(tmp) / "runtime", Path(tmp) / "hermes-agent")
            # HEAD=A is a local commit not reachable from origin/main=C; baseline=C
            state = {"baseline_commit": r["C"], "baseline_label": "Hermes Agent v0.17.0 (2026.6.19)",
                     "review_markers": [], "history": []}
            generate.archive_if_head_advanced(state, self._diverge_data(generate, r["A"], r["C"]))
            self._assert_no_recovery(state, r["C"], [], 0, "not on the trusted origin/main lineage")

    def test_missing_baseline_warns_only_no_count0_gap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-trust-missing-") as tmp:
            r = self.make_trust_repo(Path(tmp) / "hermes-agent")
            generate = self.load_generate_with_root(Path(tmp) / "runtime", Path(tmp) / "hermes-agent")
            missing = "0" * 40
            state = {"baseline_commit": missing, "baseline_label": "Hermes Agent v0.14.0 (2026.5.16)",
                     "review_markers": [{"id": "m"}], "history": []}
            generate.archive_if_head_advanced(state, self._diverge_data(generate, r["C"], r["C"]))
            self._assert_no_recovery(state, missing, [{"id": "m"}], 0, "could not be resolved")
            self.assertFalse(any(h.get("kind") == "gap" for h in state["history"]))

    def test_unrelated_histories_empty_merge_base_warns_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-trust-orphan-") as tmp:
            r = self.make_trust_repo(Path(tmp) / "hermes-agent")
            generate = self.load_generate_with_root(Path(tmp) / "runtime", Path(tmp) / "hermes-agent")
            # baseline=orphan (no common ancestor with C); HEAD=C==origin/main (trusted)
            state = {"baseline_commit": r["orphan"], "baseline_label": "Checkpoint orphan",
                     "review_markers": [{"id": "m"}], "history": []}
            generate.archive_if_head_advanced(state, self._diverge_data(generate, r["C"], r["C"]))
            self._assert_no_recovery(state, r["orphan"], [{"id": "m"}], 0, "no common ancestor")

    def test_origin_main_unavailable_warns_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-trust-noupstream-") as tmp:
            r = self.make_trust_repo(Path(tmp) / "hermes-agent")
            generate = self.load_generate_with_root(Path(tmp) / "runtime", Path(tmp) / "hermes-agent")
            # genuine divergence baseline=A vs HEAD=C, but origin/main cannot be resolved
            state = {"baseline_commit": r["A"], "baseline_label": "Hermes Agent v0.14.0 (2026.5.16)",
                     "review_markers": [{"id": "m"}], "history": []}
            generate.archive_if_head_advanced(state, self._diverge_data(generate, r["C"], ""))
            self._assert_no_recovery(state, r["A"], [{"id": "m"}], 0, "origin/main")

    def test_verified_divergence_with_real_repo_records_gap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-radar-trust-ok-") as tmp:
            r = self.make_trust_repo(Path(tmp) / "hermes-agent")
            generate = self.load_generate_with_root(Path(tmp) / "runtime", Path(tmp) / "hermes-agent")
            # baseline=A diverged; HEAD=C==origin/main; merge-base=base => trusted recovery
            state = {"baseline_commit": r["A"], "baseline_label": "Hermes Agent v0.14.0 (2026.5.16)",
                     "review_markers": [{"id": "m"}], "history": []}
            generate.archive_if_head_advanced(state, self._diverge_data(generate, r["C"], r["C"]))
            self.assertEqual(len(state["history"]), 1)
            self.assertEqual(state["history"][0].get("kind"), "gap")
            self.assertEqual(state["history"][0]["merge_base"], r["base"])
            self.assertEqual(state["baseline_commit"], r["C"])
            self.assertEqual(state["review_markers"], [])
            self.assertNotIn("checkpoint_warning", state)


if __name__ == "__main__":
    unittest.main()
