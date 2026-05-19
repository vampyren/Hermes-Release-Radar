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
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path

from state import load_state_file, save_state_file

ROOT = Path(os.environ.get("RELEASE_RADAR_ROOT", Path.home() / ".hermes" / "release-radar")).expanduser()
REPO = Path(os.environ.get("RELEASE_RADAR_HERMES_REPO", Path.home() / ".hermes" / "hermes-agent")).expanduser()
GENERATE = ROOT / "generate.py"
STATE_PATH = ROOT / "state.json"
HOST = os.environ.get("RELEASE_RADAR_HOST", "127.0.0.1")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_STATIC = {"/", "/index.html", "/history.html", "/help.html"}
MAX_JSON_BODY_BYTES = 64 * 1024
MAX_REVIEW_MARKERS = 200
MAX_MARKER_FIELD_CHARS = 512
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
TARGET_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
try:
    PORT = int(os.environ.get("RELEASE_RADAR_PORT", "8765"))
except ValueError as exc:
    raise RuntimeError("RELEASE_RADAR_PORT must be an integer") from exc


def load_state() -> dict:
    return load_state_file(STATE_PATH, REPO, default_state)


def default_state() -> dict:
    return {
        "schema": 2,
        "hermes_repo": str(REPO),
        "baseline_commit": "",
        "baseline_label": "Waiting for Hermes checkout",
        "review_markers": [],
        "history": [],
    }


def save_state(state: dict) -> None:
    save_state_file(STATE_PATH, REPO, state)


def validate_markers(markers: object) -> list[dict]:
    if not isinstance(markers, list):
        raise ValueError("review_markers must be a list")
    if len(markers) > MAX_REVIEW_MARKERS:
        raise ValueError(f"review_markers must contain at most {MAX_REVIEW_MARKERS} entries")
    cleaned: list[dict] = []
    for index, marker in enumerate(markers):
        if not isinstance(marker, dict):
            raise ValueError(f"review_markers[{index}] must be an object")
        unexpected = sorted(set(marker) - {"id", "label", "commit", "target_id", "created_at"})
        if unexpected:
            raise ValueError(f"review_markers[{index}] has unsupported fields: {', '.join(unexpected)}")
        cleaned_marker: dict[str, str] = {}
        for key in ("id", "label", "commit", "target_id", "created_at"):
            value = marker.get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise ValueError(f"review_markers[{index}].{key} must be a string")
            value = value.strip()
            if len(value) > MAX_MARKER_FIELD_CHARS:
                raise ValueError(f"review_markers[{index}].{key} is too long")
            cleaned_marker[key] = value
        if cleaned_marker["commit"] and not COMMIT_RE.match(cleaned_marker["commit"]):
            raise ValueError(f"review_markers[{index}].commit must be a git commit hash")
        if cleaned_marker["target_id"] and not TARGET_RE.match(cleaned_marker["target_id"]):
            raise ValueError(f"review_markers[{index}].target_id contains invalid characters")
        cleaned.append(cleaned_marker)
    return cleaned


def regenerate(refresh: bool = False) -> str:
    env = os.environ.copy()
    env["RELEASE_RADAR_ROOT"] = str(ROOT)
    env["RELEASE_RADAR_HERMES_REPO"] = str(REPO)
    env["RELEASE_RADAR_HOST"] = HOST
    env["RELEASE_RADAR_PORT"] = str(PORT)
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
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _host_value(self, header_name: str) -> str:
        value = self.headers.get(header_name) or ""
        if header_name.lower() == "origin" and "://" in value:
            from urllib.parse import urlparse
            value = urlparse(value).hostname or ""
        elif value.startswith("[") and "]" in value:
            value = value[1:value.index("]")]
        else:
            value = value.split(":", 1)[0]
        return value.strip().lower()

    def _is_local_request(self) -> bool:
        host = self._host_value("Host")
        origin = self._host_value("Origin")
        peer = self.client_address[0] if self.client_address else ""
        try:
            peer_is_loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            peer_is_loopback = peer in LOCAL_HOSTS
        return peer_is_loopback and host in LOCAL_HOSTS and (not origin or origin in LOCAL_HOSTS)

    def _is_allowed_static(self) -> bool:
        path = self.path.split("?", 1)[0]
        return path in ALLOWED_STATIC

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
        if length > MAX_JSON_BODY_BYTES:
            raise ValueError(f"JSON body is too large; limit is {MAX_JSON_BODY_BYTES} bytes")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def list_directory(self, path):
        self.send_error(404, "Directory listing is disabled")
        return None

    def do_OPTIONS(self):
        return self._json(403, {"ok": False, "error": "CORS preflight is not supported; use the local helper page"})

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
            if not self._is_local_request():
                return self._json(403, {"ok": False, "error": "local requests only"})
            return self._json(200, {"ok": True, "state": load_state()})
        if not self._is_allowed_static():
            return self._json(404, {"ok": False, "error": "not found"})
        return super().do_GET()

    def do_POST(self):
        if not self._is_local_request():
            return self._json(403, {"ok": False, "error": "local requests only"})

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
                markers = validate_markers(payload.get("review_markers"))
                state = load_state()
                state["review_markers"] = markers
                save_state(state)
                output = regenerate()
                return self._json(200, {"ok": True, "message": "Markers saved", "output": output})
            except ValueError as e:
                return self._json(400, {"ok": False, "error": str(e)})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        return self._json(404, {"ok": False, "error": "not found"})


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hermes Release Radar local helper: http://{HOST}:{PORT}/")
    print("Local-only. Do not expose publicly without auth.")
    server.serve_forever()
