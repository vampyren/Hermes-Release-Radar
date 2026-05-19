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
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("RELEASE_RADAR_ROOT", Path.home() / ".hermes" / "release-radar")).expanduser()
REPO = Path(os.environ.get("RELEASE_RADAR_HERMES_REPO", Path.home() / ".hermes" / "hermes-agent")).expanduser()
GENERATE = ROOT / "generate.py"
STATE_PATH = ROOT / "state.json"
HOST = os.environ.get("RELEASE_RADAR_HOST", "127.0.0.1")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_STATIC = {"/", "/index.html", "/history.html", "/help.html"}
try:
    PORT = int(os.environ.get("RELEASE_RADAR_PORT", "8765"))
except ValueError as exc:
    raise RuntimeError("RELEASE_RADAR_PORT must be an integer") from exc


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"schema": 2, "hermes_repo": str(REPO), "review_markers": []}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = STATE_PATH.with_suffix(".json.corrupt")
        STATE_PATH.replace(backup)
        return {
            "schema": 2,
            "hermes_repo": str(REPO),
            "review_markers": [],
            "state_warning": f"Previous state.json was corrupt and moved to {backup}",
        }
    state.setdefault("schema", 2)
    state.setdefault("review_markers", [])
    return state


def save_state(state: dict) -> None:
    state["schema"] = max(int(state.get("schema", 1)), 2)
    state["hermes_repo"] = str(REPO)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=STATE_PATH.parent, prefix=f"{STATE_PATH.name}.", suffix=".tmp", delete=False) as fh:
        tmp = Path(fh.name)
        json.dump(state, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


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
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

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
