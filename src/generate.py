#!/usr/bin/env python3
"""Generate Rex's local Hermes Release Radar pages.
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
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path.home() / ".hermes" / "release-radar"
REPO = Path.home() / ".hermes" / "hermes-agent"
STATE_PATH = ROOT / "state.json"
HTML_PATH = ROOT / "index.html"
HISTORY_PATH = ROOT / "history.html"
RUNS = ROOT / "runs"
GITHUB_RELEASES_API = "https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=8"


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sh(args: list[str], check: bool = True) -> str:
    r = subprocess.run(args, cwd=str(REPO), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{r.stdout}")
    return r.stdout.strip()


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        head = sh(["git", "rev-parse", "HEAD"])
        state = {
            "schema": 2,
            "hermes_repo": str(REPO),
            "baseline_commit": head,
            "baseline_label": "Initial Release Radar baseline",
            "review_markers": [],
            "history": [],
        }
    state.setdefault("schema", 2)
    state.setdefault("review_markers", [])
    state.setdefault("history", [])
    return state


def save_state(state: dict[str, Any]) -> None:
    state["schema"] = max(int(state.get("schema", 1)), 2)
    state["hermes_repo"] = str(REPO)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_version(text: str) -> dict[str, str]:
    first = (text or "").splitlines()[0] if text else ""
    m = re.search(r"Hermes Agent\s+(v[\w.\-]+)\s*\(([^)]+)\)", first)
    if not m:
        return {"raw": first or "unknown", "version": "unknown", "date": "unknown", "tag": ""}
    date = m.group(2)
    return {"raw": first, "version": m.group(1), "date": date, "tag": f"v{date}"}


def is_ancestor(older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    r = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=str(REPO))
    return r.returncode == 0


def rev_parse(ref: str) -> str:
    return sh(["git", "rev-parse", ref], check=False).splitlines()[-1].strip()


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
        c["file_count"] = len(c["files"])
        c["files"] = c["files"][:10]
    cat_counts, imp_counts = Counter(), Counter()
    category_commits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in commits:
        imp_counts[c["importance"]] += 1
        for cat in c["categories"]:
            cat_counts[cat] += 1
            category_commits[cat].append({k: c[k] for k in ["short", "full", "date", "subject", "importance"]})
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
    version_output = sh(["hermes", "--version"])
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


def build_release_notes(data: dict[str, Any]) -> dict[str, Any]:
    notes: list[dict[str, Any]] = []
    behind = data.get("behind", 0)
    high = data.get("importance_counts", {}).get("High", 0)
    dirty = bool(data.get("modified"))
    clusters = [
        ("Installability, update safety, and packaging", "Hermes is becoming easier to install/update and less heavy on first run. For your VM this matters because update failures and eager dependency downloads are annoying blast-radius multipliers.", ["update", "install", "postinstall", "wheel", "pypi", "camofox", "dependency", "deps", "uv ", "browser download", "lazy", "windows"], ["Install/dependencies"], ["PyPI/wheel/postinstall paths and lighter lazy dependency handling.", "Visible update/install progress instead of silent hangs.", "Security dependency bumps and supply-chain policy work."], "Update risk: medium-high. Do this as a planned checkpoint because your checkout has local edits and this area touches installation/update plumbing.", "warn"),
        ("Messaging and gateway reliability", "This is daily-use important because Telegram/voice/platform handoff is one of your core Hermes workflows. The cluster is about fewer dropped messages, better follow-ups, and platform failures not taking everything down.", ["gateway", "telegram", "discord", "whatsapp", "signal", "slack", "yuanbao", "line", "simplex", "clarify", "follow-up", "platform", "teams"], ["Gateway/platforms"], ["Per-platform isolation/circuit breakers and status visibility.", "Better rapid follow-up handling during active sessions.", "More platform adapters and richer message/attachment behavior."], "Update risk: medium. Worth it, but verify Telegram + TTS/STT + gateway after updating.", "good"),
        ("Models, OAuth providers, and local proxy", "This matters because provider weirdness is expensive. The release includes stronger OAuth/provider routing, xAI/Grok work, local proxy support, and sharper model/tool schema handling.", ["provider", "oauth", "xai", "grok", "deepseek", "moonshot", "copilot", "anthropic", "novita", "proxy", "openai-compatible", "reasoning"], ["Core agent/model routing"], ["xAI/Grok OAuth and 1M-context Grok path appear in the release notes.", "Local OpenAI-compatible proxy can let external coding tools use OAuth-backed providers.", "Provider error handling and schema compatibility improved."], "Update risk: medium. Test your normal provider and any OAuth flows after updating.", "good"),
        ("Agent tools: search, browser, video, vision, computer use", "This matters because Jarvis is only as useful as the tools it can safely call. The official release highlights more first-class tools and faster browser/tool paths.", ["tool", "x_search", "firecrawl", "image-gen", "video", "vision", "browser", "computer_use", "terminal", "web", "brave", "ddgs"], ["Tools/toolsets"], ["X/Twitter search becomes first-class.", "Vision/video/computer-use/web tooling is broader and more pluggable.", "Browser/tool calls get safety and performance fixes."], "Update risk: low-medium. Mostly additive, but smoke-test browser/tools.", "good"),
        ("Coding correctness: LSP, mutation verifier, patch/write safety", "This matters because you use Jarvis for real repo work. LSP diagnostics and mutation verification reduce the chance that an agent says it changed one thing but broke something else.", ["lsp", "diagnostic", "mutation", "write_file", "patch", "verifier", "semantic", "dangerous-command", "sanitize", "security"], ["Tools/toolsets", "Core agent/model routing"], ["Semantic diagnostics around writes/patches.", "Per-turn file mutation verification in the release notes.", "More dangerous-command and tool-error safety hardening."], "Update risk: low-medium. Safety/correctness improvements are attractive, but verify patch/write workflow.", "good"),
        ("Terminal/TUI daily-use polish", "This matters because you live in the terminal. The range has many fixes for scrolling, prompts, cursor behavior, markdown tables, background completion, and session deletion.", ["tui", "cli", "/exit", "cursor", "scroll", "markdown table", "notification", "doctor", "slash", "handoff"], ["CLI/TUI"], ["Cleaner exit/session deletion via `/exit --delete`.", "Better prompt scrolling/escape behavior and cursor handling.", "Clickable URLs and live handoff are highlighted in the official release."], "Update risk: low-medium. Mostly UX, but test your normal TUI loop.", "good"),
        ("Dashboard, Kanban, and web UI", "This matters when you use the local dashboard or Kanban. The current range looks more like polish and correctness than a giant dashboard feature wave.", ["dashboard", "web", "kanban", "config page", "analytics", "modal", "layout"], ["Dashboard/Web UI", "Kanban/multi-agent"], ["Kanban copy/Ready-state clarification.", "Dashboard config path and UI polish.", "Token/cost analytics hidden behind config by default."], "Update risk: low. Nice polish, not the main update reason by itself.", "neutral"),
        ("Skills and ecosystem", "This matters because skills are Jarvis's reusable muscle memory. The official release calls out 9 optional skills plus skills hub/Hugging Face tap work.", ["skill", "skills", "notion", "osint", "pinggy", "comfyui", "evm", "huggingface", "skills-hub"], ["Skills", "Docs"], ["New optional skills and better skill discovery/docs.", "Hugging Face skills tap support.", "Notion/OSINT/Pinggy/Darwinian/ComfyUI/EVM-related additions appear in this range."], "Update risk: low. Mostly additive unless you depend on a changed skill.", "neutral"),
        ("Cron and autonomous automation", "This matters because you use scheduled jobs. The range has smaller but practical improvements around cron lookup and environment handling.", ["cron", "job", "schedule", "wakeagent"], ["Cron/automation"], ["Name-based cron job operations.", "Gateway/home-target environment fixes.", "Safer async/thread bridge behavior that can affect background automation."], "Update risk: low-medium. Existing cron jobs should be smoke-tested after update.", "good"),
    ]
    reachable = data.get("reachable_releases", []) or []
    official_blob = " ".join(
        ((r.get("name") or "") + " " + (r.get("body_excerpt") or ""))
        for r in reachable
    ).lower()
    for title, why, needles, cats, changes, risk, tone in clusters:
        commits = select_commits(data, needles, cats)
        official_hit = bool(reachable) and any(n.strip().replace("_", " ") in official_blob for n in needles if n.strip())
        if commits or official_hit:
            card_changes = changes if official_hit else commit_subject_changes(commits)
            notes.append(release_note_card(title, why, card_changes, risk, commits, tone))
    if not notes:
        notes.append(release_note_card("No clear user-facing cluster detected", "The commit range mostly looks like internal maintenance from the current heuristics.", ["Raw commits are still listed below for inspection."], "Update risk: unknown; inspect raw commits before updating.", [], "neutral"))
    if behind == 0:
        recommendation = "You are up to date. No update decision needed."
    elif dirty:
        recommendation = f"Worth considering, but do not blind-update: {behind} commits are ahead and {high} are tagged high-impact, while local Hermes edits are present. Back up/checkpoint and review dirty files first."
    elif high >= 20:
        recommendation = f"Looks worth a planned update: {behind} commits ahead with {high} high-impact candidates. Do it as a checkpointed update, not casually mid-workflow."
    else:
        recommendation = f"Probably optional: {behind} commits ahead, but only {high} high-impact candidates detected. Review the cards and update when convenient."
    return {"recommendation": recommendation, "cards": notes}


def build_new_since_refresh(state: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Return commits that appeared since the previous upstream refresh.

    The previous upstream waterline lives in state.json as last_upstream. On each
    helper refresh, serve.py fetches origin and sets RELEASE_RADAR_REFRESH=1;
    this generator compares the old waterline to the newly collected origin/main.
    Non-refresh regenerations, such as marker saves or local code edits, preserve
    the last highlight set so the visible cue does not disappear until the next
    real Refresh from upstream action.
    """
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
        # visible highlights. Rex uses those as "what changed recently" cues
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


def render_official_release(data: dict[str, Any]) -> str:
    latest = data.get("latest_release") or {}
    if data.get("release_fetch_error"):
        return f'<section class="card warn"><h2>Official release notes</h2><p>Could not fetch GitHub release notes: {html.escape(data["release_fetch_error"])}</p></section>'
    cur = data.get("current_version", {})
    reachable = data.get("reachable_releases", []) or []
    if not reachable:
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
    highlights = rel.get("highlights") or []
    shown = "".join(
        f'<li><b>{html.escape(h.get("title", "Highlight"))}</b><br><span>{html.escape(strip_md(h.get("text", ""), 900))}</span></li>'
        for h in highlights
    ) or '<li>No parsed highlights in the latest GitHub release body.</li>'
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
    rel = build_release_notes(data)
    cards_html = []
    refresh = data.get("new_since_refresh", {}) or {}
    new_fulls = set(refresh.get("commit_fulls", []))
    new_card_count = 0
    for card in rel["cards"]:
        changes = "".join(f"<li>{html.escape(item)}</li>" for item in card["changes"])
        refs = commit_refs(card["commits"])
        refs_html = f'<div class="commit-ref-block"><div class="muted">Representative commits:</div><div class="commit-ref-row">{refs}</div></div>' if refs else ""
        commit_dates = sorted({c.get("date", "") for c in card.get("commits", []) if c.get("date")})
        if commit_dates:
            if len(commit_dates) == 1:
                date_html = f'<p class="card-date">Representative commit date: <time>{html.escape(commit_dates[-1])}</time></p>'
            else:
                date_html = f'<p class="card-date">Representative commit dates: <time>{html.escape(commit_dates[0])}</time> → <time>{html.escape(commit_dates[-1])}</time></p>'
        else:
            date_label = (data.get("latest_release", {}).get("published_at") or "")[:10] or "unknown"
            date_html = f'<p class="card-date">Release published: <time>{html.escape(date_label)}</time></p>'
        tone = html.escape(card.get("tone") or "neutral")
        is_new = bool(new_fulls and any(c.get("full") in new_fulls for c in card.get("commits", [])))
        if is_new:
            new_card_count += 1
        new_badge = '<span class="new-badge">● new this refresh</span>' if is_new else ""
        cards_html.append(
            f'<article class="release-card {tone}{" new-update" if is_new else ""}">'
            f'<div class="row spread"><h3>{html.escape(card["title"])}</h3>{new_badge}</div>'
            f'<p class="why">{html.escape(card["why"])}</p>'
            f'<ul>{changes}</ul>'
            f'<p class="risk">{html.escape(card["risk"])}</p>'
            f'{refs_html}'
            f'{date_html}'
            f'</article>'
        )
    if refresh.get("commit_count"):
        banner = f'<p class="new-refresh-banner"><b>{refresh.get("commit_count", 0)} new upstream commit(s)</b> since your last refresh. Highlighted cards/categories contain at least one of them.</p>'
    else:
        banner = '<p class="muted compact-note">No new upstream commits since the previous refresh.</p>'
    if new_card_count:
        banner += f'<p class="muted compact-note">{new_card_count} impact card(s) have fresh commits.</p>'
    return (
        '<section class="card release-notes">'
        '<div class="row"><h2>What actually matters</h2><span class="pill high">Rex-focused</span></div>'
        f'{banner}'
        f'<p class="recommendation">{html.escape(rel["recommendation"])}</p>'
        '<p class="muted">All impact cards are shown here. This combines official release notes with local commit/file heuristics; raw commits stay in the Raw categorized commits tab for auditability.</p>'
        f'<div id="impactGrid" class="release-grid">{"".join(cards_html)}</div>'
        '</section>'
    )


def render_markers_section(data: dict[str, Any], today_sv: str) -> str:
    return f'''<section class="card"><details><summary><h2>Review markers</h2><span class="muted">Hidden by default · use Mark all most of the time</span></summary><p class="muted">Server-side <code>state.json</code> is canonical. With the helper service online, marker buttons save to disk and regenerate this page.</p><div class="marker-controls"><input id="markerLabel" placeholder="Optional marker label"><button class="date-chip" title="Use today as marker label" onclick="useTodayLabel()">Use {today_sv}</button><button onclick="markAllCategories()">Mark all categories reviewed</button><button class="danger" onclick="clearMarkers()">Clear all markers</button></div><div id="topMarkerLine" class="section-marker" data-marker-slot="top"></div><div id="markers"></div><p id="newSince" class="muted"></p></details></section>'''


def render_page(data: dict[str, Any], state: dict[str, Any]) -> str:
    cats = sorted(data["category_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
    dirty = bool(data["modified"])
    verdict = "Review first" if data["behind"] else "Up to date"
    verdict_note = "Local edits" if dirty else ("Ready" if data["behind"] else "Clean")
    today_sv = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
    release_notes = render_release_notes(data)
    official = render_official_release(data)
    refresh = data.get("new_since_refresh", {}) or {}
    new_cat_counts = refresh.get("category_counts", {}) or {}
    new_fulls = set(refresh.get("commit_fulls", []))

    def render_cat_jump(cat: str, count: int) -> str:
        is_new = cat in new_cat_counts
        badge = f"<em class=\"jump-new\">+{new_cat_counts[cat]}</em>" if is_new else ""
        return (
            f'<a class="jump{" new-update" if is_new else ""}" href="#{anchor_id("cat", cat)}">'
            f'<span class="jump-label">{html.escape(cat)}</span>'
            f'<span class="jump-meta"><span class="jump-count">{count}</span>{badge}</span>'
            f'</a>'
        )

    cat_nav = "".join(render_cat_jump(cat, count) for cat, count in cats)

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
            f'<section id="{aid}" class="card category-card collapsed{" new-update" if new_count else ""}" data-marker-target="{aid}">'
            f'<div class="row spread"><h3>{html.escape(cat)} <span class="muted">{count}</span></h3><div class="row">{new_badge}'
            f'<button onclick="addMarker(\'{html.escape(cat)} reviewed\', \'{marker_commit}\', \'{aid}\')">Mark reviewed</button></div></div>'
            f'<div class="section-marker fallback-marker" data-marker-slot="{aid}"></div>'
            f'<ul class="category-commits">{rows}</ul>'
            f'<p class="row">{toggle}<a class="backtop" href="#top">Back to top</a></p></section>'
        )

    cat_cards = "\n".join(render_category(cat, count) for cat, count in cats)
    commits = "\n".join(
        f'<details id="commit-{c["short"]}" class="commit" data-marker-target="commit-{c["short"]}">'
        f'<summary><span class="pill {c["importance"].lower()}">{c["importance"]}</span> <code>{c["short"]}</code> {html.escape(c["subject"])} <span class="muted">{c["date"]}</span></summary>'
        f'<div class="section-marker" data-marker-slot="commit-{c["short"]}"></div>'
        f'<p>Categories: {html.escape(", ".join(c["categories"]))}</p>'
        f'<button onclick="addMarker(\'Reviewed through {c["short"]}\', \'{c["full"]}\', \'commit-{c["short"]}\')">Mark this commit reviewed</button>'
        f'<ul>' + "".join(f'<li>{html.escape(f)}</li>' for f in c["files"]) + '</ul></details>'
        for c in data["recent_commits"]
    )
    modified = "".join(f"<li><code>{html.escape(m)}</code></li>" for m in data["modified"]) or "<li>None</li>"
    version = data.get("current_version", {})
    latest = data.get("latest_release", {})
    history_count = len(state.get("history", []))
    page_state = {"review_markers": state.get("review_markers", []), "upstream": data.get("upstream", "") }
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Hermes Release Radar</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1014; --panel:#121a21; --text:#e7f0f4; --muted:#91a4af; --accent:#62e6c8; --warn:#ffc857; --bad:#ff6b6b; --line:#26343d; --marker:#62e6c8; }}
*{{box-sizing:border-box;min-width:0}} html{{scroll-behavior:smooth;overflow-x:hidden}} body{{margin:0;width:100%;max-width:100%;overflow-x:hidden;background:radial-gradient(circle at 15% 0,#18342f 0,#0b1014 34rem);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}} main{{width:100%;max-width:1180px;margin:auto;padding:18px;overflow-wrap:anywhere}} h1{{font-size:clamp(24px,6vw,32px);margin:0 0 4px}} h2{{margin:20px 0 9px}} h3{{margin:0}} a{{color:#a8e9ff}} code{{background:#0b1419;border:1px solid var(--line);border-radius:7px;padding:2px 6px;white-space:normal;overflow-wrap:anywhere;word-break:break-word}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;max-width:100%;overflow-x:auto}} button{{background:#183831;color:var(--text);border:1px solid #2b6d60;border-radius:10px;padding:8px 10px;cursor:pointer;max-width:100%;white-space:normal;text-align:left}} button:hover{{background:#205347}} summary{{cursor:pointer}} details>summary h2{{display:inline;margin-right:10px}} .danger{{background:#3a1b22;border-color:#7d3543}} .status-badge{{display:inline-flex;align-items:center;border-radius:999px;padding:4px 10px;border:1px solid var(--line);font-weight:700}} .status-badge.online{{background:#123a2e;color:#7ff6d7;border-color:#2b8a71}} .status-badge.offline{{background:#3a1b22;color:#ffb3b3;border-color:#7d3543}} .openlink{{display:inline-flex;align-items:center;min-height:34px;padding:0 10px;border:1px solid #315a7e;border-radius:10px;background:#102239;color:#d9ecff;text-decoration:none}} .topbar{{border-bottom:1px solid var(--line);background:#0b1014aa;position:sticky;top:0;z-index:2;backdrop-filter:blur(8px)}} .topbar main{{padding:8px 18px}} .navlinks a{{margin-left:10px;text-decoration:none}} .navlinks .help-icon{{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border:1px solid #315a7e;border-radius:999px;background:#102239;color:#d9ecff;font-weight:900;line-height:1}} .helperbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;background:#0e171d;border:1px solid #21313b;border-radius:14px;padding:10px 12px;margin:0 0 12px;box-shadow:0 8px 20px #0003}} .helperbar p{{margin:2px 0 0}} .helper-actions{{display:flex;gap:8px;flex-wrap:wrap}} .tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 8px;position:sticky;top:48px;z-index:1;background:#0b1014cc;padding:8px 0;backdrop-filter:blur(8px)}} .tabbtn{{background:#0e171d;border-color:var(--line);font-weight:800}} .tabbtn.active{{background:#183831;border-color:#2b8a71;color:#dffbf5}} .tab-panel{{display:none}} .tab-panel.active{{display:block}} .summary-strip{{display:grid;grid-template-columns:1.1fr repeat(5,.65fr);gap:8px;margin:8px 0 12px}} .summary-item{{background:#101820;border:1px solid #21313b;border-radius:12px;padding:8px 10px;min-height:56px;display:flex;flex-direction:column;justify-content:center;box-shadow:0 8px 20px #0003}} .summary-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}} .summary-value{{font-size:17px;font-weight:800;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}} .summary-value code{{font-size:15px;padding:1px 5px}} .summary-sub{{font-size:12px;color:#ffc857;margin-top:2px}} @media(max-width:960px){{.summary-strip{{grid-template-columns:repeat(3,1fr)}}}} @media(max-width:560px){{.summary-strip{{grid-template-columns:repeat(2,1fr)}}}} .card,.commit{{background:linear-gradient(180deg,var(--panel),#10171d);border:1px solid var(--line);border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 12px 30px #0005;width:100%;max-width:100%;overflow:hidden}} .muted{{color:var(--muted)}} .row{{display:flex;gap:10px;align-items:center;justify-content:flex-start;flex-wrap:wrap}} .spread{{justify-content:space-between}} .jumpgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr));gap:8px;align-items:start}} .jump{{display:flex;align-items:center;justify-content:space-between;gap:10px;text-decoration:none;background:#0e171d;border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-height:44px;line-height:1.2}} .jump-label{{font-weight:650;overflow-wrap:normal;word-break:normal;hyphens:none}} .jump-meta{{display:inline-flex;align-items:center;justify-content:flex-end;gap:6px;flex:0 0 auto;white-space:nowrap}} .jump-count{{font-weight:750}} .warn{{border-color:#7a5b20}} .pill{{border-radius:999px;padding:2px 8px;border:1px solid var(--line);font-size:12px}} .pill.high{{background:#3a2b12;color:#ffd98a}} .pill.medium{{background:#1d3042;color:#b9ddff}} .pill.low{{background:#172317;color:#b8f0be}} .marker-controls{{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}} input{{background:#0b1419;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:9px 10px;min-width:min(280px,100%)}} .marker{{display:flex;justify-content:space-between;gap:8px;align-items:center;border:1px solid var(--line);border-radius:12px;padding:8px;margin:7px 0;background:#0e171d}} .section-marker{{display:none}} .section-marker.visible,.inserted-marker{{display:block;margin:12px 0}} .marker-line{{border:0;border-top:2px solid var(--marker)}} .inline-marker-row{{display:flex;gap:8px;justify-content:space-between;align-items:center;flex-wrap:wrap;background:#0c2722;border:1px solid #276e61;border-radius:12px;padding:8px}} .category-card.collapsed .category-commits li.extra,#markers.collapsed .marker.extra{{display:none}} .showmore{{background:#102239;border-color:#315a7e}} .category-commits li,.highlight-list li{{margin:7px 0}} .release-notes,.official-release{{border-color:#315a7e;background:linear-gradient(180deg,#111d27,#0f171d)}} .recommendation{{font-size:17px;font-weight:800;color:#dffbf5}} .release-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(330px,100%),1fr));gap:12px;align-items:start}} .release-card{{background:#0e171d;border:1px solid var(--line);border-radius:14px;padding:13px;display:flex;flex-direction:column}} .release-card.good{{border-color:#2b6d60}} .release-card.warn{{border-color:#8a6a2d}} .release-card h3{{margin-bottom:8px}} .release-card .why{{color:#dce9ee}} .release-card .risk{{color:#ffd98a;font-weight:650;margin:12px 0 10px}} .commit-ref-block{{margin:8px 0 10px}} .commit-ref-row{{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px}} .card-date{{margin:8px 0 0;padding-top:8px;color:#91a4af;font-size:12px;border-top:1px solid #1f2d35}} .card-date time{{color:#c7d7de}} .new-refresh-banner{{margin:8px 0 10px;padding:8px 10px;border:1px solid #9b7b29;border-radius:12px;background:#211a0b;color:#ffe3a1}} .compact-note{{margin:4px 0 8px}} .new-badge{{display:inline-flex;align-items:center;gap:4px;border:1px solid #9b7b29;border-radius:999px;background:#221907;color:#ffe08a;font-size:12px;font-weight:800;padding:2px 8px;white-space:nowrap}} .release-card.new-update{{border-color:var(--line);box-shadow:none}} .category-card.new-update{{border-color:#c9942e;box-shadow:0 0 0 1px #c9942e66,0 0 22px #c9942e22}} .jump.new-update{{border-color:#c9942e;background:#201707;color:#ffe7a8;font-weight:800}} .jump-new{{font-style:normal;border-radius:999px;background:#3b2a09;color:#ffe08a;border:1px solid #68480b;padding:1px 6px;line-height:1.25;min-width:0}} .category-commits li.new-commit{{background:#201707;border-left:3px solid #c9942e;border-radius:8px;padding:5px 7px}} .new-dot{{display:inline-block;margin-left:6px;border-radius:999px;background:#3b2a09;color:#ffe08a;border:1px solid #9b7b29;font-size:11px;font-weight:800;padding:1px 6px}} .highlight-list{{padding-left:20px}} .version-line{{font-size:16px}}
</style></head><body>
<div id="top" class="topbar"><main class="row spread"><strong>Hermes Release Radar</strong><span class="navlinks"><a href="index.html">Current</a><a href="history.html">History ({history_count})</a><a class="help-icon" href="help.html" title="Help / setup commands" aria-label="Help / setup commands">?</a></span></main></div>
<main>
<h1>Hermes Release Radar</h1><p class="muted">Generated {html.escape(data['generated_at'])} from {html.escape(data['repo'])}</p>
<section class="summary-strip" aria-label="Release radar summary">
<div class="summary-item status-item"><div class="summary-label">Status</div><div class="summary-value"><span id="helperStatus" class="status-badge offline">Checking…</span></div><div class="summary-sub">{html.escape(verdict)} · {html.escape(verdict_note)}</div></div>
<div class="summary-item"><div class="summary-label">Installed</div><div class="summary-value">{html.escape(version.get('version','?'))}</div><div class="summary-sub">{html.escape(version.get('date',''))}</div></div>
<div class="summary-item"><div class="summary-label">Latest</div><div class="summary-value">{html.escape((latest.get('name') or latest.get('tag_name') or '?').replace('Hermes Agent ',''))}</div></div>
<div class="summary-item"><div class="summary-label">Behind</div><div class="summary-value">{data['behind']}</div></div>
<div class="summary-item"><div class="summary-label">High impact</div><div class="summary-value">{data['importance_counts'].get('High',0)}</div></div>
<div class="summary-item"><div class="summary-label">Upstream</div><div class="summary-value"><code>{data['upstream'][:10]}</code></div></div>
</section>
<section class="helperbar"><div><b>Local helper service</b><p id="helperDetail" class="muted">Checking local-only service on <code>127.0.0.1:8765</code>.</p></div><div class="helper-actions"><button class="refresh" onclick="refreshRadar()">Refresh from upstream</button><button onclick="checkHelperStatus()">Check status</button><a class="openlink" href="http://127.0.0.1:8765/">Open service</a></div></section>
<nav class="tabs" aria-label="Release radar sections"><button class="tabbtn active" onclick="switchTab('official', this)">Official release notes</button><button class="tabbtn" onclick="switchTab('matters', this)">What actually matters</button><button class="tabbtn" onclick="switchTab('raw', this)">Raw categorized commits</button></nav>
<section id="tab-official" class="tab-panel active">{official}</section>
<section id="tab-matters" class="tab-panel">{release_notes}</section>
<section id="tab-raw" class="tab-panel">
<section class="card"><h2>Jump to category</h2><p class="muted">Raw commit groups are here for auditability. The tabs above keep the page lean without hiding the data.</p><div class="jumpgrid">{cat_nav}</div></section>
<section class="card warn"><h2>Update safety note</h2><p>This page only inspected git/release data. It did not install, update, restart, reset, stash, or modify Hermes source.</p><p>Local modified files detected:</p><ul>{modified}</ul></section>
{render_markers_section(data, today_sv)}
<section class="card"><h2>Current installed state</h2><pre>{html.escape(data['version_output'])}\n{html.escape(data['status'])}</pre><p>Baseline checkpoint: <code>{html.escape(state.get('baseline_commit','')[:12])}</code> — {html.escape(state.get('baseline_label',''))}</p></section>
<h2>Raw categorized commits</h2>{cat_cards}
<h2>Recent upstream commits</h2><p class="muted">Showing the newest {len(data['recent_commits'])} commits from HEAD..origin/main.</p>{commits}
</section>
</main>
<script>
const DATA = {{}};
const STATE = {js_data(page_state)};
const HELPER = 'http://127.0.0.1:8765';
const TODAY_LABEL = '{today_sv}';
let helperOnline = false;
let MARKERS = Array.isArray(STATE.review_markers) ? [...STATE.review_markers] : [];
const CATEGORY_TARGETS = {js_data([{ "id": anchor_id("cat", cat), "label": cat, "commit": (data["category_commits"].get(cat, [{}])[0].get("full") or data["upstream"]) } for cat, _count in cats])};
function getMarkers() {{ return MARKERS; }}
async function saveMarkers(ms) {{
  MARKERS = ms; renderMarkers();
  if (!helperOnline) {{ setHelperStatus(false, 'Helper is offline. Marker changes are visible only until reload.'); return; }}
  try {{
    const res = await fetch(`${{HELPER}}/api/markers`, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{review_markers: MARKERS}})}});
    const payload = await res.json().catch(() => ({{}}));
    if (!res.ok || !payload.ok) throw new Error(payload.error || await res.text());
    setHelperStatus(true, 'Markers saved to state.json and page regenerated. Reload to view regenerated HTML.');
  }} catch (err) {{ setHelperStatus(false, `Could not save markers to helper: ${{err.message || err}}`); }}
}}
function setHelperStatus(ok, detail) {{ helperOnline = !!ok; const badge = document.getElementById('helperStatus'); const text = document.getElementById('helperDetail'); if (badge) {{ badge.className = `status-badge ${{ok ? 'online' : 'offline'}}`; badge.textContent = ok ? 'Online' : 'Offline'; }} if (text) text.textContent = detail || (ok ? 'Helper is online.' : 'Helper is offline.'); }}
async function checkHelperStatus() {{ try {{ const res = await fetch(`${{HELPER}}/api/status`, {{cache:'no-store'}}); const payload = await res.json(); if (!res.ok || !payload.ok) throw new Error(payload.error || 'status failed'); setHelperStatus(true, `Online · markers: ${{payload.marker_count}} · last generated: ${{payload.last_generated_at || 'unknown'}} · ${{payload.index_path}}`); }} catch (err) {{ setHelperStatus(false, 'Offline. Refresh and durable marker saves need hermes-release-radar.service running.'); }} }}
function addMarker(label, commit, targetId) {{ const input = document.getElementById('markerLabel'); const finalLabel = (input && input.value.trim()) || label || 'Reviewed marker'; const target = targetId || 'top'; const ms = getMarkers().filter(m => (m.target_id || 'top') !== target); ms.unshift({{ id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())), label: finalLabel, commit, target_id: target, created_at: new Date().toISOString() }}); if (input) input.value = ''; saveMarkers(ms); }}
function useTodayLabel() {{ const input = document.getElementById('markerLabel'); if (input) input.value = TODAY_LABEL; }}
function markAllCategories() {{ const input = document.getElementById('markerLabel'); const labelText = (input && input.value.trim()) || TODAY_LABEL; const suffix = labelText ? ` — ${{labelText}}` : ''; const existing = getMarkers().filter(m => !CATEGORY_TARGETS.some(c => c.id === (m.target_id || 'top'))); const now = new Date().toISOString(); const added = CATEGORY_TARGETS.map(c => ({{ id: (crypto.randomUUID ? crypto.randomUUID() : `${{Date.now()}}-${{c.id}}`), label: `${{c.label}} reviewed${{suffix}}`, commit: c.commit, target_id: c.id, created_at: now }})); if (input) input.value = ''; saveMarkers([...added, ...existing]); }}
function deleteMarker(id) {{ saveMarkers(getMarkers().filter(m => m.id !== id)); }}
function clearMarkers() {{ if (confirm('Clear all review markers for this page?')) saveMarkers([]); }}
async function refreshRadar() {{ try {{ setHelperStatus(true, 'Refreshing: git fetch origin --quiet + regenerate page…'); const activeHash = location.hash || '#official'; const res = await fetch(`${{HELPER}}/api/refresh`, {{method:'POST'}}); const payload = await res.json().catch(() => ({{}})); if (!res.ok || !payload.ok) throw new Error(payload.error || await res.text()); location.href = `${{HELPER}}/?t=${{Date.now()}}${{activeHash}}`; }} catch (err) {{ setHelperStatus(false, `Refresh failed or helper is offline: ${{err.message || err}}`); alert('Refresh needs the local helper service: hermes-release-radar.service'); }} }}
function toggleCategory(id) {{ const section = document.getElementById(id); if (!section) return; section.classList.toggle('collapsed'); const btn = section.querySelector('.showmore'); if (btn) btn.textContent = section.classList.contains('collapsed') ? btn.dataset.showLabel : btn.dataset.hideLabel; }}
function toggleBlock(id, btn) {{ const el = document.getElementById(id); if (!el) return; el.classList.toggle('collapsed'); if (btn && btn.dataset) btn.textContent = el.classList.contains('collapsed') ? btn.dataset.showLabel : btn.dataset.hideLabel; }}
function toggleMarkerList(btn) {{ const el = document.getElementById('markers'); if (!el) return; el.classList.toggle('collapsed'); if (btn && btn.dataset) btn.textContent = el.classList.contains('collapsed') ? btn.dataset.showLabel : btn.dataset.hideLabel; }}
function switchTab(name, btn) {{ document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${{name}}`)); document.querySelectorAll('.tabbtn').forEach(b => b.classList.toggle('active', b === btn)); if (history.replaceState) history.replaceState(null, '', `#${{name}}`); }}
function activateInitialTab() {{ const name = (location.hash || '#official').slice(1); const btn = [...document.querySelectorAll('.tabbtn')].find(b => b.getAttribute('onclick')?.includes(`'${{name}}'`)); if (btn) switchTab(name, btn); }}
function renderMarkers() {{ const el = document.getElementById('markers'); const ns = document.getElementById('newSince'); const ms = getMarkers(); document.querySelectorAll('[data-marker-slot]').forEach(slot => {{ slot.classList.remove('visible'); slot.innerHTML = ''; }}); document.querySelectorAll('.inserted-marker').forEach(node => node.remove()); if (!ms.length) {{ if(el) el.innerHTML = '<p class="muted">No review markers yet.</p>'; if(ns) ns.textContent = 'Everything above your first marker will count as new to your eyes.'; return; }} const latestByTarget = new Map(); ms.slice().reverse().forEach(m => latestByTarget.set(m.target_id || 'top', m)); latestByTarget.forEach((m, targetId) => {{ const section = document.getElementById(targetId); const markHtml = `<div class="section-marker visible inserted-marker"><hr class="marker-line"><div class="inline-marker-row"><span class="marker-label">Reviewed through here: ${{escapeHtml(m.label)}} · ${{new Date(m.created_at).toLocaleString()}}</span><button class="danger" onclick="deleteMarker('${{m.id}}')">Clear marker</button></div></div>`; if (section && section.classList.contains('category-card')) {{ const match = section.querySelector(`li[data-commit="${{cssEscape(m.commit || '')}}"]`); if (match) match.insertAdjacentHTML('beforebegin', markHtml); else {{ const slot = section.querySelector(`[data-marker-slot="${{cssEscape(targetId)}}"]`); if (slot) {{ slot.classList.add('visible'); slot.innerHTML = markHtml; }} }} return; }} const slot = document.querySelector(`[data-marker-slot="${{cssEscape(targetId)}}"]`); if (slot) {{ slot.classList.add('visible'); slot.innerHTML = markHtml; }} }}); if(el) {{ const rows = ms.map((m,i) => `<div class="marker ${{i >= 4 ? 'extra' : ''}}"><div><b>${{escapeHtml(m.label)}}</b><br><span class="muted">${{new Date(m.created_at).toLocaleString()}} · <code>${{(m.commit || 'unknown').slice(0,12)}}</code> · <a class="backtop" href="#${{escapeHtml(m.target_id || 'top')}}">jump</a></span></div><button class="danger" onclick="deleteMarker('${{m.id}}')">Clear marker</button></div>`).join(''); const btn = ms.length > 4 ? `<button class="showmore" onclick="toggleMarkerList(this)" data-show-label="Show all ${{ms.length}} markers" data-hide-label="Show fewer markers">Show all ${{ms.length}} markers</button>` : ''; el.classList.add('collapsed'); el.innerHTML = rows + btn; }} if(ns) ns.innerHTML = `Last review marker: <code>${{(ms[0].commit || 'unknown').slice(0,12)}}</code>. Newer upstream top now: <code>${{(STATE.upstream || 'unknown').slice(0,12)}}</code>.`; }}
function cssEscape(s) {{ return String(s).replace(/[^a-zA-Z0-9_-]/g, ''); }}
function escapeHtml(s) {{ return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
activateInitialTab(); window.addEventListener('hashchange', activateInitialTab); renderMarkers(); checkHelperStatus();
</script></body></html>"""


def render_history(state: dict[str, Any]) -> str:
    entries = list(reversed(state.get("history", [])))
    if not entries:
        body = '<section class="card"><h2>No installed-update history yet</h2><p class="muted">After Hermes local HEAD advances beyond the stored baseline, Release Radar will archive the installed range here and reset the main page to only future upstream commits.</p></section>'
    else:
        cards = []
        for idx, h in enumerate(entries):
            cats = h.get("category_counts", {})
            cat_text = ", ".join(f"{html.escape(k)}: {v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])[:8])
            rels = h.get("releases", [])
            rel_html = "".join(f'<li><a href="{html.escape(r.get("html_url", "#"))}">{html.escape(r.get("name") or r.get("tag_name") or "release")}</a></li>' for r in rels) or "<li>No official release tag detected inside this installed range.</li>"
            top_commits = "".join(f'<li><code>{html.escape(c.get("short",""))}</code> {html.escape(c.get("subject",""))}</li>' for c in h.get("commits", [])[:25])
            cards.append(f'''<section class="card"><h2>{html.escape(h.get('from_version','unknown'))} → {html.escape(h.get('to_version','unknown'))}</h2><p class="muted">Archived {html.escape(h.get('archived_at',''))} · {h.get('commit_count',0)} installed commits · <code>{html.escape(h.get('old_baseline','')[:12])}</code> → <code>{html.escape(h.get('new_baseline','')[:12])}</code></p><details open><summary>Official releases in this installed range</summary><ul>{rel_html}</ul></details><p><b>Category mix:</b> {cat_text or 'none'}</p><details><summary>Top installed commits</summary><ul>{top_commits}</ul></details></section>''')
        body = "\n".join(cards)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Hermes Release Radar History</title><style>:root{{color-scheme:dark;--bg:#0b1014;--panel:#121a21;--text:#e7f0f4;--muted:#91a4af;--line:#26343d}}*{{box-sizing:border-box}}body{{margin:0;background:#0b1014;color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:1100px;margin:auto;padding:18px}}a{{color:#a8e9ff}}code{{background:#0b1419;border:1px solid var(--line);border-radius:7px;padding:2px 6px}}.topbar{{border-bottom:1px solid var(--line);background:#0b1014cc;position:sticky;top:0}}.topbar main{{display:flex;justify-content:space-between;padding:8px 18px}}.card{{background:linear-gradient(180deg,var(--panel),#10171d);border:1px solid var(--line);border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 12px 30px #0005}}.muted{{color:var(--muted)}}summary{{cursor:pointer}}</style></head><body><div class="topbar"><main><strong>Hermes Release Radar History</strong><span><a href="index.html">Current</a></span></main></div><main><h1>Installed update history</h1><p class="muted">This is the archive of commits that became installed checkpoints. It is separate from review markers.</p>{body}</main></body></html>'''


def archive_if_head_advanced(state: dict[str, Any], data: dict[str, Any]) -> None:
    baseline = state.get("baseline_commit") or ""
    head = data["head"]
    if not baseline:
        state["baseline_commit"] = head
        state["baseline_label"] = data.get("current_version", {}).get("raw", "Initial baseline")
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
        state["baseline_label"] = new_version.get("raw", f"Checkpoint {head[:12]}")
        state["review_markers"] = []
        state["checkpoint_notice"] = f"Archived {len(commits)} installed commits into history and moved baseline to {head[:12]}."
    else:
        state["checkpoint_warning"] = f"Stored baseline {baseline[:12]} is not an ancestor of current HEAD {head[:12]}; not auto-archiving. Manual checkpoint review needed."


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    state = load_state()
    data = collect()
    data["new_since_refresh"] = build_new_since_refresh(state, data)
    archive_if_head_advanced(state, data)
    state["last_generated_at"] = data["generated_at"]
    state["last_refresh_highlights"] = data.get("new_since_refresh", {})
    state["last_version_output"] = data.get("version_output", "")
    state["last_head"] = data["head"]
    state["last_upstream"] = data["upstream"]
    state["hermes_repo"] = str(REPO)
    save_state(state)
    stamp = data["generated_at"].replace(":", "").replace("+", "_")
    (RUNS / f"{stamp}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    HTML_PATH.write_text(render_page(data, state), encoding="utf-8")
    HISTORY_PATH.write_text(render_history(state), encoding="utf-8")
    print(str(HTML_PATH))


if __name__ == "__main__":
    main()
