#!/usr/bin/env python3
"""Generate local Hermes Release Radar pages.
Safe by design: read-only git inspection plus optional GitHub release-note reads.
It never runs hermes update, installs packages, restarts services, resets, stashes,
or modifies the Hermes source checkout.
"""
from __future__ import annotations

import datetime
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from state import load_state_file, save_state_file

def env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if not value:
        return default
    return Path(value).expanduser()


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


ROOT = env_path("RELEASE_RADAR_ROOT", Path.home() / ".hermes" / "release-radar")
REPO = env_path("RELEASE_RADAR_HERMES_REPO", Path.home() / ".hermes" / "hermes-agent")
HELPER_HOST = os.environ.get("RELEASE_RADAR_HOST", "127.0.0.1")
HELPER_PORT = env_int("RELEASE_RADAR_PORT", 8765)
STATE_PATH = ROOT / "state.json"
HTML_PATH = ROOT / "index.html"
HISTORY_PATH = ROOT / "history.html"
RUNS = ROOT / "runs"
GITHUB_RELEASES_API = "https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=8"
APP_ICON_SVG = """<svg class="app-icon" viewBox="0 0 48 48" role="img" aria-label="Hermes Release Radar icon" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="radar-g" x1="8" y1="6" x2="40" y2="42" gradientUnits="userSpaceOnUse"><stop stop-color="#7ff6d7"/><stop offset="1" stop-color="#7aa7ff"/></linearGradient></defs><circle cx="24" cy="24" r="21" fill="#0b1419" stroke="url(#radar-g)" stroke-width="2.5"/><path d="M24 24 36.8 12.8" stroke="#7ff6d7" stroke-width="3" stroke-linecap="round"/><path d="M14 25a10 10 0 0 1 20 0M9.5 25a14.5 14.5 0 0 1 29 0" fill="none" stroke="#315a7e" stroke-width="2" stroke-linecap="round"/><circle cx="24" cy="24" r="4.2" fill="#62e6c8"/><circle cx="36.8" cy="12.8" r="3.2" fill="#ffc857"/></svg>"""
FAVICON_DATA = urllib.parse.quote(APP_ICON_SVG.replace(' class="app-icon"', ''), safe="")
# Small inline chevron icons (currentColor) for the category disclosure caret and
# the Expand all / Collapse all bulk buttons.
CHEVRON_RIGHT_SVG = '<svg class="ico" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>'
CHEVRON_DOWN_SVG = '<svg class="ico" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
CHEVRON_UP_SVG = '<svg class="ico" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg>'
GIT_WARNINGS: list[str] = []


def read_app_version() -> str:
    """Return the Release Radar app version (this tool's version, not Hermes Agent).

    Reads the VERSION file so the top-bar badge has a single source of truth.
    Candidates are ordered to prefer the VERSION file co-located with the running
    code, so the badge reflects the version that actually generated the page:
    1. here.parent/VERSION        — installed runtime (generate.py + VERSION live
                                     together in RELEASE_RADAR_ROOT)
    2. here.parent.parent/VERSION — direct repo run (VERSION sits above src/)
    3. ROOT/VERSION               — fallback only
    ROOT is last so a stale RELEASE_RADAR_ROOT/VERSION cannot shadow the repo
    VERSION during a repo run. In the installed runtime here.parent == ROOT, so
    those paths overlap; dedupe to avoid reading the same file twice. Returns ""
    if no VERSION file is found so the badge degrades gracefully.
    """
    here = Path(__file__).resolve()
    candidates = [here.parent / "VERSION", here.parent.parent / "VERSION", ROOT / "VERSION"]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = resolved.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text.splitlines()[0].strip()
    return ""


APP_VERSION = read_app_version()
# Display formatting only: drop the internal "-local" channel suffix from the
# user-visible badge (the raw APP_VERSION is kept for VERSION-file/source logic).
APP_VERSION_DISPLAY = APP_VERSION.removesuffix("-local")
APP_VERSION_BADGE = (
    f'<span class="app-version" title="Hermes Release Radar app version">{html.escape(APP_VERSION_DISPLAY)}</span>'
    if APP_VERSION
    else ""
)

# Shared page shell (frame) used by BOTH the current and history pages so they
# stay visually in sync: same background gradient, content width, topbar, brand,
# version badge, card, and base resets. Kept as one source of truth instead of
# duplicating near-identical wrapper styles per page. Plain CSS (single braces);
# interpolate as {SHELL_CSS} inside the page f-strings.
SHELL_CSS = (
    ":root{color-scheme:dark;--bg:#0b1014;--panel:#121a21;--text:#c7d7dc;--muted:#91a4af;--accent:#62e6c8;--warn:#ffc857;--bad:#ff6b6b;--line:#26343d;--marker:#62e6c8}"
    "*{box-sizing:border-box;min-width:0}"
    "html{scroll-behavior:smooth;overflow-x:hidden}"
    "body{margin:0;width:100%;max-width:100%;overflow-x:hidden;background:radial-gradient(circle at 15% 0,#18342f 0,#0b1014 34rem);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}"
    "main{width:100%;max-width:1180px;margin:auto;padding:18px;overflow-wrap:anywhere}"
    "a{color:#a8e9ff}"
    "code{background:#0b1419;border:1px solid var(--line);border-radius:7px;padding:2px 6px;white-space:normal;overflow-wrap:anywhere;word-break:break-word}"
    "summary{cursor:pointer}"
    "h1{font-size:clamp(24px,6vw,32px);margin:0 0 4px}"
    ".topbar{border-bottom:1px solid var(--line);background:#0b1014aa;position:sticky;top:0;z-index:2;backdrop-filter:blur(8px)}"
    ".topbar main{padding:8px 18px}"
    ".brand{display:inline-flex;align-items:center;gap:9px;font-weight:800;letter-spacing:.01em;white-space:nowrap;color:var(--text);text-decoration:none}"
    ".brand .app-icon{width:30px;height:30px;flex:0 0 auto;filter:drop-shadow(0 0 10px #62e6c833)}"
    ".brandwrap{display:inline-flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}"
    ".app-version{font-size:11px;font-weight:600;color:var(--muted);letter-spacing:.02em;white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:1px 7px;background:#0d141a}"
    ".navlinks a{margin-left:10px;text-decoration:none}"
    ".navlinks .help-icon{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border:1px solid #315a7e;border-radius:999px;background:#102239;color:#d9ecff;font-weight:900;line-height:1}"
    ".row{display:flex;gap:10px;align-items:center;justify-content:flex-start;flex-wrap:wrap}"
    ".spread{justify-content:space-between}"
    ".card,.commit{background:linear-gradient(180deg,var(--panel),#10171d);border:1px solid var(--line);border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 12px 30px #0005;width:100%;max-width:100%;overflow:hidden}"
    ".muted{color:var(--muted)}"
)


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sh(args: list[str], check: bool = True, timeout: int = 120) -> str:
    try:
        r = subprocess.run(
            args,
            cwd=str(REPO),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except FileNotFoundError:
        if check:
            raise
        return f"{args[0]} command not found"
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{r.stdout}")
    return r.stdout.strip()


def check_repo_health() -> dict[str, Any]:
    if not REPO.exists():
        return {
            "ok": False,
            "kind": "missing",
            "title": "Hermes checkout not found",
            "message": f"Release Radar expected a Hermes Agent git checkout at {REPO}.",
        }
    if not REPO.is_dir():
        return {
            "ok": False,
            "kind": "not_directory",
            "title": "Hermes checkout path is not a directory",
            "message": f"{REPO} exists, but it is not a directory.",
        }
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=str(REPO), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0 or r.stdout.strip() != "true":
        return {
            "ok": False,
            "kind": "not_git",
            "title": "Hermes checkout is not a git repo",
            "message": f"{REPO} exists, but git cannot read it as a worktree. {r.stdout.strip()}",
        }
    return {"ok": True, "kind": "ok", "title": "Hermes checkout ready", "message": str(REPO)}


def empty_collect(repo_health: dict[str, Any]) -> dict[str, Any]:
    message = repo_health.get("message") or "Hermes checkout is not available."
    return {
        "generated_at": now_iso(),
        "repo": str(REPO),
        "repo_ok": False,
        "repo_problem": repo_health,
        "version_output": message,
        "current_version": {"raw": "Hermes checkout unavailable", "version": "not configured", "date": "", "tag": ""},
        "latest_release": {},
        "reachable_releases": [],
        "release_fetch_error": "",
        "status": message,
        "head": "",
        "upstream": "",
        "behind": 0,
        "modified": [],
        "category_counts": {},
        "importance_counts": {},
        "category_commits": {},
        "recent_commits": [],
        "git_warnings": [],
    }


def default_state() -> dict[str, Any]:
    repo_health = check_repo_health()
    head = sh(["git", "rev-parse", "HEAD"]) if repo_health.get("ok") else ""
    return {
        "schema": 2,
        "hermes_repo": str(REPO),
        "baseline_commit": head,
        "baseline_label": "Initial Release Radar baseline" if head else "Waiting for Hermes checkout",
        "review_markers": [],
        "history": [],
    }


def load_state() -> dict[str, Any]:
    return load_state_file(STATE_PATH, REPO, default_state)


def save_state(state: dict[str, Any]) -> None:
    save_state_file(STATE_PATH, REPO, state)


def parse_version(text: str) -> dict[str, str]:
    first = (text or "").splitlines()[0] if text else ""
    m = re.search(r"Hermes Agent\s+(v[\w.\-]+)\s*\(([^)]+)\)", first)
    if not m:
        return {"raw": first or "unknown", "version": "unknown", "date": "unknown", "tag": ""}
    date = m.group(2)
    return {"raw": first, "version": m.group(1), "date": date, "tag": f"v{date}"}


def is_valid_checkpoint_label(label: str) -> bool:
    """Return True only for a real checkpoint label, not operational error text.

    Releases up to 0.4.4-local could persist version-detection error strings such
    as ``hermes command not found`` or ``Hermes CLI version unavailable`` into
    state.json as ``baseline_label``. Those, plus empty/``unknown`` placeholders
    and any ``command not found`` / ``unavailable`` operational text, are rejected
    so they can be migrated or replaced with a safe ``Checkpoint <shortsha>``.
    """
    text = (label or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered == "unknown":
        return False
    if "command not found" in lowered or "unavailable" in lowered:
        return False
    return True


def checkpoint_label_for(version: dict[str, Any], commit: str) -> str:
    """Pick a safe checkpoint label from a parsed version or fall back to the SHA.

    Use the raw version string only when the version actually parsed and the raw
    text is not an operational error; otherwise return ``Checkpoint <shortsha>``
    so unknown/error version output never becomes a stored checkpoint label.
    """
    raw = (version or {}).get("raw", "")
    if (version or {}).get("version", "unknown") != "unknown" and is_valid_checkpoint_label(raw):
        return raw
    return f"Checkpoint {(commit or '')[:12]}"


def migrate_baseline_label(state: dict[str, Any], data: dict[str, Any]) -> None:
    """Repair a stale/invalid persisted baseline_label without touching the commit.

    The renderer prints ``baseline_label`` verbatim in the "Current installed
    state" card, so an old bad value (for example ``hermes command not found``)
    persisted before the installed-version fallback fix stays visible even after
    the live version detection recovers. Replace an invalid label with the valid
    current version when the baseline still points at HEAD, otherwise with a
    neutral ``Checkpoint <shortsha>``. ``baseline_commit`` is never mutated here.
    """
    if is_valid_checkpoint_label(state.get("baseline_label", "")):
        return
    baseline = state.get("baseline_commit") or ""
    if not baseline:
        return
    head = data.get("head") or ""
    current_version = data.get("current_version", {}) or {}
    if (
        head
        and baseline == head
        and current_version.get("version", "unknown") != "unknown"
        and is_valid_checkpoint_label(current_version.get("raw", ""))
    ):
        state["baseline_label"] = current_version["raw"]
    else:
        state["baseline_label"] = f"Checkpoint {baseline[:12]}"


def _init_version_label(text: str) -> str:
    """Build a 'Hermes Agent v<v> (<d>)' label from hermes_cli/__init__.py contents, or ''."""
    version_match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not version_match:
        return ""
    date_match = re.search(r'^__release_date__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    version = version_match.group(1).strip()
    date = date_match.group(1).strip() if date_match else "local source"
    if not version.startswith("v"):
        version = f"v{version}"
    return f"Hermes Agent {version} ({date})"


def local_source_version_output() -> str:
    """Read the inspected Hermes checkout version without importing or executing it."""
    init_path = REPO / "hermes_cli" / "__init__.py"
    try:
        text = init_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return _init_version_label(text)


def version_label_at_commit(commit: str) -> str:
    """Read the Hermes version recorded at a specific commit, read-only.

    Uses `git show <commit>:hermes_cli/__init__.py` against the inspected checkout —
    it never checks out, fetches, or otherwise mutates the Hermes repo. Returns a
    valid 'Hermes Agent v<v> (<d>)' label, or '' when the commit/file is missing or
    the metadata does not parse into a valid version (so callers can fall back to a
    neutral checkpoint label instead of guessing).
    """
    if not commit:
        return ""
    out = sh(["git", "show", f"{commit}:hermes_cli/__init__.py"], check=False)
    if not out or out.lower().startswith("fatal:") or "command not found" in out.lower():
        return ""
    label = _init_version_label(out)
    return label if is_valid_checkpoint_label(label) else ""


def resolve_version_output() -> str:
    """Prefer the installed CLI version, but fall back to the inspected checkout.

    The systemd user service can run with a minimal PATH that does not include the
    `hermes` console script. Release Radar still has direct read access to the
    configured Hermes checkout, so the Installed card should not degrade to
    Unknown just because the CLI wrapper is unavailable.
    """
    cli_output = sh(["hermes", "--version"], check=False) or ""
    if parse_version(cli_output).get("version") != "unknown":
        return cli_output
    source_output = local_source_version_output()
    if source_output:
        return source_output
    return cli_output or "Hermes CLI version unavailable"


def is_ancestor(older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    try:
        r = subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=str(REPO),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        GIT_WARNINGS.append(f"git merge-base timed out while checking {older[:12]}..{newer[:12]}")
        return False
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    GIT_WARNINGS.append(f"git merge-base failed for {older[:12]}..{newer[:12]}: {r.stdout.strip() or f'exit {r.returncode}'}")
    return False


def merge_base(a: str, b: str) -> str:
    """Return the best common ancestor of two commits, or '' if none/unreadable.

    Read-only (`git merge-base`); never mutates the inspected checkout.
    """
    if not a or not b:
        return ""
    out = sh(["git", "merge-base", a, b], check=False)
    if not out or "fatal" in out.lower():
        return ""
    return out.splitlines()[-1].strip()


def commit_exists(commit: str) -> bool:
    """True only if the ref resolves to a real commit object in the checkout.

    Read-only and fail-closed: a missing/garbage-collected/empty ref returns False.
    """
    if not commit:
        return False
    out = sh(["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"], check=False)
    return bool(out.strip()) and "fatal" not in out.lower()


def head_is_on_upstream_lineage(head: str, upstream: str) -> bool:
    """Fail-closed trust check: True only if HEAD is on the origin/main lineage.

    HEAD is trusted when it equals origin/main or is an ancestor of it. Any missing
    ref, or a HEAD that has diverged onto a local branch/detached commit, returns
    False so automatic history recovery is never attempted off untrusted lineage.
    """
    if not head or not upstream:
        return False
    if head == upstream:
        return True
    return is_ancestor(head, upstream)


def rev_parse(ref: str) -> str:
    return sh(["git", "rev-parse", ref], check=False).splitlines()[-1].strip()


# Canonical, neutral explanation rendered for every history gap card. Rendered from
# this constant rather than a record's stored free-text note, so legacy records (which
# may assert "Upstream history was rewritten" as fact) display the accurate wording too.
GAP_EXPLANATION = (
    "Stored Release Radar baseline diverged from the current trusted origin/main lineage. "
    "This can happen after an upstream history rewrite or when an earlier checkpoint came "
    "from another lineage. Exact intermediate installed checkpoints were not recorded."
)


def classify(files: list[str], subject: str):
    s = subject.lower()
    cats, high = set(), False
    for f in files:
        if f.startswith("web/") or "/dashboard/" in f:
            cats.add("Dashboard/Web UI"); high = True
        if f.startswith("ui-tui/") or f == "cli.py" or f.startswith("hermes_cli/"):
            cats.add("CLI/TUI")
        if f.startswith("gateway/"):
            cats.add("Gateway/platforms"); high = True
        if f.startswith("cron/"):
            cats.add("Cron/automation"); high = True
        if f.startswith("tools/") or f in {"toolsets.py", "model_tools.py"}:
            cats.add("Tools/toolsets")
        if f.startswith("plugins/kanban") or "kanban" in f:
            cats.add("Kanban/multi-agent"); high = True
        if f.startswith("agent/") or f == "run_agent.py" or "provider" in f:
            cats.add("Core agent/model routing")
        if f.startswith("skills/") or f.startswith("optional-skills/"):
            cats.add("Skills")
        if f.startswith("website/") or f.startswith("docs/") or f.lower().endswith(".md"):
            cats.add("Docs")
        if f.startswith("tests/"):
            cats.add("Tests/reliability")
        if f in {"pyproject.toml", "package.json", "uv.lock", "package-lock.json"} or "install" in f:
            cats.add("Install/dependencies"); high = True
    if any(w in s for w in ["feat", "add", "dashboard", "telegram", "gateway", "cron", "kanban", "tool", "model", "provider", "voice", "tts", "stt", "update", "security", "proxy", "oauth", "windows", "pypi", "lsp", "handoff", "vision", "video", "computer_use"]):
        high = True
    if not cats:
        cats.add("Internal/other")
    importance = "High" if high else ("Low" if cats <= {"Docs"} or cats <= {"Tests/reliability"} else "Medium")
    return sorted(cats), importance


PRIMARY_CATEGORY_ORDER = [
    "Gateway/platforms",
    "Dashboard/Web UI",
    "CLI/TUI",
    "Kanban/multi-agent",
    "Core agent/model routing",
    "Tools/toolsets",
    "Cron/automation",
    "Skills",
    "Install/dependencies",
    "Docs",
    "Tests/reliability",
    "Internal/other",
]


def primary_category(categories: list[str]) -> str:
    """Pick one display bucket so visible category counts sum to unique commits."""
    category_set = set(categories)
    for cat in PRIMARY_CATEGORY_ORDER:
        if cat in category_set:
            return cat
    return categories[0] if categories else "Internal/other"


def collect_commits(rev_range: str) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int], dict[str, list[dict[str, Any]]]]:
    log = sh(["git", "log", "--date=short", "--pretty=format:%H%x1f%h%x1f%ad%x1f%s", "--name-only", rev_range], check=False)
    commits: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in log.splitlines():
        if "\x1f" in line:
            if cur:
                commits.append(cur)
            full, short, date, subject = line.split("\x1f", 3)
            cur = {"full": full, "short": short, "date": date, "subject": subject, "files": []}
        elif cur and line.strip():
            cur["files"].append(line.strip())
    if cur:
        commits.append(cur)
    for c in commits:
        c["categories"], c["importance"] = classify(c["files"], c["subject"])
        c["primary_category"] = primary_category(c["categories"])
        c["file_count"] = len(c["files"])
        c["files"] = c["files"][:10]
    cat_counts, imp_counts = Counter(), Counter()
    category_commits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in commits:
        imp_counts[c["importance"]] += 1
        cat = c["primary_category"]
        cat_counts[cat] += 1
        category_commits[cat].append({k: c[k] for k in ["short", "full", "date", "subject", "importance", "primary_category"]})
    return commits, dict(cat_counts), dict(imp_counts), dict(category_commits)


def extract_release_highlights(body: str, limit: int = 40) -> list[dict[str, str]]:
    highlights: list[dict[str, str]] = []
    in_highlights = False
    current: dict[str, str] | None = None
    for raw in (body or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            title = line.strip("# ").lower()
            if "highlight" in title:
                in_highlights = True
                continue
            if in_highlights:
                break
        if not in_highlights:
            continue
        if line.startswith("- **"):
            if current:
                highlights.append(current)
            txt = line[2:].strip()
            title = re.sub(r"^\*\*([^*]+)\*\*.*", r"\1", txt)
            desc = re.sub(r"^\*\*[^*]+\*\*\s*[—:-]*\s*", "", txt)
            current = {"title": title.strip(), "text": desc.strip()}
        elif current and line.strip() and not line.startswith("---"):
            current["text"] = (current["text"] + " " + line.strip()).strip()
    if current:
        highlights.append(current)
    return highlights[:limit]


def fetch_github_releases() -> list[dict[str, Any]]:
    try:
        req = urllib.request.Request(GITHUB_RELEASES_API, headers={"User-Agent": "hermes-release-radar"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return [{"error": str(e)}]
    clean = []
    for rel in releases:
        body = rel.get("body") or ""
        parsed_name = rel.get("name") or rel.get("tag_name") or ""
        clean.append({
            "name": parsed_name,
            "tag_name": rel.get("tag_name") or "",
            "html_url": rel.get("html_url") or "",
            "published_at": rel.get("published_at") or "",
            "body_excerpt": body[:1800],
            "highlights": extract_release_highlights(body),
        })
    return clean


def release_commit(tag: str) -> str:
    if not tag:
        return ""
    out = sh(["git", "rev-parse", f"{tag}^{{}}"], check=False)
    if "fatal:" in out.lower() or not out:
        return ""
    return out.splitlines()[-1].strip()


def releases_between(releases: list[dict[str, Any]], older: str, newer: str) -> list[dict[str, Any]]:
    found = []
    seen_tags = set()
    for rel in releases:
        tag = rel.get("tag_name") or ""
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        commit = release_commit(tag)
        if commit and is_ancestor(older, commit) and is_ancestor(commit, newer):
            item = dict(rel)
            item["commit"] = commit
            found.append(item)
    return found


def collect() -> dict[str, Any]:
    GIT_WARNINGS.clear()
    repo_health = check_repo_health()
    if not repo_health.get("ok"):
        return empty_collect(repo_health)
    version_output = resolve_version_output()
    status = sh(["git", "status", "--short", "--branch"])
    head = sh(["git", "rev-parse", "HEAD"])
    upstream = sh(["git", "rev-parse", "origin/main"])
    behind = int(sh(["git", "rev-list", "--count", "HEAD..origin/main"]) or "0")
    modified = [line for line in status.splitlines()[1:] if line.strip()]
    commits, cat_counts, imp_counts, category_commits = collect_commits("HEAD..origin/main")
    releases = fetch_github_releases()
    current_version = parse_version(version_output)
    latest_release = next((r for r in releases if not r.get("error")), {})
    reachable_releases = releases_between(releases, head, upstream) if releases and not releases[0].get("error") else []
    return {
        "generated_at": now_iso(),
        "repo": str(REPO),
        "repo_ok": True,
        "repo_problem": {},
        "version_output": version_output,
        "current_version": current_version,
        "latest_release": latest_release,
        "reachable_releases": reachable_releases,
        "release_fetch_error": releases[0].get("error") if releases and releases[0].get("error") else "",
        "status": status,
        "head": head,
        "upstream": upstream,
        "behind": behind,
        "modified": modified,
        "category_counts": cat_counts,
        "importance_counts": imp_counts,
        "category_commits": category_commits,
        "recent_commits": commits,
        "git_warnings": GIT_WARNINGS,
    }


def select_commits(data: dict[str, Any], needles: list[str], cats: list[str] | None = None, limit: int = 8) -> list[dict[str, Any]]:
    hits, seen = [], set()
    for c in data.get("recent_commits", []):
        subject = c.get("subject", "").lower()
        categories = set(c.get("categories", []))
        text_hit = any(n in subject for n in needles)
        cat_hit = bool(cats and categories.intersection(cats))
        if text_hit or cat_hit:
            key = c.get("full") or c.get("short")
            if key not in seen:
                seen.add(key)
                hits.append(c)
    return hits[:limit]


def commit_refs(commits: list[dict[str, Any]]) -> str:
    if not commits:
        return ""
    return ", ".join(f"<code>{html.escape(c.get('short',''))}</code>" for c in commits[:8])


def release_note_card(title: str, why: str, changes: list[str], risk: str, commits: list[dict[str, Any]], tone: str = "") -> dict[str, Any]:
    return {"title": title, "why": why, "changes": changes, "risk": risk, "commits": commits, "tone": tone}


def commit_subject_changes(commits: list[dict[str, Any]], limit: int = 5) -> list[str]:
    changes: list[str] = []
    seen: set[str] = set()
    for c in commits:
        subject = (c.get("subject") or "").strip()
        if not subject or subject in seen:
            continue
        seen.add(subject)
        changes.append(subject)
        if len(changes) >= limit:
            break
    return changes or ["Representative commits are listed below; inspect the raw tab for the full audit trail."]


def category_matter_description(cat: str) -> str:
    descriptions = {
        "Gateway/platforms": "Messaging, voice, Telegram/Discord-style adapters, and platform handoff reliability. Review this first if gateway or chat delivery is daily-critical.",
        "Dashboard/Web UI": "Browser dashboard and web UI changes. Useful polish, but usually lower risk than gateway/core unless you depend on the dashboard every day.",
        "CLI/TUI": "Terminal workflow, slash commands, prompts, session handling, and everyday Hermes ergonomics.",
        "Kanban/multi-agent": "Board/worker orchestration, task dispatch, and multi-agent coordination behavior.",
        "Core agent/model routing": "Agent loop, providers, OAuth/model routing, schemas, memory/session behavior, and other central runtime paths.",
        "Tools/toolsets": "Tool calls, browser/search/media/terminal integrations, mutation safety, and agent execution helpers.",
        "Cron/automation": "Scheduled jobs, background automation, wake/follow-up behavior, and unattended runs.",
        "Skills": "Reusable skill content and ecosystem additions. Mostly additive unless your workflow depends on a changed skill.",
        "Install/dependencies": "Install, update, packaging, dependency, and setup paths. Treat this as update-risk relevant.",
        "Docs": "Documentation and operator guidance. Low runtime risk but useful for understanding new behavior.",
        "Tests/reliability": "Regression tests and reliability hardening. Usually indirect value, but good evidence that fragile paths are being stabilized.",
        "Internal/other": "Changes that did not map cleanly to one product area. Skim for unexpected broad refactors or hidden risk.",
    }
    return descriptions.get(cat, "Pending changes in this area from the current HEAD..origin/main range.")


def category_risk(cat: str, high: int, total: int, dirty: bool) -> str:
    if cat == "Install/dependencies":
        base = "Update risk: medium-high; this touches install/update/dependency plumbing."
    elif cat in {"Gateway/platforms", "Core agent/model routing"}:
        base = "Update risk: medium; smoke-test your daily chat/provider flow after updating."
    elif cat in {"CLI/TUI", "Tools/toolsets", "Cron/automation", "Kanban/multi-agent"}:
        base = "Update risk: low-medium; test the workflow if you use this area heavily."
    else:
        base = "Update risk: low; mostly review for relevance unless the commits show broad changes."
    if dirty:
        return base + " Local Hermes edits are present, so checkpoint before any update."
    if high and high >= max(3, total // 3):
        return base + " This category has a high-impact concentration."
    return base


def importance_summary(commits: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(c.get("importance", "Low") for c in commits)
    return {"High": counts.get("High", 0), "Medium": counts.get("Medium", 0), "Low": counts.get("Low", 0)}


def build_release_notes(data: dict[str, Any]) -> dict[str, Any]:
    """Build category-grounded #matters content from pending commits only."""
    behind = int(data.get("behind", 0) or 0)
    high_total = int(data.get("importance_counts", {}).get("High", 0) or 0)
    dirty = bool(data.get("modified"))
    cards: list[dict[str, Any]] = []
    cats = sorted((data.get("category_counts") or {}).items(), key=lambda kv: (-int(kv[1] or 0), kv[0]))
    for cat, count in cats:
        commits = list((data.get("category_commits") or {}).get(cat, []))
        if not commits:
            continue
        imp = importance_summary(commits)
        cards.append({
            "category": cat,
            "title": cat,
            "why": category_matter_description(cat),
            "changes": commit_subject_changes(commits, limit=6),
            "risk": category_risk(cat, imp["High"], int(count or 0), dirty),
            "commits": commits,
            "count": int(count or 0),
            "importance": imp,
            "tone": "warn" if cat == "Install/dependencies" else ("good" if cat in {"Gateway/platforms", "Core agent/model routing", "Tools/toolsets", "Cron/automation"} else "neutral"),
        })
    if behind == 0:
        recommendation = "You are up to date. No update decision needed."
    elif dirty:
        recommendation = f"Review before updating: {behind} pending commit(s), including {high_total} high-impact candidate(s), and local Hermes edits are present."
    elif high_total >= 20:
        recommendation = f"Looks worth a planned update review: {behind} pending commit(s), grouped below by area, with {high_total} high-impact candidate(s)."
    else:
        recommendation = f"Probably optional for now: {behind} pending commit(s), grouped below by area, with {high_total} high-impact candidate(s)."
    return {"recommendation": recommendation, "cards": cards}

def build_new_since_refresh(state: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Return commits that appeared since the previous upstream refresh.

    The previous upstream waterline lives in state.json as last_upstream. On each
    helper refresh, serve.py fetches origin and sets RELEASE_RADAR_REFRESH=1;
    this generator compares the old waterline to the newly collected origin/main.
    Non-refresh regenerations, such as marker saves or local code edits, preserve
    the last highlight set so the visible cue does not disappear until the next
    real Refresh from upstream action.
    """
    if not data.get("repo_ok", True):
        return {}
    previous = state.get("last_upstream") or ""
    current = data.get("upstream") or ""
    is_refresh = os.environ.get("RELEASE_RADAR_REFRESH") == "1"
    empty = {
        "previous_upstream": previous,
        "current_upstream": current,
        "commit_count": 0,
        "commit_fulls": [],
        "category_counts": {},
        "warning": "",
    }
    if not previous or not current:
        return empty
    if previous == current:
        # A refresh with zero new upstream commits should not wipe the last
        # visible highlights. Users can treat those as "what changed recently" cues
        # until a later refresh actually discovers new commits, at which point
        # the highlight set is replaced below.
        if state.get("last_refresh_highlights"):
            saved = dict(state.get("last_refresh_highlights") or {})
            saved["current_upstream"] = current
            return saved
        return empty
    if not is_ancestor(previous, current):
        empty["warning"] = f"Previous upstream {previous[:12]} is not an ancestor of current upstream {current[:12]}; new-refresh highlights were skipped."
        return empty
    commits, cat_counts, _imp_counts, _category_commits = collect_commits(f"{previous}..{current}")
    return {
        "previous_upstream": previous,
        "current_upstream": current,
        "commit_count": len(commits),
        "commit_fulls": [c.get("full", "") for c in commits if c.get("full")],
        "category_counts": cat_counts,
        "warning": "",
    }


def js_data(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def anchor_id(prefix: str, value: str) -> str:
    safe = ''.join(ch.lower() if ch.isalnum() else '-' for ch in value).strip('-')
    while '--' in safe:
        safe = safe.replace('--', '-')
    return f"{prefix}-{safe or 'item'}"


def strip_md(text: str, limit: int = 520) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text or "")
    text = re.sub(r"[*_`#>]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def render_first_run_setup(data: dict[str, Any]) -> str:
    problem = data.get("repo_problem") or {}
    title = problem.get("title") or "Hermes checkout not ready"
    message = problem.get("message") or "Release Radar needs a readable Hermes Agent git checkout before it can compare local HEAD with origin/main."
    return (
        '<section class="card warn first-run-setup">'
        f'<h2>{html.escape(title)}</h2>'
        f'<p>{html.escape(message)}</p>'
        '<p class="muted">First-run setup: point Release Radar at the Hermes checkout you want to inspect, then regenerate or use the local helper refresh.</p>'
        '<ol>'
        '<li>Confirm the Hermes checkout path exists and is a git worktree.</li>'
        '<li>If Hermes lives elsewhere, set <code>RELEASE_RADAR_HERMES_REPO=/path/to/hermes-agent</code>.</li>'
        '<li>Run the generator again or start the local helper service. Release Radar still will not run <code>hermes update</code>.</li>'
        '</ol>'
        '<pre>RELEASE_RADAR_HERMES_REPO=~/.hermes/hermes-agent\npython3 src/generate.py</pre>'
        '</section>'
    )


def render_official_highlights(highlights: list[dict[str, Any]] | None) -> str:
    """Render parsed release highlights as <li> items (shared by live + cached cards)."""
    return "".join(
        f'<li><b>{html.escape(h.get("title", "Highlight"))}</b><br><span>{html.escape(strip_md(h.get("text", ""), 900))}</span></li>'
        for h in (highlights or [])
    ) or '<li>No parsed highlights in the latest GitHub release body.</li>'


def render_cached_official_release(data: dict[str, Any], cache: dict[str, Any]) -> str:
    """Render the cached last official release as honest, reference-only content.

    Shown on #official when no newer release is reachable but a prior official
    release was cached. It is reference content only and does not affect any
    counts elsewhere on the page; it makes no claim about pending commits in
    either direction (the other tabs are the source of truth for those).

    Always shows the current installed version from live ``data`` — never the
    cached ``installed_raw`` (which is only the install context at cache time).
    """
    cur = data.get("current_version", {})
    behind = int(data.get("behind", 0) or 0)
    rel_name = cache.get("name") or cache.get("tag_name") or "unknown"
    rel_url = cache.get("html_url") or "#"
    published = cache.get("published_at") or ""
    published_html = f' · <b>Published:</b> {html.escape(published)}' if published else ""
    shown = render_official_highlights(cache.get("highlights"))
    intro = "You are up to date" if behind == 0 else "No newer official release is reachable"
    return (
        '<section class="card official-release cached">'
        '<div class="row spread"><h2>Official release notes</h2><span class="pill medium">Last official release</span></div>'
        f'<p class="muted">{intro}; showing the last official release notes for reference. This is reference content only.</p>'
        f'<p class="version-line"><b>Installed:</b> {html.escape(cur.get("raw", "unknown"))} · <b>Last official release:</b> <a href="{html.escape(rel_url)}">{html.escape(rel_name)}</a>{published_html}</p>'
        '<details open><summary>Release framing from GitHub</summary>'
        f'<p>{html.escape(strip_md(cache.get("body_excerpt", ""), 1200))}</p></details>'
        f'<ul id="officialHighlights" class="highlight-list">{shown}</ul>'
        '</section>'
    )


def render_official_release(data: dict[str, Any], state: dict[str, Any] | None = None) -> str:
    if not data.get("repo_ok", True):
        return render_first_run_setup(data)
    latest = data.get("latest_release") or {}
    if data.get("release_fetch_error"):
        return f'<section class="card warn"><h2>Official release notes</h2><p>Could not fetch GitHub release notes: {html.escape(data["release_fetch_error"])}</p></section>'
    cur = data.get("current_version", {})
    reachable = data.get("reachable_releases", []) or []
    if not reachable:
        cache = (state or {}).get("last_official_release_notes") or {}
        if cache:
            return render_cached_official_release(data, cache)
        latest_name = latest.get("name") or latest.get("tag_name") or "unknown"
        latest_url = latest.get("html_url") or "#"
        return (
            '<section class="card official-release">'
            '<div class="row spread"><h2>Official release notes</h2><span class="pill medium">GitHub</span></div>'
            f'<p class="version-line"><b>Installed:</b> {html.escape(cur.get("raw", "unknown"))} · <b>Latest GitHub release:</b> <a href="{html.escape(latest_url)}">{html.escape(latest_name)}</a></p>'
            '<p class="muted">No newer GitHub release tag is currently reachable between your local HEAD and origin/main. The other tabs are based only on raw commits you are behind.</p>'
            '</section>'
        )
    rel = reachable[0]
    shown = render_official_highlights(rel.get("highlights"))
    rel_names = ", ".join(html.escape(r.get("name") or r.get("tag_name") or "release") for r in reachable) or "None detected between local HEAD and upstream top"
    return (
        '<section class="card official-release">'
        '<div class="row spread"><h2>Official release notes</h2><span class="pill medium">GitHub</span></div>'
        f'<p class="version-line"><b>Installed:</b> {html.escape(cur.get("raw", "unknown"))} · <b>Next release ahead:</b> <a href="{html.escape(rel.get("html_url", "#"))}">{html.escape(rel.get("name", "unknown"))}</a></p>'
        f'<p class="muted">Release(s) currently ahead of your checkout: {rel_names}</p>'
        '<details open><summary>Release framing from GitHub</summary>'
        f'<p>{html.escape(strip_md(rel.get("body_excerpt", ""), 1200))}</p></details>'
        f'<ul id="officialHighlights" class="highlight-list">{shown}</ul>'
        '</section>'
    )


def render_release_notes(data: dict[str, Any]) -> str:
    if not data.get("repo_ok", True):
        return render_first_run_setup(data)
    rel = build_release_notes(data)
    refresh = data.get("new_since_refresh", {}) or {}
    new_fulls = set(refresh.get("commit_fulls", []))

    def render_matter_jump(card: dict[str, Any]) -> str:
        cat = card.get("category") or card.get("title", "Area")
        count = int(card.get("count") or 0)
        is_new = bool(new_fulls and any(c.get("full") in new_fulls for c in card.get("commits", [])))
        new_count = sum(1 for c in card.get("commits", []) if c.get("full") in new_fulls)
        label = "commit" if count == 1 else "commits"
        badge = f'<em class="jump-new" title="Newly discovered on the last upstream refresh">+{new_count}</em>' if new_count else ""
        return (
            f'<a class="jump{" new-update" if is_new else ""}" href="#{anchor_id("matter", cat)}" title="{count} pending {label} in {html.escape(cat)}">'
            f'<span class="jump-label">{html.escape(cat)}</span>'
            f'<span class="jump-meta"><span class="jump-count">{count}</span><span class="jump-unit">{label}</span>{badge}</span>'
            f'</a>'
        )

    cards_html = []
    for card in rel["cards"]:
        cat = card.get("category") or card.get("title", "Area")
        changes = "".join(f"<li>{html.escape(item)}</li>" for item in card["changes"])
        refs = commit_refs(card["commits"])
        refs_html = f'<div class="commit-ref-block"><div class="muted">Representative pending commits:</div><div class="commit-ref-row">{refs}</div></div>' if refs else ""
        commit_dates = sorted({c.get("date", "") for c in card.get("commits", []) if c.get("date")})
        if commit_dates:
            if len(commit_dates) == 1:
                date_html = f'<p class="card-date">Pending commit date: <time>{html.escape(commit_dates[-1])}</time></p>'
            else:
                date_html = f'<p class="card-date">Pending commit dates: <time>{html.escape(commit_dates[0])}</time> → <time>{html.escape(commit_dates[-1])}</time></p>'
        else:
            date_html = '<p class="card-date">Pending commit dates: <time>unknown</time></p>'
        imp = card.get("importance", {}) or {}
        high = int(imp.get("High", 0) or 0)
        med = int(imp.get("Medium", 0) or 0)
        low = int(imp.get("Low", 0) or 0)
        tone = html.escape(card.get("tone") or "neutral")
        if high >= 10:
            signal_class, signal_label = "critical", "Critical"
        elif high or med:
            signal_class, signal_label = "medium", "Medium"
        else:
            signal_class, signal_label = "low", "Low"
        is_new = bool(new_fulls and any(c.get("full") in new_fulls for c in card.get("commits", [])))
        new_count = sum(1 for c in card.get("commits", []) if c.get("full") in new_fulls)
        new_badge = f'<span class="new-badge">● +{new_count} refresh</span>' if new_count else ""
        raw_link = anchor_id("cat", cat)
        cards_html.append(
            f'<article id="{anchor_id("matter", cat)}" class="release-card matter-card {tone}{" new-update" if is_new else ""}">'
            f'<div class="row spread"><div><p class="signal-label {signal_class}"><span class="signal-dot"></span>{signal_label}</p><h3>{html.escape(cat)}</h3></div>{new_badge}</div>'
            f'<div class="matter-stats"><span><b>{int(card.get("count") or 0)}</b> pending</span><span><b>{high}</b> high</span><span><b>{med}</b> medium</span><span><b>{low}</b> low</span></div>'
            f'<p class="why">{html.escape(card["why"])}</p>'
            f'<h4>Most relevant pending changes</h4><ul>{changes}</ul>'
            f'<p class="risk">{html.escape(card["risk"])}</p>'
            f'{refs_html}'
            f'{date_html}'
            f'<p class="matter-actions"><a class="openlink" href="#{raw_link}">Open raw {html.escape(cat)} commits</a></p>'
            f'</article>'
        )
    jump_html = "".join(render_matter_jump(card) for card in rel["cards"]) or '<p class="muted">No pending update areas yet.</p>'
    refresh_note = '<p class="muted compact-note">When present, small red <b>+N</b> badges mark commits discovered by the last upstream refresh; they are not the total pending count.</p>'
    return (
        '<section class="card release-notes matters-overview">'
        '<div class="row"><h2>What actually matters</h2><span class="pill high">Local review</span></div>'
        f'<p class="recommendation">{html.escape(rel["recommendation"])}</p>'
        '<details class="matters-context"><summary>Show update-range context</summary>'
        f'<p class="muted">This view is grouped by the same primary categories as Raw and only uses commits in the current <code>HEAD..origin/main</code> range.</p>'
        f'{refresh_note}'
        '</details>'
        f'<div class="jumpgrid matters-jump" aria-label="Jump to category">{jump_html}</div>'
        '</section>'
        f'<div id="impactGrid" class="release-grid matter-grid">{"".join(cards_html)}</div>'
    )

def render_markers_section(data: dict[str, Any]) -> str:
    return f'''<section class="card"><details><summary><h2>Review markers</h2><span class="muted">Hidden by default · use Mark all most of the time</span></summary><p class="muted">Server-side <code>state.json</code> is canonical. With the helper service online, marker buttons save to disk and regenerate this page.</p><div class="marker-controls"><input id="markerLabel" placeholder="Optional marker label"><button onclick="markAllCategories()">Mark all categories reviewed</button><button class="danger" onclick="clearMarkers()">Clear all markers</button></div><div id="topMarkerLine" class="section-marker" data-marker-slot="top"></div><div id="markers"></div><p id="newSince" class="muted"></p></details></section>'''


def render_page(data: dict[str, Any], state: dict[str, Any]) -> str:
    cats = sorted(data["category_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
    dirty = bool(data["modified"])
    if not data.get("repo_ok", True):
        verdict = "Setup needed"
        verdict_note = "Checkout missing"
    else:
        verdict = "Review first" if data["behind"] else "Up to date"
        verdict_note = "Local edits" if dirty else ("Ready" if data["behind"] else "Clean")
    today_sv = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
    release_notes = render_release_notes(data)
    official = render_official_release(data, state)
    refresh = data.get("new_since_refresh", {}) or {}
    new_cat_counts = refresh.get("category_counts", {}) or {}
    new_fulls = set(refresh.get("commit_fulls", []))

    def render_cat_jump(cat: str, count: int) -> str:
        is_new = cat in new_cat_counts
        badge = f"<em class=\"jump-new\" title=\"New primary-category commits this refresh\">+{new_cat_counts[cat]}</em>" if is_new else ""
        label = "commit" if count == 1 else "commits"
        return (
            f'<a class="jump{" new-update" if is_new else ""}" href="#{anchor_id("cat", cat)}" title="{count} unique pending {label} in this primary category">'
            f'<span class="jump-label">{html.escape(cat)}</span>'
            f'<span class="jump-meta"><span class="jump-count">{count}</span><span class="jump-unit">{label}</span>{badge}</span>'
            f'</a>'
        )

    cat_nav = "".join(render_cat_jump(cat, count) for cat, count in cats) or '<p class="muted">No categories yet. Configure a readable Hermes checkout first.</p>'

    def render_category_row(idx: int, e: dict[str, Any]) -> str:
        is_new = e["full"] in new_fulls
        classes = []
        if idx >= 20:
            classes.append("extra")
        if is_new:
            classes.append("new-commit")
        new_dot = '<span class="new-dot">new</span>' if is_new else ""
        return (
            f'<li class="{" ".join(classes)}" data-commit="{html.escape(e["full"])}"><b>{html.escape(e["importance"])}</b> '
            f'<code>{e["short"]}</code> <span class="muted">{html.escape(e["date"])}</span> {html.escape(e["subject"])} {new_dot}</li>'
        )

    def render_category(cat: str, count: int) -> str:
        aid = anchor_id("cat", cat)
        entries = data["category_commits"].get(cat, [])
        marker_commit = entries[0]["full"] if entries else data["upstream"]
        new_count = int(new_cat_counts.get(cat, 0) or 0)
        rows = "".join(render_category_row(idx, e) for idx, e in enumerate(entries))
        toggle = f'<button class="showmore" onclick="toggleCategory(\'{aid}\')" data-show-label="Show all {len(entries)}" data-hide-label="Show less">Show all {len(entries)}</button>' if len(entries) > 20 else ''
        new_badge = f'<span class="new-badge">● {new_count} new</span>' if new_count else ''
        return (
            f'<details id="{aid}" class="card category-card collapsed{" new-update" if new_count else ""}" data-marker-target="{aid}" open>'
            f'<summary class="cat-summary"><span class="cat-caret">{CHEVRON_RIGHT_SVG}</span><h3 class="cat-title">{html.escape(cat)} <span class="muted">{count}</span></h3></summary>'
            f'<div class="cat-actions">{new_badge}<button onclick="addMarker(\'{html.escape(cat)} reviewed\', \'{marker_commit}\', \'{aid}\')">Mark reviewed</button></div>'
            f'<div class="section-marker fallback-marker" data-marker-slot="{aid}"></div>'
            f'<ul class="category-commits">{rows}</ul>'
            f'<p class="row">{toggle}<a class="backtop" href="#top">Back to top</a></p></details>'
        )

    cat_cards = "\n".join(render_category(cat, count) for cat, count in cats)
    cat_bulk_controls = (
        f'<div class="cat-bulk">'
        f'<button class="cat-bulk-btn" type="button" onclick="expandAllCats()" title="Expand all categories">{CHEVRON_DOWN_SVG}<span>Expand all</span></button>'
        f'<button class="cat-bulk-btn" type="button" onclick="collapseAllCats()" title="Collapse all categories">{CHEVRON_UP_SVG}<span>Collapse all</span></button>'
        f'</div>'
    ) if cats else ''
    commits = "\n".join(
        f'<details id="commit-{c["short"]}" class="commit" data-marker-target="commit-{c["short"]}">'
        f'<summary><span class="pill {c["importance"].lower()}">{c["importance"]}</span> <code>{c["short"]}</code> {html.escape(c["subject"])} <span class="muted">{c["date"]}</span></summary>'
        f'<div class="section-marker" data-marker-slot="commit-{c["short"]}"></div>'
        f'<p>Categories: {html.escape(", ".join(c["categories"]))}</p>'
        f'<button onclick="addMarker(\'Reviewed through {c["short"]}\', \'{c["full"]}\', \'commit-{c["short"]}\')">Mark this commit reviewed</button>'
        f'<ul>' + "".join(f'<li>{html.escape(f)}</li>' for f in c["files"]) + '</ul></details>'
        for c in data["recent_commits"]
    ) or '<section class="card"><p class="muted">No raw commits are available until Release Radar can read the Hermes checkout.</p></section>'
    modified = "".join(f"<li><code>{html.escape(m)}</code></li>" for m in data["modified"])
    git_warning_rows = "".join(f"<li>{html.escape(w)}</li>" for w in data.get("git_warnings", []))
    git_warnings = f'<section class="card warn"><h2>Git inspection warnings</h2><ul>{git_warning_rows}</ul><p class="muted">Release Radar continued without mutating Hermes; review these before trusting release-range calculations.</p></section>' if git_warning_rows else ""
    if modified:
        safety_note = f'<section class="card warn"><h2>Local Hermes modified files</h2><p>Review these before any approved Hermes update:</p><ul>{modified}</ul><p class="muted">Safety: Release Radar inspected git/release data only. It did not update, install, restart, reset, stash, or modify Hermes source.</p></section>'
    else:
        safety_note = '<p class="muted safety-footnote">Safety: this page inspected git/release data only; it did not update, install, restart, reset, stash, or modify Hermes source.</p>'
    version = data.get("current_version", {})
    latest = data.get("latest_release", {})
    history_count = len(state.get("history", []))
    page_state = {"review_markers": state.get("review_markers", []), "upstream": data.get("upstream", "") }
    helper_url = f"http://{HELPER_HOST}:{HELPER_PORT}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Hermes Release Radar</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{FAVICON_DATA}">
<style>
{SHELL_CSS}
h2{{margin:20px 0 9px}} h3{{margin:0}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;max-width:100%;overflow-x:auto}} button{{background:#183831;color:var(--text);border:1px solid #2b6d60;border-radius:10px;padding:8px 10px;cursor:pointer;max-width:100%;white-space:normal;text-align:left}} button:hover{{background:#205347}} details>summary h2{{display:inline;margin-right:10px}} .danger{{background:#3a1b22;border-color:#7d3543}} .status-badge{{display:inline-flex;align-items:center;border-radius:999px;padding:4px 10px;border:1px solid var(--line);font-weight:700}} .status-badge.online{{background:#123a2e;color:#7ff6d7;border-color:#2b8a71}} .status-badge.offline{{background:#3a1b22;color:#ffb3b3;border-color:#7d3543}} .openlink{{display:inline-flex;align-items:center;min-height:34px;padding:0 10px;border:1px solid #315a7e;border-radius:10px;background:#102239;color:#d9ecff;text-decoration:none}} .helperbar{{display:grid;grid-template-columns:1fr;align-items:start;gap:10px;background:#0e171d;border:1px solid #21313b;border-radius:14px;padding:10px 12px;margin:0 0 12px;box-shadow:0 8px 20px #0003}} .helperbar p{{margin:2px 0 0}} .helper-actions{{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start;justify-content:flex-start;min-width:0}} .tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 8px;position:sticky;top:48px;z-index:1;background:#0b1014cc;padding:8px 0;backdrop-filter:blur(8px)}} .tabbtn{{background:#0e171d;border-color:var(--line);font-weight:800}} .tabbtn.active{{background:#183831;border-color:#2b8a71;color:#dffbf5}} .tab-panel{{display:none}} .tab-panel.active{{display:block}} .summary-strip{{display:grid;grid-template-columns:1.05fr .65fr .85fr .55fr .65fr .65fr;gap:8px;margin:8px 0 12px}} .summary-item{{background:#101820;border:1px solid #21313b;border-radius:12px;padding:8px 10px;min-height:56px;display:flex;flex-direction:column;justify-content:center;box-shadow:0 8px 20px #0003}} .summary-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}} .summary-value{{font-size:17px;font-weight:800;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}} .summary-value code{{font-size:15px;padding:1px 5px}} .summary-sub{{font-size:12px;color:#ffc857;margin-top:2px}} .status-item{{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"label badge" "sub badge";align-items:center;column-gap:12px;row-gap:4px;justify-content:stretch}} .status-item .summary-label{{grid-area:label}} .status-item .summary-value{{grid-area:badge;justify-self:end;align-self:center}} .status-item .summary-sub{{grid-area:sub;margin-top:0;align-self:center}} .latest-item .summary-value{{white-space:normal;overflow:visible;line-height:1.25}} @media(max-width:960px){{.summary-strip{{grid-template-columns:repeat(3,1fr)}}}} @media(max-width:560px){{.summary-strip{{grid-template-columns:repeat(2,1fr)}}}} .jumpgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:10px;align-items:stretch}} .jump{{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;text-decoration:none;background:#0e171d;border:1px solid #264e46;border-radius:12px;padding:10px 12px;min-height:58px;line-height:1.18;color:var(--text);box-shadow:inset 2px 0 0 #2a6d61}} .jump-label{{font-weight:750;color:#c7d7dc;overflow-wrap:normal;word-break:normal;hyphens:none}} .jump-meta{{display:inline-flex;align-items:center;justify-content:flex-end;gap:6px;flex-wrap:nowrap;white-space:nowrap}} .jump-count{{font-weight:800;color:#c7d7dc}} .jump-unit{{font-size:11px;color:var(--muted)}} .warn{{border-color:#7a5b20}} .pill{{border-radius:999px;padding:2px 8px;border:1px solid var(--line);font-size:12px}} .pill.high{{background:#3a2b12;color:#ffd98a}} .pill.medium{{background:#1d3042;color:#b9ddff}} .pill.low{{background:#172317;color:#b8f0be}} .marker-controls{{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}} input{{background:#0b1419;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:9px 10px;min-width:min(280px,100%)}} .marker{{display:flex;justify-content:space-between;gap:8px;align-items:center;border:1px solid var(--line);border-radius:12px;padding:8px;margin:7px 0;background:#0e171d}} .section-marker{{display:none}} .section-marker.visible,.inserted-marker{{display:block;margin:12px 0}} .marker-line{{border:0;border-top:2px solid var(--marker)}} .inline-marker-row{{display:flex;gap:8px;justify-content:space-between;align-items:center;flex-wrap:wrap;background:#0c2722;border:1px solid #276e61;border-radius:12px;padding:8px}} .category-card.collapsed .category-commits li.extra,#markers.collapsed .marker.extra{{display:none}} details.category-card{{position:relative}} .cat-summary{{display:flex;align-items:center;gap:10px;cursor:pointer;list-style:none;min-height:30px}} .cat-summary::-webkit-details-marker{{display:none}} .cat-caret{{flex:0 0 auto;display:inline-flex;color:var(--muted);transition:transform .15s ease}} details.category-card[open]>.cat-summary .cat-caret{{transform:rotate(90deg)}} .cat-title{{flex:1;min-width:0;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}} details.category-card[open]>.cat-summary{{padding-right:210px}} .cat-actions{{position:absolute;top:13px;right:14px;display:flex;align-items:center;gap:8px}} @media(max-width:600px){{details.category-card[open]>.cat-summary{{padding-right:0}} .cat-actions{{position:static;margin:8px 0 0;justify-content:flex-end}}}} .cat-bulk-row{{margin:20px 0 9px}} .cat-bulk-row h2{{margin:0}} .cat-bulk{{display:inline-flex;gap:8px;flex-wrap:wrap}} .cat-bulk-btn{{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;padding:6px 10px}} .cat-bulk-btn .ico{{flex:0 0 auto}} .showmore{{background:#102239;border-color:#315a7e}} .category-commits li,.highlight-list li{{margin:7px 0}} .release-notes,.official-release{{border-color:#315a7e;background:linear-gradient(180deg,#111d27,#0f171d)}} .recommendation{{font-size:17px;font-weight:800;color:#c7d7dc}} .release-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(330px,100%),1fr));gap:12px;align-items:start}} .matter-grid{{grid-template-columns:repeat(auto-fit,minmax(min(360px,100%),1fr));margin-top:12px}} .release-card{{background:#0e171d;border:1px solid var(--line);border-radius:14px;padding:13px;display:flex;flex-direction:column}} .matter-card{{background:linear-gradient(180deg,#101c24,#0d151b);border-color:#2b6d60;box-shadow:inset 3px 0 0 #2b8f78}} .matter-card.good,.matter-card.warn,.matter-card.neutral{{border-color:#2b6d60}} .release-card.good{{border-color:#2b6d60}} .release-card.warn{{border-color:#2b6d60}} .release-card h3{{margin-bottom:8px}} .release-card h4{{margin:12px 0 6px;color:#cfe8ef;font-size:13px;text-transform:uppercase;letter-spacing:.04em}} .release-card .why{{color:#dce9ee}} .release-card .risk{{color:#ffd98a;font-weight:650;margin:12px 0 10px}} .signal-label{{display:inline-flex;align-items:center;gap:6px;margin:0 0 4px;color:#96acb7;font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:650}} .signal-dot{{width:8px;height:8px;border-radius:999px;background:#67e5c3;box-shadow:0 0 8px #67e5c344}} .signal-label.medium .signal-dot{{background:#d7b75e;box-shadow:0 0 8px #d7b75e33}} .signal-label.critical .signal-dot{{background:#e66d73;box-shadow:0 0 9px #e66d7344}} .signal-label.low{{color:#8fcfbe}} .signal-label.medium{{color:#d4be78}} .signal-label.critical{{color:#efa0a5}} .eyebrow{{margin:0 0 2px;color:#77b9c6;font-size:11px;text-transform:uppercase;letter-spacing:.08em}} .matter-stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:8px 0 10px}} .matter-stats span{{border:1px solid #21323b;border-radius:10px;background:#0b1419;padding:6px 8px;color:#9fb3bd;font-size:12px}} .matter-stats b{{display:block;color:#e6f4f7;font-size:17px;line-height:1.1}} .matter-actions{{margin-top:auto;padding-top:8px}} .matters-overview,.jump-overview{{position:relative;border-color:#264e46;box-shadow:0 12px 30px #0005}} .matters-context{{margin:2px 0 10px;color:var(--muted)}} .matters-context summary{{display:inline-flex;color:#9fcfc6;font-size:13px;border:1px solid #264e46;border-radius:999px;padding:3px 9px;background:#0d1b1b}} .matters-context p{{margin:8px 0 0}} .commit-ref-block{{margin:8px 0 10px}} .commit-ref-row{{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px}} .card-date{{margin:8px 0 0;padding-top:8px;color:#91a4af;font-size:12px;border-top:1px solid #1f2d35}} .card-date time{{color:#c7d7de}} .new-refresh-banner{{margin:8px 0 10px;padding:8px 10px;border:1px solid #9b7b29;border-radius:12px;background:#211a0b;color:#ffe3a1}} .compact-note{{margin:4px 0 8px}} .new-badge{{display:inline-flex;align-items:center;gap:4px;border:1px solid #2f7180;border-radius:999px;background:#102832;color:#bfeef5;font-size:12px;font-weight:650;padding:2px 8px;white-space:nowrap}} .release-card.new-update{{border-color:var(--line);box-shadow:none}} .matter-card.new-update{{border-color:#2b6d60;box-shadow:inset 3px 0 0 #2b8f78}} .category-card.new-update{{border-color:#2f7180;box-shadow:none}} .jump.new-update{{border-color:#264e46;background:linear-gradient(180deg,#102832,#0e171d);color:var(--text);font-weight:inherit;box-shadow:inset 2px 0 0 #2a6d61}} .jump-new{{font-style:normal;border-radius:999px;background:#3a1f25;color:#ffc6cc;border:1px solid #b85b68;padding:2px 7px;line-height:1.25;min-width:0;font-size:12px;font-weight:650}} .category-commits li.new-commit{{background:#102832;border-left:3px solid #38b6c9;border-radius:8px;padding:5px 7px}} .new-dot{{display:inline-block;margin-left:6px;border-radius:999px;background:#3a1f25;color:#ffc6cc;border:1px solid #b85b68;font-size:11px;font-weight:650;padding:1px 6px}} .highlight-list{{padding-left:20px}} .version-line{{font-size:16px}} .toast-layer{{position:fixed;top:56px;left:50%;transform:translateX(-50%);width:min(1180px,calc(100vw - 36px));z-index:5;pointer-events:none;display:flex;flex-direction:column;align-items:flex-end;gap:8px}} .toast{{pointer-events:auto;max-width:min(360px,100%);margin-left:auto;display:flex;gap:8px;align-items:flex-start;background:#0e171d;border:1px solid var(--line);border-radius:12px;padding:10px 12px;box-shadow:0 10px 26px #0006;color:var(--text);font-size:13px;line-height:1.35;cursor:pointer;opacity:0;transform:translateY(-6px);transition:opacity .18s ease,transform .18s ease}} .toast.show{{opacity:1;transform:translateY(0)}} .toast.ok{{border-color:#2b8a71}} .toast.err{{border-color:#7d3543}} .toast.info{{border-color:#315a7e}} .toast .dot{{flex:0 0 auto;width:8px;height:8px;border-radius:999px;margin-top:5px;background:var(--muted)}} .toast.ok .dot{{background:#7ff6d7}} .toast.err .dot{{background:#ff9b9b}} .toast.info .dot{{background:#8fd0ff}} .toast .toast-msg{{min-width:0;overflow-wrap:anywhere}} @media(max-width:760px){{.helperbar{{grid-template-columns:1fr}} .helper-actions{{justify-content:flex-start;min-width:0}}}}
</style></head><body>
<div id="top" class="topbar"><main class="row spread"><span class="brandwrap"><a class="brand" href="index.html" aria-label="Hermes Release Radar home">{APP_ICON_SVG}<span>Hermes Release Radar</span></a>{APP_VERSION_BADGE}</span><span class="navlinks"><a href="history.html">History ({history_count})</a><a class="help-icon" href="help.html" title="Help / setup commands" aria-label="Help / setup commands">?</a></span></main></div>
<main>
<div id="toastLayer" class="toast-layer" aria-live="polite" aria-atomic="false"></div>
<h1>Hermes Release Radar</h1><p class="muted">Generated {html.escape(data['generated_at'])} from {html.escape(data['repo'])}</p>
<section class="summary-strip" aria-label="Release radar summary">
<div class="summary-item status-item"><div class="summary-label">Status</div><div class="summary-value"><span id="helperStatus" class="status-badge offline">Checking…</span></div><div class="summary-sub">{html.escape(verdict)} · {html.escape(verdict_note)}</div></div>
<div class="summary-item"><div class="summary-label">Installed</div><div class="summary-value">{html.escape(version.get('version','?'))}</div><div class="summary-sub">{html.escape(version.get('date',''))}</div></div>
<div class="summary-item latest-item"><div class="summary-label">Latest</div><div class="summary-value">{html.escape((latest.get('name') or latest.get('tag_name') or '?').replace('Hermes Agent ',''))}</div></div>
<div class="summary-item"><div class="summary-label">Behind</div><div class="summary-value">{data['behind']}</div></div>
<div class="summary-item"><div class="summary-label">High impact</div><div class="summary-value">{data['importance_counts'].get('High',0)}</div></div>
<div class="summary-item"><div class="summary-label">Upstream</div><div class="summary-value"><code>{data['upstream'][:10]}</code></div></div>
</section>
<section class="helperbar"><div><b>Local helper service</b><p id="helperDetail" class="muted">Checking local-only service on <code>{html.escape(helper_url)}</code>.</p></div><div class="helper-actions"><button class="refresh" onclick="refreshRadar()">Refresh from upstream</button><button onclick="checkHelperStatus(true)">Check status</button></div></section>
<nav class="tabs" aria-label="Release radar sections"><button class="tabbtn active" onclick="switchTab('official', this)">Official release notes</button><button class="tabbtn" onclick="switchTab('matters', this)">What actually matters</button><button class="tabbtn" onclick="switchTab('raw', this)">Raw categorized commits</button></nav>
<section id="tab-official" class="tab-panel active">{official}</section>
<section id="tab-matters" class="tab-panel">{release_notes}</section>
<section id="tab-raw" class="tab-panel">
<section class="card jump-overview"><h2>Jump to category</h2><details class="matters-context"><summary>Show raw-category context</summary><p class="muted">Raw commit groups are here for auditability. <b>{data['behind']}</b> unique pending commit(s) are in the current <code>HEAD..origin/main</code> range. Category numbers below use each commit’s primary category, so the visible category total matches the unique pending count.</p></details><div class="jumpgrid">{cat_nav}</div></section>
{safety_note}
{git_warnings}
{render_markers_section(data)}
<section class="card"><h2>Current installed state</h2><pre>{html.escape(data['version_output'])}\n{html.escape(data['status'])}</pre><p>Baseline checkpoint: <code>{html.escape(state.get('baseline_commit','')[:12])}</code> — {html.escape(state.get('baseline_label',''))}</p></section>
<div class="row spread cat-bulk-row"><h2>Raw categorized commits</h2>{cat_bulk_controls}</div>{cat_cards}
<h2>Recent upstream commits</h2><p class="muted">Showing the newest {len(data['recent_commits'])} commits from HEAD..origin/main.</p>{commits}
</section>
</main>
<script>
const DATA = {{}};
const STATE = {js_data(page_state)};
const HELPER = {js_data(helper_url)};
const TODAY_LABEL = '{today_sv}';
let helperOnline = false;
let MARKERS = Array.isArray(STATE.review_markers) ? [...STATE.review_markers] : [];
const CATEGORY_TARGETS = {js_data([{ "id": anchor_id("cat", cat), "label": cat, "commit": (data["category_commits"].get(cat, [{}])[0].get("full") or data["upstream"]) } for cat, _count in cats])};
function getMarkers() {{ return MARKERS; }}
async function saveMarkers(ms, toastMsg) {{
  MARKERS = ms; renderMarkers();
  if (!helperOnline) {{ setHelperStatus(false, 'Helper is offline. Marker changes are visible only until reload.'); showToast(`${{toastMsg || 'Marker updated'}} — helper offline, so visible only until reload.`, 'err'); return; }}
  try {{
    const res = await fetch(`${{HELPER}}/api/markers`, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{review_markers: MARKERS}})}});
    const payload = await res.json().catch(() => ({{}}));
    if (!res.ok || !payload.ok) throw new Error(payload.error || await res.text());
    setHelperStatus(true, 'Markers saved to state.json and page regenerated. Reload to view regenerated HTML.');
    showToast(`${{toastMsg || 'Markers saved'}} — saved to state.json.`, 'ok');
  }} catch (err) {{ setHelperStatus(false, `Could not save markers to helper: ${{err.message || err}}`); showToast(`Could not save markers — ${{err.message || err}}`, 'err'); }}
}}
function showToast(message, kind) {{ const layer = document.getElementById('toastLayer'); if (!layer || !message) return; const el = document.createElement('div'); el.className = `toast ${{kind || 'info'}}`; el.setAttribute('role', kind === 'err' ? 'alert' : 'status'); const dot = document.createElement('span'); dot.className = 'dot'; const msg = document.createElement('span'); msg.className = 'toast-msg'; msg.textContent = message; el.appendChild(dot); el.appendChild(msg); layer.appendChild(el); requestAnimationFrame(() => el.classList.add('show')); let removed = false; const remove = () => {{ if (removed) return; removed = true; el.classList.remove('show'); setTimeout(() => el.remove(), 200); }}; const timer = setTimeout(remove, 4500); el.addEventListener('click', () => {{ clearTimeout(timer); remove(); }}); }}
function queueToast(message, kind) {{ try {{ sessionStorage.setItem('rrToast', JSON.stringify({{message, kind}})); }} catch (_) {{}} }}
function flushPendingToast() {{ try {{ const raw = sessionStorage.getItem('rrToast'); if (!raw) return; sessionStorage.removeItem('rrToast'); const t = JSON.parse(raw); showToast(t.message, t.kind); }} catch (_) {{}} }}
function setHelperStatus(ok, detail) {{ helperOnline = !!ok; const badge = document.getElementById('helperStatus'); const text = document.getElementById('helperDetail'); if (badge) {{ badge.className = `status-badge ${{ok ? 'online' : 'offline'}}`; badge.textContent = ok ? 'Online' : 'Offline'; }} if (text) text.textContent = detail || (ok ? 'Helper is online.' : 'Helper is offline.'); }}
async function checkHelperStatus(fromClick) {{ try {{ const res = await fetch(`${{HELPER}}/api/status`, {{cache:'no-store'}}); const payload = await res.json(); if (!res.ok || !payload.ok) throw new Error(payload.error || 'status failed'); setHelperStatus(true, `Online · markers: ${{payload.marker_count}} · last generated: ${{payload.last_generated_at || 'unknown'}} · ${{payload.index_path}}`); if (fromClick) showToast(`Helper online · ${{payload.marker_count}} marker(s) · last generated ${{payload.last_generated_at || 'unknown'}}`, 'ok'); }} catch (err) {{ setHelperStatus(false, 'Offline. Refresh and durable marker saves need hermes-release-radar.service running.'); if (fromClick) showToast('Helper offline — start hermes-release-radar.service to enable Refresh and durable marker saves.', 'err'); }} }}
function addMarker(label, commit, targetId) {{ const input = document.getElementById('markerLabel'); const finalLabel = (input && input.value.trim()) || label || 'Reviewed marker'; const target = targetId || 'top'; const ms = getMarkers().filter(m => (m.target_id || 'top') !== target); ms.unshift({{ id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())), label: finalLabel, commit, target_id: target, created_at: new Date().toISOString() }}); if (input) input.value = ''; saveMarkers(ms, 'Review marker saved'); }}
function markAllCategories() {{ const input = document.getElementById('markerLabel'); const labelText = (input && input.value.trim()) || TODAY_LABEL; const suffix = labelText ? ` — ${{labelText}}` : ''; const existing = getMarkers().filter(m => !CATEGORY_TARGETS.some(c => c.id === (m.target_id || 'top'))); const now = new Date().toISOString(); const added = CATEGORY_TARGETS.map(c => ({{ id: (crypto.randomUUID ? crypto.randomUUID() : `${{Date.now()}}-${{c.id}}`), label: `${{c.label}} reviewed${{suffix}}`, commit: c.commit, target_id: c.id, created_at: now }})); if (input) input.value = ''; saveMarkers([...added, ...existing], 'All categories marked reviewed'); }}
function deleteMarker(id) {{ saveMarkers(getMarkers().filter(m => m.id !== id), 'Marker cleared'); }}
function clearMarkers() {{ if (confirm('Clear all review markers for this page?')) saveMarkers([], 'All review markers cleared'); }}
function activeTabHash() {{ const active = document.querySelector('.tab-panel.active'); if (!active || !active.id) return '#official'; return `#${{active.id.replace('tab-', '')}}`; }}
async function refreshRadar() {{ try {{ const activeHash = activeTabHash(); setHelperStatus(true, 'Refreshing: git fetch origin --quiet + regenerate page…'); showToast('Refreshing from upstream… (git fetch origin + regenerate)', 'info'); const res = await fetch(`${{HELPER}}/api/refresh`, {{method:'POST'}}); const payload = await res.json().catch(() => ({{}})); if (!res.ok || !payload.ok) throw new Error(payload.error || await res.text()); queueToast('Refreshed from upstream ✓ — page regenerated.', 'ok'); location.href = `${{HELPER}}/?t=${{Date.now()}}${{activeHash}}`; }} catch (err) {{ setHelperStatus(false, `Refresh failed or helper is offline: ${{err.message || err}}`); showToast(`Refresh failed — ${{err.message || err}}. Needs the local hermes-release-radar.service.`, 'err'); }} }}
function toggleCategory(id) {{ const section = document.getElementById(id); if (!section) return; section.classList.toggle('collapsed'); const btn = section.querySelector('.showmore'); if (btn) btn.textContent = section.classList.contains('collapsed') ? btn.dataset.showLabel : btn.dataset.hideLabel; }}
function expandAllCats() {{ document.querySelectorAll('#tab-raw details.category-card').forEach(d => {{ d.open = true; }}); }}
function collapseAllCats() {{ document.querySelectorAll('#tab-raw details.category-card').forEach(d => {{ d.open = false; }}); }}
function loadCatState() {{ try {{ return JSON.parse(localStorage.getItem('rr_cat_open') || '{{}}'); }} catch (_) {{ return {{}}; }} }}
function saveCatState(map) {{ try {{ localStorage.setItem('rr_cat_open', JSON.stringify(map)); }} catch (_) {{}} }}
function initCatToggle() {{ const map = loadCatState(); document.querySelectorAll('#tab-raw details.category-card').forEach(d => {{ if (d.id && Object.prototype.hasOwnProperty.call(map, d.id)) d.open = map[d.id]; d.addEventListener('toggle', () => {{ const m = loadCatState(); m[d.id] = d.open; saveCatState(m); }}); }}); }}
function toggleBlock(id, btn) {{ const el = document.getElementById(id); if (!el) return; el.classList.toggle('collapsed'); if (btn && btn.dataset) btn.textContent = el.classList.contains('collapsed') ? btn.dataset.showLabel : btn.dataset.hideLabel; }}
function toggleMarkerList(btn) {{ const el = document.getElementById('markers'); if (!el) return; el.classList.toggle('collapsed'); if (btn && btn.dataset) btn.textContent = el.classList.contains('collapsed') ? btn.dataset.showLabel : btn.dataset.hideLabel; }}
function switchTab(name, btn) {{ document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${{name}}`)); document.querySelectorAll('.tabbtn').forEach(b => b.classList.toggle('active', b === btn)); if (history.replaceState) history.replaceState(null, '', `#${{name}}`); }}
function activateInitialTab() {{ let name = (location.hash || '#official').slice(1); if (name.startsWith('cat-') || name.startsWith('commit-')) name = 'raw'; const btn = [...document.querySelectorAll('.tabbtn')].find(b => b.getAttribute('onclick')?.includes(`'${{name}}'`)); if (btn) switchTab(name, btn); }}
function renderMarkers() {{ const el = document.getElementById('markers'); const ns = document.getElementById('newSince'); const ms = getMarkers(); document.querySelectorAll('[data-marker-slot]').forEach(slot => {{ slot.classList.remove('visible'); slot.innerHTML = ''; }}); document.querySelectorAll('.inserted-marker').forEach(node => node.remove()); if (!ms.length) {{ if(el) el.innerHTML = '<p class="muted">No review markers yet.</p>'; if(ns) ns.textContent = 'Everything above your first marker will count as new to your eyes.'; return; }} const latestByTarget = new Map(); ms.slice().reverse().forEach(m => latestByTarget.set(m.target_id || 'top', m)); latestByTarget.forEach((m, targetId) => {{ const section = document.getElementById(targetId); const markHtml = `<div class="section-marker visible inserted-marker"><hr class="marker-line"><div class="inline-marker-row"><span class="marker-label">Reviewed through here: ${{escapeHtml(m.label)}} · ${{new Date(m.created_at).toLocaleString()}}</span><button class="danger" onclick="deleteMarker('${{m.id}}')">Clear marker</button></div></div>`; if (section && section.classList.contains('category-card')) {{ const match = section.querySelector(`li[data-commit="${{cssEscape(m.commit || '')}}"]`); if (match) match.insertAdjacentHTML('beforebegin', markHtml); else {{ const slot = section.querySelector(`[data-marker-slot="${{cssEscape(targetId)}}"]`); if (slot) {{ slot.classList.add('visible'); slot.innerHTML = markHtml; }} }} return; }} const slot = document.querySelector(`[data-marker-slot="${{cssEscape(targetId)}}"]`); if (slot) {{ slot.classList.add('visible'); slot.innerHTML = markHtml; }} }}); if(el) {{ const rows = ms.map((m,i) => `<div class="marker ${{i >= 4 ? 'extra' : ''}}"><div><b>${{escapeHtml(m.label)}}</b><br><span class="muted">${{new Date(m.created_at).toLocaleString()}} · <code>${{(m.commit || 'unknown').slice(0,12)}}</code> · <a class="backtop" href="#${{escapeHtml(m.target_id || 'top')}}">jump</a></span></div><button class="danger" onclick="deleteMarker('${{m.id}}')">Clear marker</button></div>`).join(''); const btn = ms.length > 4 ? `<button class="showmore" onclick="toggleMarkerList(this)" data-show-label="Show all ${{ms.length}} markers" data-hide-label="Show fewer markers">Show all ${{ms.length}} markers</button>` : ''; el.classList.add('collapsed'); el.innerHTML = rows + btn; }} if(ns) ns.innerHTML = `Last review marker: <code>${{(ms[0].commit || 'unknown').slice(0,12)}}</code>. Newer upstream top now: <code>${{(STATE.upstream || 'unknown').slice(0,12)}}</code>.`; }}
function cssEscape(s) {{ return String(s).replace(/[^a-zA-Z0-9_-]/g, ''); }}
function escapeHtml(s) {{ return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
flushPendingToast(); activateInitialTab(); initCatToggle(); window.addEventListener('hashchange', activateInitialTab); renderMarkers(); checkHelperStatus();
</script></body></html>"""


def render_history(state: dict[str, Any]) -> str:
    entries = list(reversed(state.get("history", [])))
    warn = state.get("checkpoint_warning")
    warn_banner = (
        f'<section class="card warn"><h2>Checkpoint warning</h2><p>{html.escape(warn)}</p>'
        '<p class="muted">History was not auto-archived for this change. No history was deleted.</p></section>'
        if warn else ""
    )
    if not entries:
        body = warn_banner + '<section class="card"><h2>No installed-update history yet</h2><p class="muted">After Hermes local HEAD advances beyond the stored baseline, Release Radar will archive the installed range here and reset the main page to only future upstream commits.</p></section>'
    else:
        cards = []
        for idx, h in enumerate(entries):
            cats = h.get("category_counts", {})
            cat_text = ", ".join(f"{html.escape(k)}: {v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])[:8])
            rels = h.get("releases", [])
            rel_html = "".join(f'<li><a href="{html.escape(r.get("html_url", "#"))}">{html.escape(r.get("name") or r.get("tag_name") or "release")}</a></li>' for r in rels) or "<li>No official release tag detected inside this installed range.</li>"
            top_commits = "".join(f'<li><code>{html.escape(c.get("short",""))}</code> {html.escape(c.get("subject",""))}</li>' for c in h.get("commits", [])[:25])
            from_label = history_display_label(h.get('from_version', ''), h.get('old_baseline', ''))
            to_label = history_display_label(h.get('to_version', ''), h.get('new_baseline', ''))
            if h.get("kind") == "gap":
                mb = h.get("merge_base", "")
                mb_html = f' · nearest common ancestor <code>{html.escape(mb[:12])}</code>' if mb else ""
                cards.append(f'''<section class="card warn"><h2>History gap · {html.escape(from_label)} → {html.escape(to_label)}</h2><p class="muted">Recorded {html.escape(h.get('archived_at',''))} · ~{h.get('commit_count',0)} commits (approximate) · <code>{html.escape(h.get('old_baseline','')[:12])}</code> → <code>{html.escape(h.get('new_baseline','')[:12])}</code>{mb_html}</p><p>{html.escape(GAP_EXPLANATION)}</p><details open><summary>Official releases in the recovered range</summary><ul>{rel_html}</ul></details><p><b>Category mix (approximate):</b> {cat_text or 'none'}</p><details><summary>Sample commits in the recovered range</summary><ul>{top_commits}</ul></details></section>''')
                continue
            cards.append(f'''<section class="card"><h2>{html.escape(from_label)} → {html.escape(to_label)}</h2><p class="muted">Archived {html.escape(h.get('archived_at',''))} · {h.get('commit_count',0)} installed commits · <code>{html.escape(h.get('old_baseline','')[:12])}</code> → <code>{html.escape(h.get('new_baseline','')[:12])}</code></p><details open><summary>Official releases in this installed range</summary><ul>{rel_html}</ul></details><p><b>Category mix:</b> {cat_text or 'none'}</p><details><summary>Top installed commits</summary><ul>{top_commits}</ul></details></section>''')
        body = warn_banner + "\n".join(cards)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Hermes Release Radar History</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{FAVICON_DATA}"><style>{SHELL_CSS}</style></head><body><div class="topbar"><main class="row spread"><span class="brandwrap"><a class="brand" href="index.html" aria-label="Hermes Release Radar home">{APP_ICON_SVG}<span>Hermes Release Radar</span></a>{APP_VERSION_BADGE}</span><span class="navlinks"><a href="index.html">Current</a><a class="help-icon" href="help.html" title="Help / setup commands" aria-label="Help / setup commands">?</a></span></main></div><main><h1>Installed update history</h1><p class="muted">This is the archive of commits that became installed checkpoints. It is separate from review markers.</p>{body}</main></body></html>'''


def archive_if_head_advanced(state: dict[str, Any], data: dict[str, Any]) -> None:
    if not data.get("repo_ok", True):
        return
    baseline = state.get("baseline_commit") or ""
    head = data["head"]
    if not baseline:
        state["baseline_commit"] = head
        state["baseline_label"] = checkpoint_label_for(data.get("current_version", {}), head)
        return
    if baseline == head:
        return
    if is_ancestor(baseline, head):
        commits, cat_counts, imp_counts, _category_commits = collect_commits(f"{baseline}..{head}")
        old_version = parse_version(state.get("last_version_output", "") or state.get("baseline_label", ""))
        new_version = data.get("current_version", {})
        releases = releases_between([data.get("latest_release", {})] + data.get("reachable_releases", []), baseline, head)
        record = {
            "archived_at": data["generated_at"],
            "old_baseline": baseline,
            "new_baseline": head,
            "from_version": old_version.get("raw") or state.get("baseline_label", "unknown"),
            "to_version": new_version.get("raw", "unknown"),
            "commit_count": len(commits),
            "category_counts": cat_counts,
            "importance_counts": imp_counts,
            "releases": releases,
            "commits": [{k: c[k] for k in ["short", "full", "date", "subject", "importance", "categories"]} for c in commits],
            "review_markers_archived": state.get("review_markers", []),
        }
        state.setdefault("history", []).append(record)
        state["baseline_commit"] = head
        state["baseline_label"] = checkpoint_label_for(new_version, head)
        state["review_markers"] = []
        state["checkpoint_notice"] = f"Archived {len(commits)} installed commits into history and moved baseline to {head[:12]}."
        state.pop("checkpoint_warning", None)
    elif is_ancestor(head, baseline):
        # HEAD is behind the stored baseline (a possible Hermes rollback/downgrade).
        # Do not fabricate a range or move the baseline backwards; surface a warning.
        state["checkpoint_warning"] = (
            f"Current HEAD {head[:12]} is behind stored baseline {baseline[:12]} "
            f"(possible Hermes rollback); not auto-archiving. Manual checkpoint review needed."
        )
    else:
        # Non-ancestor in both directions. Recover ONLY on verified trusted-lineage
        # divergence; every other untrusted state warns without mutating history.
        attempt_history_gap_recovery(state, data, baseline, head)


def attempt_history_gap_recovery(state: dict[str, Any], data: dict[str, Any], baseline: str, head: str) -> None:
    """Gate automatic gap recovery behind read-only, fail-closed trust checks.

    Reached only when baseline and HEAD are non-ancestors of each other (genuine
    divergence). A durable gap is recorded — clearing markers and advancing the
    baseline — ONLY when every trust condition holds: both commits resolve, HEAD is
    on the trusted origin/main lineage, and a real merge-base exists. If any check
    fails we set a specific checkpoint_warning and leave history, baseline, and
    markers untouched. Never mutates the Hermes checkout.
    """
    upstream = data.get("upstream") or ""
    if not commit_exists(baseline):
        state["checkpoint_warning"] = (
            f"Stored Release Radar baseline {baseline[:12] or '(empty)'} could not be resolved in the Hermes "
            f"checkout (missing or garbage-collected); skipping automatic history recovery. No history was changed."
        )
        return
    if not commit_exists(head):
        state["checkpoint_warning"] = (
            f"Current HEAD {head[:12] or '(empty)'} could not be resolved in the Hermes checkout; "
            f"skipping automatic history recovery. No history was changed."
        )
        return
    if not commit_exists(upstream):
        state["checkpoint_warning"] = (
            "Could not resolve a trusted origin/main to verify the current HEAD's lineage; "
            "skipping automatic history recovery. No history was changed."
        )
        return
    if not head_is_on_upstream_lineage(head, upstream):
        state["checkpoint_warning"] = (
            f"Current HEAD {head[:12]} is not on the trusted origin/main lineage "
            f"(e.g. a local feature branch or detached commit); skipping automatic history recovery. "
            f"No history was changed."
        )
        return
    mb = merge_base(baseline, head)
    if not mb:
        state["checkpoint_warning"] = (
            f"No common ancestor between stored baseline {baseline[:12]} and current HEAD {head[:12]} "
            f"(unrelated histories); skipping automatic history recovery. No history was changed."
        )
        return
    record_history_gap(state, data, baseline, head, mb)


def record_history_gap(state: dict[str, Any], data: dict[str, Any], baseline: str, head: str, mb: str) -> None:
    """Append a durable 'gap' record for a verified trusted-lineage divergence.

    Callers (attempt_history_gap_recovery) must have already verified every trust
    condition, including a non-empty merge-base ``mb``. The individual installed
    checkpoints between baseline and HEAD cannot be reconstructed faithfully, so we
    record one clearly-labelled gap covering ``mb..head`` — counts approximate,
    version labels only when reliably derivable — and advance the baseline to HEAD so
    the next real update archives normally. Existing history is never deleted.
    Read-only git inspection; the Hermes checkout is not mutated.
    """
    commits, cat_counts, imp_counts, _category_commits = collect_commits(f"{mb}..{head}")
    releases = releases_between([data.get("latest_release", {})] + data.get("reachable_releases", []), mb, head)
    new_version = data.get("current_version", {})
    # from_version: prefer the real version at the diverged baseline; fall back to the
    # stored label only if it is valid; otherwise a neutral checkpoint. Never invented.
    stored_label = state.get("baseline_label", "")
    from_label = (
        version_label_at_commit(baseline)
        or (stored_label if is_valid_checkpoint_label(stored_label) else "")
        or f"Checkpoint {baseline[:12]}"
    )
    to_label = new_version.get("raw") or version_label_at_commit(head) or f"Checkpoint {head[:12]}"
    record = {
        "kind": "gap",
        "archived_at": data["generated_at"],
        "old_baseline": baseline,
        "new_baseline": head,
        "merge_base": mb,
        "from_version": from_label,
        "to_version": to_label,
        "commit_count": len(commits),
        "commit_count_approximate": True,
        "category_counts": cat_counts,
        "importance_counts": imp_counts,
        "releases": releases,
        "commits": [{k: c[k] for k in ["short", "full", "date", "subject", "importance", "categories"]} for c in commits[:50]],
        "review_markers_archived": state.get("review_markers", []),
        "note": GAP_EXPLANATION,
    }
    state.setdefault("history", []).append(record)
    state["baseline_commit"] = head
    state["baseline_label"] = checkpoint_label_for(new_version, head)
    state["review_markers"] = []
    state["checkpoint_notice"] = (
        f"Recorded a history gap and recovered the baseline to {head[:12]} after the stored baseline "
        f"diverged from the trusted origin/main lineage (~{len(commits)} commits in the recovered range)."
    )
    state.pop("checkpoint_warning", None)


def history_display_label(label: str, commit: str) -> str:
    """Render-safe history label: the stored label if valid, else a neutral checkpoint.

    Defensive fallback so the History page never shows operational error text even
    if a record has not been (or cannot be) repaired by migrate_history_version_labels.
    """
    if is_valid_checkpoint_label(label):
        return label
    return f"Checkpoint {commit[:12]}" if commit else "Checkpoint unknown"


def migrate_history_version_labels(state: dict[str, Any], data: dict[str, Any]) -> None:
    """Repair invalid version labels in archived installed-update history.

    History records created before the baseline-label fix could persist operational
    error text (e.g. "hermes command not found") as from_version/to_version. Repair
    ONLY invalid labels: derive the real version from the record's baseline commit
    via version_label_at_commit() (read-only) when possible, otherwise fall back to
    "Checkpoint <shortsha>". Valid labels and every other field (commits, baselines,
    counts, dates, releases, archived review markers) are left untouched, and no
    records are added, removed, or reordered.
    """
    if not data.get("repo_ok", True):
        return  # only derive labels when the checkout is readable
    for record in state.get("history") or []:
        for field, baseline_key in (("from_version", "old_baseline"), ("to_version", "new_baseline")):
            if is_valid_checkpoint_label(record.get(field, "")):
                continue  # keep valid labels exactly as stored
            derived = version_label_at_commit(record.get(baseline_key) or "")
            if derived:
                record[field] = derived  # only durably rewrite when a real version is reliably derivable
            # else: leave the stored label untouched; render_history shows a neutral
            # Checkpoint <shortsha> at display time, so we never lose the chance to
            # derive the real version later and never casually rewrite durable history.


def prune_review_markers(state: dict[str, Any], data: dict[str, Any]) -> None:
    """Drop review markers that no longer map to the current pending view.

    Review markers are local "reviewed through here" state tied to the pending
    HEAD..origin/main commits shown on the current page. After Hermes is updated
    and Release Radar refreshes, implemented commits leave that pending view, so
    their markers are stale and must not linger under "Review markers". This runs
    after archive_if_head_advanced(), which already snapshots the full marker set
    into installed-update history when HEAD advances — so pruning here never
    touches state["history"] or that archived copy.

    - behind == 0: no pending upstream commits remain, so all current-page markers
      are cleared.
    - behind > 0: keep a marker only when its target is still rendered — a
      'top'/global marker, a category target id derived from category_counts, or a
      raw commit target id from recent_commits — and, for non-top markers that
      carry a commit hash, only when that commit is still in the pending set.
    """
    if not data.get("repo_ok", True):
        return  # no reliable pending view to reconcile against; leave markers as-is
    markers = state.get("review_markers") or []
    if not markers:
        return
    behind = int(data.get("behind", 0) or 0)
    if behind == 0:
        state["review_markers"] = []
        return
    recent = data.get("recent_commits") or []
    category_targets = {anchor_id("cat", cat) for cat in (data.get("category_counts") or {})}
    commit_targets = {f"commit-{c.get('short', '')}" for c in recent}
    valid_targets = category_targets | commit_targets
    pending_commits = {c.get("full", "") for c in recent} | {c.get("short", "") for c in recent}
    pending_commits.discard("")
    kept: list[dict[str, Any]] = []
    for marker in markers:
        target = marker.get("target_id") or "top"
        if target == "top":
            kept.append(marker)  # global marker stays valid while commits are still pending
            continue
        if target not in valid_targets:
            continue  # the category/commit this marker pointed at is no longer rendered
        commit = marker.get("commit") or ""
        if commit and commit not in pending_commits:
            continue  # target still exists but this exact commit has been implemented
        kept.append(marker)
    if len(kept) != len(markers):
        state["review_markers"] = kept


def update_official_release_cache(state: dict[str, Any], data: dict[str, Any]) -> None:
    """Cache the newest reachable official release for the #official tab.

    Lets #official keep showing the last official release notes after Hermes is
    updated and no newer release is reachable in HEAD..origin/main. Only writes
    when a release is currently reachable, so a GitHub fetch error or an
    up-to-date checkout preserves the existing cache. The stored payload is small
    and reference-only: it never feeds behind/category counts, risk text,
    #matters, raw commits, or history.
    """
    reachable = data.get("reachable_releases") or []
    if not reachable:
        return
    rel = reachable[0]
    cur = data.get("current_version") or {}
    state["last_official_release_notes"] = {
        "name": rel.get("name", ""),
        "tag_name": rel.get("tag_name", ""),
        "html_url": rel.get("html_url", ""),
        "published_at": rel.get("published_at", ""),
        "body_excerpt": rel.get("body_excerpt", ""),
        "highlights": rel.get("highlights", []),
        "commit": rel.get("commit", ""),
        "installed_raw": cur.get("raw", ""),
        "cached_at": data.get("generated_at", ""),
    }


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    state = load_state()
    data = collect()
    data["new_since_refresh"] = build_new_since_refresh(state, data)
    migrate_baseline_label(state, data)
    archive_if_head_advanced(state, data)
    prune_review_markers(state, data)
    migrate_history_version_labels(state, data)
    update_official_release_cache(state, data)
    state["last_generated_at"] = data["generated_at"]
    state["last_refresh_highlights"] = data.get("new_since_refresh", {})
    state["last_version_output"] = data.get("version_output", "")
    state["last_head"] = data.get("head", "")
    state["last_upstream"] = data.get("upstream", "")
    state["hermes_repo"] = str(REPO)
    save_state(state)
    stamp = data["generated_at"].replace(":", "").replace("+", "_")
    (RUNS / f"{stamp}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    HTML_PATH.write_text(render_page(data, state), encoding="utf-8")
    HISTORY_PATH.write_text(render_history(state), encoding="utf-8")
    print(str(HTML_PATH))


if __name__ == "__main__":
    main()
