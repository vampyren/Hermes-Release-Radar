#!/usr/bin/env python3
"""Security regression tests for the local Release Radar helper."""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
import serve  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class HelperServer:
    def __init__(self, *, create_index: bool = True) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="release-radar-helper-test-")
        self.root = Path(self.tmp.name)
        self.port = free_port()
        if create_index:
            (self.root / "index.html").write_text("index", encoding="utf-8")
        (self.root / "history.html").write_text("history", encoding="utf-8")
        (self.root / "help.html").write_text("help", encoding="utf-8")
        (self.root / "state.json").write_text(json.dumps({"schema": 2, "review_markers": []}), encoding="utf-8")
        (self.root / "runs").mkdir()
        (self.root / "runs" / "snapshot.json").write_text("{}", encoding="utf-8")
        (self.root / "serve.py").write_text("secret", encoding="utf-8")
        (self.root / "generate.py").write_text("#!/usr/bin/env python3\nprint('generated')\n", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "RELEASE_RADAR_ROOT": str(self.root),
            "RELEASE_RADAR_HERMES_REPO": str(REPO_ROOT),
            "RELEASE_RADAR_HOST": "127.0.0.1",
            "RELEASE_RADAR_PORT": str(self.port),
        })
        self.proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "src" / "serve.py")],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.time() + 5
        last = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"helper exited early: {out}")
            try:
                with urlopen(f"http://127.0.0.1:{self.port}/api/status", timeout=0.5) as response:
                    response.read()
                    return
            except Exception as exc:  # noqa: BLE001 - startup polling
                last = exc
                time.sleep(0.05)
        raise RuntimeError(f"helper did not start: {last}")

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self.proc.stdout:
            self.proc.stdout.close()
        self.tmp.cleanup()


class HelperSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HelperServer()
        cls.base = f"http://127.0.0.1:{cls.server.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.close()

    def get(self, path: str):
        return urlopen(self.base + path, timeout=5)

    def post_markers(self, markers) -> tuple[int, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        body = json.dumps({"review_markers": markers})
        conn.putrequest("POST", "/api/markers", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{self.server.port}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body.encode("utf-8"))
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        status = response.status
        conn.close()
        return status, payload

    def test_responses_do_not_allow_wildcard_cors(self) -> None:
        req = Request(self.base + "/api/status", headers={"Origin": "https://evil.example"})
        with urlopen(req, timeout=5) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_static_serving_is_whitelisted(self) -> None:
        with self.get("/index.html") as response:
            self.assertEqual(response.status, 200)
        for blocked in ("/state.json", "/runs/snapshot.json", "/serve.py"):
            with self.subTest(path=blocked):
                with self.assertRaises(HTTPError) as ctx:
                    self.get(blocked)
                ctx.exception.close()
                self.assertEqual(ctx.exception.code, 404)

    def test_directory_listing_is_disabled_before_first_generation(self) -> None:
        server = HelperServer(create_index=False)
        try:
            with self.assertRaises(HTTPError) as ctx:
                urlopen(f"http://127.0.0.1:{server.port}/", timeout=5)
            ctx.exception.close()
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.close()

    def test_api_state_rejects_hostile_origin(self) -> None:
        req = Request(self.base + "/api/state", headers={"Origin": "https://evil.example"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=5)
        ctx.exception.close()
        self.assertEqual(ctx.exception.code, 403)

    def test_api_state_rejects_non_local_host(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.putrequest("GET", "/api/state", skip_host=True)
        conn.putheader("Host", "evil.example")
        conn.endheaders()
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        conn.close()
        self.assertEqual(response.status, 403, payload)

    def test_api_state_allows_normal_local_request(self) -> None:
        with self.get("/api/state") as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["state"]["review_markers"], [])

    def test_state_changing_posts_reject_non_local_host(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        body = json.dumps({"review_markers": []})
        conn.putrequest("POST", "/api/markers", skip_host=True)
        conn.putheader("Host", "evil.example")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body.encode("utf-8"))
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        conn.close()
        self.assertEqual(response.status, 403, payload)

    def test_marker_body_size_is_capped(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.putrequest("POST", "/api/markers", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{self.server.port}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(serve.MAX_JSON_BODY_BYTES + 1))
        conn.endheaders()
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        conn.close()
        self.assertEqual(response.status, 400, payload)
        self.assertIn("too large", payload)

    def test_marker_validation_rejects_malformed_marker(self) -> None:
        status, payload = self.post_markers([{"id": "one", "commit": "not-a-hash", "target_id": "cat-Test"}])
        self.assertEqual(status, 400, payload)
        self.assertIn("commit", payload)

    def test_marker_validation_rejects_non_list(self) -> None:
        status, payload = self.post_markers({"id": "not-a-list"})
        self.assertEqual(status, 400, payload)
        self.assertIn("must be a list", payload)

    def test_marker_validation_rejects_too_many_markers(self) -> None:
        status, payload = self.post_markers([{} for _ in range(serve.MAX_REVIEW_MARKERS + 1)])
        self.assertEqual(status, 400, payload)
        self.assertIn("at most", payload)

    def test_marker_validation_rejects_non_dict_marker(self) -> None:
        status, payload = self.post_markers(["not-an-object"])
        self.assertEqual(status, 400, payload)
        self.assertIn("must be an object", payload)

    def test_marker_validation_rejects_huge_label(self) -> None:
        status, payload = self.post_markers([{"label": "x" * (serve.MAX_MARKER_FIELD_CHARS + 1)}])
        self.assertEqual(status, 400, payload)
        self.assertIn("label is too long", payload)

    def test_marker_validation_rejects_unknown_fields(self) -> None:
        status, payload = self.post_markers([{"id": "one", "unexpected": "nope"}])
        self.assertEqual(status, 400, payload)
        self.assertIn("unsupported fields", payload)

    def test_marker_validation_accepts_valid_marker(self) -> None:
        marker = {
            "id": "one",
            "label": "Docs reviewed",
            "commit": "abcdef1",
            "target_id": "cat-docs",
            "created_at": "2026-05-19T12:00:00+02:00",
        }
        status, payload = self.post_markers([marker])
        self.assertEqual(status, 200, payload)
        saved = json.loads((self.server.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["review_markers"], [marker])

    def test_local_request_guard_checks_peer_address(self) -> None:
        fake = serve.Handler.__new__(serve.Handler)
        fake.headers = {"Host": "127.0.0.1"}
        fake.client_address = ("192.0.2.10", 4567)

        self.assertFalse(fake._is_local_request())


if __name__ == "__main__":
    unittest.main()
