#!/usr/bin/env python3
"""Generate the public GitHub Pages demo for Hermes Release Radar.

This is intentionally separate from the local/private generator in generate.py.
It reads only a public Hermes Agent git checkout and GitHub release metadata, then
writes static public artifacts. It never reads ~/.hermes/release-radar/state.json,
review markers, helper service status, local runtime paths, or Rex's installed
checkout state.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Reuse deterministic classification/release helpers, but do not reuse the local
# render path because that path intentionally includes private runtime controls.
import generate as local_generator

DEFAULT_HERMES_REPO = Path(".cache/hermes-agent")
DEFAULT_OUTPUT_DIR = Path("public")
PUBLIC_GITHUB_RELEASES = "https://github.com/NousResearch/hermes-agent/releases"
PUBLIC_HERMES_REPO = "https://github.com/NousResearch/hermes-agent"
PRIVACY_FORBIDDEN_SUBSTRINGS = [
    "/home/",
    "~/.hermes/release-radar/state.json",
    "review_markers",
    "127.0.0.1:8765/api",
    "api/status",
    "api/refresh",
    "api/markers",
    "hermes_repo",
]


def sh(repo: Path, args: list[str], check: bool = True) -> str:
    result = subprocess.run(args, cwd=str(repo), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed in {repo}: {' '.join(args)}\n{result.stdout}")
    return result.stdout.strip()


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def commit_for_ref(repo: Path, ref: str) -> str:
    out = sh(repo, ["git", "rev-parse", f"{ref}^{{}}"], check=False)
    if "fatal:" in out.lower() or not out:
        return ""
    return out.splitlines()[-1].strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    result = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=str(repo))
    return result.returncode == 0


def latest_reachable_release(repo: Path, releases: list[dict[str, Any]], upstream: str) -> dict[str, Any]:
    for rel in releases:
        if rel.get("error"):
            continue
        tag = rel.get("tag_name") or ""
        commit = commit_for_ref(repo, tag)
        if commit and is_ancestor(repo, commit, upstream):
            item = dict(rel)
            item["commit"] = commit
            return item
    return {}


def collect_public_data(hermes_repo: Path) -> dict[str, Any]:
    if not (hermes_repo / ".git").exists():
        raise RuntimeError(f"Hermes repo checkout not found: {hermes_repo}")

    # Point imported helper functions at the public checkout for this process.
    local_generator.REPO = hermes_repo.resolve()

    upstream = sh(hermes_repo, ["git", "rev-parse", "origin/main"])
    releases = local_generator.fetch_github_releases()
    latest = latest_reachable_release(hermes_repo, releases, upstream) if releases and not releases[0].get("error") else {}
    base = latest.get("commit") or sh(hermes_repo, ["git", "rev-list", "--max-count=1", "origin/main"])
    rev_range = f"{base}..origin/main"
    commits, cat_counts, imp_counts, category_commits = local_generator.collect_commits(rev_range)
    if not commits:
        commits, cat_counts, imp_counts, category_commits = local_generator.collect_commits("origin/main")
        commits = commits[:30]
        keep = {c.get("full") for c in commits}
        category_commits = {
            cat: [entry for entry in entries if entry.get("full") in keep]
            for cat, entries in category_commits.items()
        }
        cat_counts = {cat: len(entries) for cat, entries in category_commits.items() if entries}
        imp_counts = {}
        for c in commits:
            imp_counts[c.get("importance", "Unknown")] = imp_counts.get(c.get("importance", "Unknown"), 0) + 1
        comparison_label = "Latest upstream commits"
    else:
        comparison_label = f"origin/main since {latest.get('tag_name') or base[:12]}"
    return {
        "generated_at": now_iso(),
        "upstream": upstream,
        "latest_release": latest,
        "release_fetch_error": releases[0].get("error") if releases and releases[0].get("error") else "",
        "comparison_label": comparison_label,
        "commit_count": len(commits),
        "category_counts": cat_counts,
        "importance_counts": imp_counts,
        "category_commits": category_commits,
        "recent_commits": commits,
    }


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def render_official(data: dict[str, Any]) -> str:
    if data.get("release_fetch_error"):
        return f"<section class='card warn'><h2>Official release metadata</h2><p>Could not fetch GitHub releases: {esc(data['release_fetch_error'])}</p></section>"
    latest = data.get("latest_release") or {}
    if not latest:
        return "<section class='card'><h2>Official release metadata</h2><p>No reachable GitHub release tag was found in the public Hermes Agent checkout.</p></section>"
    highlights = latest.get("highlights") or []
    highlight_html = "".join(
        f"<li><b>{esc(h.get('title') or 'Highlight')}</b><br><span>{esc(local_generator.strip_md(h.get('text') or '', 900))}</span></li>"
        for h in highlights[:12]
    ) or "<li>No parsed highlights were available in the latest release body.</li>"
    return (
        "<section class='card official-release'>"
        "<div class='row spread'><h2>Latest official Hermes release</h2><span class='pill'>GitHub</span></div>"
        f"<p><b>{esc(latest.get('name') or latest.get('tag_name') or 'unknown')}</b> · "
        f"published {esc((latest.get('published_at') or '')[:10] or 'unknown')} · "
        f"<a href='{esc(latest.get('html_url') or PUBLIC_GITHUB_RELEASES)}'>open release</a></p>"
        f"<ul class='highlight-list'>{highlight_html}</ul>"
        "</section>"
    )


def build_public_cards(data: dict[str, Any]) -> list[dict[str, Any]]:
    clusters = [
        ("Install/update and packaging", ["update", "install", "pypi", "wheel", "dependency", "deps", "postinstall"], ["Install/dependencies"]),
        ("Gateway and messaging", ["gateway", "telegram", "discord", "slack", "signal", "platform", "voice", "tts", "stt"], ["Gateway/platforms"]),
        ("Models and provider routing", ["provider", "model", "oauth", "proxy", "openai", "anthropic", "xai", "grok", "schema"], ["Core agent/model routing"]),
        ("Tools and browser/media capabilities", ["tool", "browser", "web", "vision", "video", "computer_use", "search", "terminal"], ["Tools/toolsets"]),
        ("TUI/CLI workflow", ["tui", "cli", "slash", "cursor", "session", "doctor", "handoff"], ["CLI/TUI"]),
        ("Dashboard, Kanban, and web UI", ["dashboard", "web", "kanban", "ui", "analytics", "config"], ["Dashboard/Web UI", "Kanban/multi-agent"]),
        ("Skills, docs, and ecosystem", ["skill", "skills", "docs", "readme", "notion", "comfyui", "huggingface"], ["Skills", "Docs"]),
        ("Cron and automation", ["cron", "schedule", "job", "automation", "wakeagent"], ["Cron/automation"]),
    ]
    cards: list[dict[str, Any]] = []
    for title, needles, categories in clusters:
        commits = local_generator.select_commits(data, needles, categories, limit=8)
        if not commits:
            continue
        cards.append({"title": title, "commits": commits, "changes": local_generator.commit_subject_changes(commits, 5)})
    if not cards:
        cards.append({"title": "Recent upstream activity", "commits": data.get("recent_commits", [])[:8], "changes": local_generator.commit_subject_changes(data.get("recent_commits", []), 5)})
    return cards


def render_public_cards(data: dict[str, Any]) -> str:
    cards = []
    for card in build_public_cards(data):
        changes = "".join(f"<li>{esc(item)}</li>" for item in card["changes"])
        refs = "".join(f"<code>{esc(c.get('short'))}</code>" for c in card.get("commits", []))
        dates = sorted({c.get("date", "") for c in card.get("commits", []) if c.get("date")})
        date_line = ""
        if dates:
            date_line = f"<p class='muted'>Representative dates: {esc(dates[0])}" + (f" → {esc(dates[-1])}" if len(dates) > 1 else "") + "</p>"
        cards.append(
            "<article class='release-card'>"
            f"<h3>{esc(card['title'])}</h3>"
            f"<ul>{changes}</ul>"
            f"<div class='commit-ref-row'>{refs}</div>"
            f"{date_line}"
            "</article>"
        )
    return "<section class='card'><div class='row'><h2>What the public demo can show</h2><span class='pill'>static</span></div><p class='muted'>These cards summarize public upstream activity only. They are not personalized update advice.</p><div class='release-grid'>" + "".join(cards) + "</div></section>"


def render_raw(data: dict[str, Any]) -> str:
    cats = sorted((data.get("category_counts") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    if not cats:
        return "<section class='card'><h2>Raw categorized commits</h2><p>No commits in the selected public comparison range.</p></section>"
    chunks = []
    for cat, count in cats:
        rows = "".join(
            f"<li><b>{esc(entry.get('importance'))}</b> <code>{esc(entry.get('short'))}</code> <span class='muted'>{esc(entry.get('date'))}</span> {esc(entry.get('subject'))}</li>"
            for entry in (data.get("category_commits") or {}).get(cat, [])
        )
        chunks.append(f"<details class='card category-card'><summary><h3>{esc(cat)} <span class='muted'>{count}</span></h3></summary><ul>{rows}</ul></details>")
    return "<section><h2>Raw categorized commits</h2>" + "".join(chunks) + "</section>"


def render_page(data: dict[str, Any]) -> str:
    icon = local_generator.APP_ICON_SVG
    favicon = local_generator.FAVICON_DATA
    latest = data.get("latest_release") or {}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Hermes Release Radar — Public Demo</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{favicon}">
<style>
:root{{color-scheme:dark;--bg:#0b1014;--panel:#121a21;--text:#e7f0f4;--muted:#91a4af;--accent:#62e6c8;--warn:#ffc857;--line:#26343d}}
*{{box-sizing:border-box;min-width:0}}html{{overflow-x:hidden}}body{{margin:0;width:100%;max-width:100%;overflow-x:hidden;background:radial-gradient(circle at 15% 0,#18342f 0,#0b1014 34rem);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}main{{width:100%;max-width:1180px;margin:auto;padding:18px;overflow-wrap:anywhere}}a{{color:#a8e9ff}}code{{background:#0b1419;border:1px solid var(--line);border-radius:7px;padding:2px 6px;white-space:normal;overflow-wrap:anywhere}}.topbar{{border-bottom:1px solid var(--line);background:#0b1014cc;position:sticky;top:0;z-index:2;backdrop-filter:blur(8px)}}.topbar main{{padding:8px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px}}.brand{{display:inline-flex;align-items:center;gap:9px;font-weight:800;color:var(--text);text-decoration:none}}.brand .app-icon{{width:30px;height:30px;filter:drop-shadow(0 0 10px #62e6c833)}}.card,.category-card{{background:linear-gradient(180deg,var(--panel),#10171d);border:1px solid var(--line);border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 12px 30px #0005}}.warning{{border-color:#8a6930;background:linear-gradient(180deg,#251f13,#15120d)}}.muted{{color:var(--muted)}}.row{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.spread{{justify-content:space-between}}.summary-strip{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr));gap:10px;margin:14px 0}}.summary-item{{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0f171d}}.summary-label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}.summary-value{{font-size:22px;font-weight:800}}.pill{{display:inline-flex;border:1px solid #2b6d60;border-radius:999px;padding:3px 9px;color:#9ff3de;background:#123a2e;font-weight:700;font-size:12px}}.release-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:12px;align-items:start}}.release-card{{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0f171d}}.commit-ref-row{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}.highlight-list li{{margin:8px 0}}summary{{cursor:pointer}}summary h3{{display:inline}}ul{{padding-left:21px}}li{{margin:5px 0}}footer{{color:var(--muted);border-top:1px solid var(--line);margin-top:20px;padding-top:12px}}
</style></head><body>
<div class="topbar"><main><a class="brand" href="index.html">{icon}<span>Hermes Release Radar</span></a><a href="{PUBLIC_HERMES_REPO}">Hermes Agent</a></main></div>
<main>
<h1>Public demo snapshot</h1>
<section class="card warning"><h2>Public demo, not your local update advisor</h2><p>This static page uses only public Hermes Agent repository data. It does not know what you have installed, it does not store review markers, and it cannot make update decisions for you.</p><p>Run Release Radar locally to compare your installed checkout against upstream, persist your own review markers, and decide whether to update.</p></section>
<section class="summary-strip" aria-label="Public snapshot summary">
<div class="summary-item"><div class="summary-label">Generated</div><div class="summary-value">{esc(data['generated_at'][:10])}</div></div>
<div class="summary-item"><div class="summary-label">Public comparison</div><div class="summary-value">{esc(data['commit_count'])}</div><div class="muted">{esc(data['comparison_label'])}</div></div>
<div class="summary-item"><div class="summary-label">Latest release</div><div class="summary-value">{esc((latest.get('tag_name') or 'unknown').replace('Hermes Agent ', ''))}</div></div>
<div class="summary-item"><div class="summary-label">origin/main</div><div class="summary-value"><code>{esc(data['upstream'][:10])}</code></div></div>
</section>
{render_official(data)}
{render_public_cards(data)}
{render_raw(data)}
<footer><p>Privacy boundary: this public artifact is generated from public repository data only. Local helper API state, local filesystem paths, private state.json, review markers, and installed-checkout-specific data are intentionally absent.</p></footer>
</main></body></html>"""


def assert_public_safe(content: str) -> None:
    hits = [needle for needle in PRIVACY_FORBIDDEN_SUBSTRINGS if needle in content]
    if hits:
        raise RuntimeError("public output failed privacy scan: " + ", ".join(hits))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate public GitHub Pages demo artifacts.")
    parser.add_argument("--hermes-repo", type=Path, default=DEFAULT_HERMES_REPO, help="Public Hermes Agent checkout to inspect")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Public output directory")
    args = parser.parse_args(argv)

    data = collect_public_data(args.hermes_repo)
    page = render_page(data)
    assert_public_safe(page)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "index.html").write_text(page, encoding="utf-8")
    (args.output / "snapshot.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    assert_public_safe((args.output / "snapshot.json").read_text(encoding="utf-8"))
    print(args.output / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
