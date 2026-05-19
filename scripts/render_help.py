from __future__ import annotations
from pathlib import Path
import html
import re

repo_root = Path(__file__).resolve().parents[1]
src = repo_root / 'HELP.md'
out_path = repo_root / 'docs' / 'help.html'
md = src.read_text(encoding='utf-8')

parts = []
in_code = False
code_buf = []
code_i = 0
open_ul = False

def close_ul():
    global open_ul
    if open_ul:
        parts.append('</ul>')
        open_ul = False

def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    url_re = r'(https?://[^\s<]+)'
    text = re.sub(url_re, r'<a href="\1">\1</a>', text)
    return text

for raw in md.splitlines():
    line = raw.rstrip('\n')
    if line.startswith('```'):
        if not in_code:
            close_ul()
            in_code = True
            code_buf = []
        else:
            code_i += 1
            code = '\n'.join(code_buf).strip('\n')
            parts.append(
                '<div class="cmd-card">'
                '<div class="cmd-top"><span>Command</span><button type="button" onclick="copyCode(this)">Copy</button></div>'
                f'<pre><code>{html.escape(code)}</code></pre>'
                '</div>'
            )
            in_code = False
        continue
    if in_code:
        code_buf.append(line)
        continue
    if not line.strip():
        close_ul()
        continue
    if line.startswith('# '):
        close_ul()
        parts.append(f'<h1>{inline(line[2:])}</h1>')
    elif line.startswith('## '):
        close_ul()
        parts.append(f'<h2>{inline(line[3:])}</h2>')
    elif line.startswith('- '):
        if not open_ul:
            parts.append('<ul>')
            open_ul = True
        parts.append(f'<li>{inline(line[2:])}</li>')
    else:
        close_ul()
        parts.append(f'<p>{inline(line)}</p>')
close_ul()
body = '\n'.join(parts)

page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Hermes Release Radar Help</title>
<style>
:root {{
  color-scheme: dark;
  --bg:#0b1014; --panel:#101820; --panel2:#0e171d; --text:#c7d7dc;
  --muted:#91a4af; --line:#26343d; --accent:#62e6c8; --blue:#a8e9ff;
}}
* {{ box-sizing:border-box; }}
html {{ overflow-x:hidden; }}
body {{
  margin:0; background:radial-gradient(circle at 12% 0,#17302d 0,#0b1014 30rem);
  color:var(--text); font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;
}}
a {{ color:var(--blue); }}
.top {{ border-bottom:1px solid var(--line); background:#0b1014cc; position:sticky; top:0; z-index:2; backdrop-filter:blur(8px); }}
.top main {{ max-width:1000px; margin:auto; padding:9px 18px; display:flex; justify-content:space-between; align-items:center; gap:12px; }}
main.content {{ max-width:1000px; margin:auto; padding:18px; }}
h1 {{ margin:8px 0 6px; font-size:clamp(26px,5vw,36px); }}
h2 {{ margin:26px 0 10px; padding-top:8px; border-top:1px solid #1d2a33; font-size:20px; }}
p {{ margin:8px 0; color:#dce8ed; }}
ul {{ margin:8px 0 12px; padding-left:22px; }}
li {{ margin:5px 0; }}
code {{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:#0b1419; border:1px solid #20313b; border-radius:7px; padding:1px 5px;
}}
.cmd-card {{
  margin:10px 0 18px; border:1px solid #22343f; border-radius:14px;
  background:linear-gradient(180deg,#0f1a21,#0b1419); overflow:hidden; box-shadow:0 10px 24px #0004;
}}
.cmd-top {{
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  padding:7px 10px; border-bottom:1px solid #1e303a; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em;
}}
.cmd-top button {{
  background:#102239; color:#d9ecff; border:1px solid #315a7e; border-radius:999px;
  padding:4px 10px; cursor:pointer; font-size:12px; text-transform:none; letter-spacing:0;
}}
pre {{
  margin:0; padding:12px; overflow-x:auto; white-space:pre; tab-size:2;
  font:15px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}}
pre code {{
  display:block; background:transparent; border:0; border-radius:0; padding:0;
  color:#f2fbff; white-space:pre; line-height:inherit;
}}
@media (max-width:720px) {{
  main.content {{ padding:14px; }}
  pre {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
  pre code {{ white-space:pre-wrap; }}
}}
.note {{ color:var(--muted); }}
</style>
</head>
<body>
<div class="top"><main><strong>Hermes Release Radar Help</strong><a href="index.html">Back to radar</a></main></div>
<main class="content">{body}</main>
<script>
async function copyCode(btn) {{
  const card = btn.closest('.cmd-card');
  const code = card ? card.querySelector('pre code')?.innerText : '';
  if (!code) return;
  try {{ await navigator.clipboard.writeText(code); btn.textContent = 'Copied'; setTimeout(() => btn.textContent = 'Copy', 1200); }}
  catch (_) {{ btn.textContent = 'Select'; setTimeout(() => btn.textContent = 'Copy', 1200); }}
}}
</script>
</body>
</html>
'''
out_path.write_text(page, encoding='utf-8')
print(out_path)
