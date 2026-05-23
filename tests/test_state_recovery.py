#!/usr/bin/env python3
"""State-file regression tests for generator/helper state handling."""
from __future__ import annotations

import importlib
import json
import os
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


if __name__ == "__main__":
    unittest.main()
