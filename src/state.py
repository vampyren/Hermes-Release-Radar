#!/usr/bin/env python3
"""Shared state-file helpers for Hermes Release Radar."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


def recover_corrupt_state(state_path: Path) -> Path:
    """Move a corrupt state file aside without overwriting older backups."""
    backup = state_path.with_suffix(".json.corrupt")
    if backup.exists():
        idx = 1
        while True:
            candidate = state_path.with_suffix(f".json.corrupt.{idx}")
            if not candidate.exists():
                backup = candidate
                break
            idx += 1
    state_path.replace(backup)
    return backup


def load_state_file(
    state_path: Path,
    repo: Path,
    default_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Load state.json, recovering corrupt JSON to a backup file."""
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = recover_corrupt_state(state_path)
            state = default_factory()
            state["state_warning"] = f"Previous state.json was corrupt and moved to {backup}"
    else:
        state = default_factory()
    state.setdefault("schema", 2)
    state.setdefault("hermes_repo", str(repo))
    state.setdefault("review_markers", [])
    state.setdefault("history", [])
    return state


def save_state_file(state_path: Path, repo: Path, state: dict[str, Any]) -> None:
    """Write state.json atomically and remove orphan temp files on failure."""
    state["schema"] = max(int(state.get("schema", 1)), 2)
    state["hermes_repo"] = str(repo)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix=f"{state_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp = Path(fh.name)
            json.dump(state, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, state_path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
