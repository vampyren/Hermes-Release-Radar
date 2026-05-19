#!/usr/bin/env python3
"""Safe smoke test for Hermes Release Radar.

This script verifies the repository files, generator, optional installed runtime,
and local helper health. It never updates Hermes, fetches upstream, restarts
services, installs packages, or mutates the Hermes checkout.
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass
class Check:
    level: str
    name: str
    detail: str = ""


class Reporter:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.checks.append(Check("ok", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.checks.append(Check("warn", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.checks.append(Check("fail", name, detail))

    @property
    def failed(self) -> bool:
        return any(c.level == "fail" for c in self.checks)

    def print(self) -> None:
        print("Hermes Release Radar smoke test")
        for check in self.checks:
            suffix = f" — {check.detail}" if check.detail else ""
            print(f"[{check.level}] {check.name}{suffix}")
        print(f"Result: {'FAIL' if self.failed else 'PASS'}")


def env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def run(args: list[str], *, cwd: Path, timeout: int = 120, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def git_output(repo: Path, args: list[str], timeout: int = 60) -> tuple[int, str]:
    result = run(["git", *args], cwd=repo, timeout=timeout)
    return result.returncode, result.stdout.strip()


def check_repo_files(report: Reporter, repo_root: Path) -> None:
    required = [
        "src/generate.py",
        "src/serve.py",
        "scripts/render_help.py",
        "scripts/smoke_test.py",
        "HELP.md",
        "README.md",
        "systemd/hermes-release-radar.service",
    ]
    missing = [rel for rel in required if not (repo_root / rel).is_file()]
    if missing:
        report.fail("repo files present", "missing: " + ", ".join(missing))
    else:
        report.ok("repo files present", str(repo_root))


def check_python_compile(report: Reporter, repo_root: Path) -> None:
    files = [repo_root / "src/generate.py", repo_root / "src/serve.py", repo_root / "scripts/render_help.py", repo_root / "scripts/smoke_test.py"]
    failures: list[str] = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path.relative_to(repo_root)}: {exc.msg}")
    if failures:
        report.fail("python syntax valid", "; ".join(failures))
    else:
        report.ok("python syntax valid", ", ".join(str(p.relative_to(repo_root)) for p in files))


def check_hermes_repo(report: Reporter, hermes_repo: Path) -> bool:
    if not hermes_repo.exists():
        report.fail("Hermes checkout exists", str(hermes_repo))
        return False
    code, inside = git_output(hermes_repo, ["rev-parse", "--is-inside-work-tree"])
    if code != 0 or inside != "true":
        report.fail("Hermes checkout is a git repo", str(hermes_repo))
        return False
    code, head = git_output(hermes_repo, ["rev-parse", "--short", "HEAD"])
    if code == 0:
        report.ok("Hermes checkout readable", f"{hermes_repo} @ {head}")
        return True
    report.fail("Hermes checkout HEAD readable", head)
    return False


def check_temp_generation(report: Reporter, repo_root: Path, hermes_repo: Path, host: str, port: int) -> None:
    with tempfile.TemporaryDirectory(prefix="release-radar-smoke-") as tmp:
        temp_root = Path(tmp)
        env = os.environ.copy()
        env.update({
            "RELEASE_RADAR_ROOT": str(temp_root),
            "RELEASE_RADAR_HERMES_REPO": str(hermes_repo),
            "RELEASE_RADAR_HOST": host,
            "RELEASE_RADAR_PORT": str(port),
        })
        result = run([sys.executable, str(repo_root / "src/generate.py")], cwd=repo_root, timeout=180, env=env)
        if result.returncode != 0:
            report.fail("temp-root generation succeeded", result.stdout.strip()[-500:])
            return
        index_path = temp_root / "index.html"
        state_path = temp_root / "state.json"
        runs_dir = temp_root / "runs"
        if not index_path.is_file() or not state_path.is_file() or not runs_dir.is_dir():
            report.fail("temp-root artifacts created", f"root={temp_root}")
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.fail("temp-root state.json readable", str(exc))
            return
        expected = ["schema", "hermes_repo", "baseline_commit", "review_markers", "history", "last_generated_at"]
        missing = [key for key in expected if key not in state]
        if missing:
            report.fail("temp-root state fields valid", "missing: " + ", ".join(missing))
        else:
            report.ok("temp-root generation succeeded", f"index={index_path.name}, state schema={state.get('schema')}")
        check_generated_ui_contract(report, temp_root)


def check_missing_checkout_generation(report: Reporter, repo_root: Path, host: str, port: int) -> None:
    """Verify first-run UX when the configured Hermes checkout is missing."""
    with tempfile.TemporaryDirectory(prefix="release-radar-missing-checkout-") as tmp:
        temp_root = Path(tmp) / "runtime"
        missing_repo = Path(tmp) / "missing-hermes-agent"
        env = os.environ.copy()
        env.update({
            "RELEASE_RADAR_ROOT": str(temp_root),
            "RELEASE_RADAR_HERMES_REPO": str(missing_repo),
            "RELEASE_RADAR_HOST": host,
            "RELEASE_RADAR_PORT": str(port),
        })
        result = run([sys.executable, str(repo_root / "src/generate.py")], cwd=repo_root, timeout=180, env=env)
        if result.returncode != 0:
            report.fail("missing-checkout first-run page generated", result.stdout.strip()[-500:])
            return
        index_path = temp_root / "index.html"
        state_path = temp_root / "state.json"
        if not index_path.is_file() or not state_path.is_file():
            report.fail("missing-checkout first-run artifacts created", f"root={temp_root}")
            return
        html_text = index_path.read_text(encoding="utf-8")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        needles = ["Hermes checkout not found", "RELEASE_RADAR_HERMES_REPO", "Waiting for Hermes checkout", "will not run <code>hermes update</code>"]
        missing = [needle for needle in needles if needle not in html_text and needle not in json.dumps(state)]
        if missing:
            report.fail("missing-checkout first-run UX present", "missing: " + ", ".join(missing))
            return
        report.ok("missing-checkout first-run UX present", "clear setup guidance without touching Hermes")


def check_generated_ui_contract(report: Reporter, temp_root: Path) -> None:
    """Guard the core Release Radar UI semantics against regressions."""
    index_path = temp_root / "index.html"
    runs = sorted((temp_root / "runs").glob("*.json"))
    if not runs or not index_path.is_file():
        report.fail("generated UI contract checked", "missing index.html or run snapshot")
        return
    html_text = index_path.read_text(encoding="utf-8")
    data = json.loads(runs[-1].read_text(encoding="utf-8"))
    behind = int(data.get("behind") or 0)
    recent = data.get("recent_commits") or []
    if len(recent) != behind:
        report.fail("raw commits match behind range", f"behind={behind}, rendered-source commits={len(recent)}")
    else:
        report.ok("raw commits match behind range", f"{behind} unique pending commit(s)")
    category_total = sum(int(v or 0) for v in (data.get("category_counts") or {}).values())
    if category_total != behind:
        report.fail("category counts sum to unique pending range", f"behind={behind}, category_total={category_total}")
    else:
        report.ok("category counts sum to unique pending range", f"{category_total} primary-category commit(s)")
    contracts = {
        "refresh controls stay below helper text": [".helperbar{display:grid;grid-template-columns:1fr", ".helper-actions", "justify-content:flex-start", "Refreshing: git fetch origin"],
        "category counts are unique primary-category commits": ["unique pending commit(s)", "primary category", "visible category total matches", "jump-unit"],
        "refresh preserves active tab": ["function activeTabHash()", "const activeHash = activeTabHash()", "name.startsWith('cat-')"],
        "matters cards use representative pending commits": ["Representative commits:", "Representative commit date"],
    }
    failures = []
    for name, needles in contracts.items():
        missing = [needle for needle in needles if needle not in html_text]
        if missing:
            failures.append(f"{name}: missing {', '.join(missing)}")
    if failures:
        report.fail("generated UI contract checked", "; ".join(failures))
    else:
        report.ok("generated UI contract checked", "layout/count/tab/#matters guards present")


def check_runtime(report: Reporter, runtime_root: Path) -> None:
    expected = ["index.html", "state.json", "generate.py", "serve.py"]
    missing = [name for name in expected if not (runtime_root / name).is_file()]
    if missing:
        report.warn("installed runtime files present", f"missing under {runtime_root}: " + ", ".join(missing))
        return
    try:
        state = json.loads((runtime_root / "state.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.fail("installed state.json readable", str(exc))
        return
    report.ok("installed runtime files present", str(runtime_root))
    report.ok("installed state.json readable", f"schema={state.get('schema')}, markers={len(state.get('review_markers', []))}")


def helper_status_url(host: str, port: int) -> str:
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{bracketed}:{port}/api/status"


def check_helper_api(report: Reporter, host: str, port: int) -> None:
    if host not in LOCAL_HOSTS:
        report.fail("configured helper host is local-only", host)
        return
    url = helper_status_url(host, port)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        report.warn("helper API reachable", f"{url} ({exc})")
        return
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        report.fail("helper API returns JSON", str(exc))
        return
    if payload.get("ok") is not True:
        report.fail("helper API reports ok", body[:300])
        return
    api_host = str(payload.get("host", ""))
    if api_host not in LOCAL_HOSTS:
        report.fail("helper API reports local-only bind", api_host)
        return
    report.ok("helper API reachable", url)
    report.ok("helper is local-only", f"host={api_host}, port={payload.get('port')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a safe smoke test for Hermes Release Radar.")
    parser.add_argument("--hermes-repo", type=Path, default=env_path("RELEASE_RADAR_HERMES_REPO", Path.home() / ".hermes" / "hermes-agent"))
    parser.add_argument("--runtime-root", type=Path, default=env_path("RELEASE_RADAR_ROOT", Path.home() / ".hermes" / "release-radar"))
    parser.add_argument("--host", default=os.environ.get("RELEASE_RADAR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RELEASE_RADAR_PORT", "8765")))
    parser.add_argument("--skip-helper", action="store_true", help="Do not call the local helper API.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    hermes_repo = args.hermes_repo.expanduser().resolve()
    runtime_root = args.runtime_root.expanduser().resolve()
    report = Reporter()

    if shutil.which("git"):
        report.ok("git available", shutil.which("git") or "git")
    else:
        report.fail("git available")

    check_repo_files(report, repo_root)
    check_python_compile(report, repo_root)
    hermes_ok = check_hermes_repo(report, hermes_repo)
    if hermes_ok:
        check_temp_generation(report, repo_root, hermes_repo, args.host, args.port)
    check_missing_checkout_generation(report, repo_root, args.host, args.port)
    check_runtime(report, runtime_root)
    if args.skip_helper:
        report.warn("helper API reachable", "skipped by --skip-helper")
    else:
        check_helper_api(report, args.host, args.port)

    report.print()
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
