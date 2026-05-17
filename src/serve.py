#!/usr/bin/env python3
"""Tiny local-only helper for Hermes Release Radar.

Serves the static page and lets the page request safe server-side actions.
Allowed actions:
- status check
- git fetch origin --quiet
- regenerate index.html from generate.py
- persist review markers in state.json

It does NOT run hermes update, install packages, restart services, reset, stash,
or modify the Hermes checkout.
"""
from __future__ import annotations

import http.server
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = Path.home() / ".hermes" / "hermes-agent"
GENERATE = ROOT / "generate.py"
STATE_PATH = ROOT / "state.json"
HOST = "127.0.0.1"
PORT = 8765


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"schema": 1, "hermes_repo": str(REPO), "review_markers": []}


def save_state(state: dict) -> None:
    state.setdefault("schema", 1)
    state["hermes_repo"] = str(REPO)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def regenerate(refresh: bool = False) -> str:
    env = os.environ.copy()
    if refresh:
        env["RELEASE_RADAR_REFRESH"] = "1"
    out = subprocess.run(
        ["python3", str(GENERATE)],
        cwd=str(ROOT),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
        env=env,
    )
    return out.stdout.strip()


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "HermesReleaseRadar/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        # Allows a file:// copy of index.html to still check/call the local helper.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            state = load_state()
            return self._json(200, {
                "ok": True,
                "service": "hermes-release-radar",
                "host": HOST,
                "port": PORT,
                "repo": str(REPO),
                "state_path": str(STATE_PATH),
                "index_path": str(ROOT / "index.html"),
                "last_generated_at": state.get("last_generated_at"),
                "marker_count": len(state.get("review_markers", [])),
            })
        if self.path == "/api/state":
            return self._json(200, {"ok": True, "state": load_state()})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/refresh":
            try:
                subprocess.run(
                    ["git", "fetch", "origin", "--quiet"],
                    cwd=str(REPO),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=120,
                )
                output = regenerate(refresh=True)
                return self._json(200, {"ok": True, "message": "Release Radar refreshed", "output": output})
            except subprocess.CalledProcessError as e:
                return self._json(500, {"ok": False, "error": e.stdout or str(e)})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if self.path == "/api/markers":
            try:
                payload = self._read_json_body()
                markers = payload.get("review_markers")
                if not isinstance(markers, list):
                    return self._json(400, {"ok": False, "error": "review_markers must be a list"})
                state = load_state()
                state["review_markers"] = markers
                save_state(state)
                output = regenerate()
                return self._json(200, {"ok": True, "message": "Markers saved", "output": output})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        return self._json(404, {"ok": False, "error": "not found"})


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hermes Release Radar local helper: http://{HOST}:{PORT}/")
    print("Local-only. Do not expose publicly without auth.")
    server.serve_forever()
