#!/usr/bin/env python3
"""Render slides.md into a single self-contained slides.html.

Deliberately small and deliberately derived. The deck a judge would see is
generated from slides.md and nothing else, so slides.md stays the one place a
figure can be edited -- and verify_presentation.py refuses a slides.html whose
recorded source digest does not match the slides.md sitting next to it. A
rendered deck that has drifted from the checked source is worse than no rendered
deck, because it looks authoritative.

No network, no fonts, no JS libraries: this has to open from a memory stick in a
room with someone else's wifi. Arrow keys and click advance; `?print` in the URL
lays every slide out for PDF export.

    python3 build_presentation.py [--dir D]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import pathlib
import re
import sys

CSS = """
:root { --ink:#12181f; --dim:#5b6773; --rule:#d8dee5; --accent:#0b5d8f;
        --bad:#a4262c; --paper:#ffffff; }
* { box-sizing:border-box; }
body { margin:0; background:#20262e; color:var(--ink);
       font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
.deck { display:block; }
section { display:none; background:var(--paper); width:100vw; height:100vh;
          padding:5.5vh 6vw 7vh; overflow:auto; }
section.on { display:block; }
h2 { font-size:2.05rem; line-height:1.18; margin:0 0 1.1rem; letter-spacing:-.015em; }
h2 .n { color:var(--dim); font-weight:400; font-size:1rem; display:block;
        margin-bottom:.5rem; letter-spacing:.08em; text-transform:uppercase; }
p, li { font-size:1.16rem; margin:.55rem 0; max-width:60em; }
ul { margin:.5rem 0 .5rem 1.1rem; }
strong { color:#000; }
em { color:var(--dim); font-style:italic; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
       font-size:.92em; background:#eef2f6; padding:.08em .32em; border-radius:3px; }
pre { background:#f5f8fa; border-left:3px solid var(--accent); padding:.85rem 1rem;
      overflow-x:auto; font-size:1rem; }
pre code { background:none; padding:0; }
table { border-collapse:collapse; margin:.9rem 0; font-size:1.02rem; }
th, td { border-bottom:1px solid var(--rule); padding:.42rem .85rem; text-align:left;
         vertical-align:top; }
th { font-size:.82rem; letter-spacing:.05em; text-transform:uppercase;
     color:var(--dim); border-bottom:2px solid var(--rule); }
td.r, th.r { text-align:right; font-variant-numeric:tabular-nums; }
footer { position:fixed; left:6vw; right:6vw; bottom:2.2vh; display:flex;
         justify-content:space-between; font-size:.8rem; color:var(--dim);
         border-top:1px solid var(--rule); padding-top:.5rem; }
footer .crit { letter-spacing:.1em; }
body.print section { display:block; height:auto; min-height:0; page-break-after:always;
                     border-bottom:1px solid var(--rule); }
body.print footer { position:static; }
@media print { body { background:#fff; } section { height:auto; } }
"""

JS = """
var S = [].slice.call(document.querySelectorAll('section')), i = 0;
function go(n){ i = Math.max(0, Math.min(S.length-1, n));
  S.forEach(function(s,k){ s.classList.toggle('on', k===i); });
  document.getElementById('pos').textContent = (i+1) + ' / ' + S.length;
  document.getElementById('crit').textContent = S[i].dataset.criteria || '';
  document.getElementById('sec').textContent = S[i].dataset.seconds + ' s'; }
document.addEventListener('keydown', function(e){
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') go(i+1);
  if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(i-1);
  if (e.key === 'Home') go(0); if (e.key === 'End') go(S.length-1); });
document.addEventListener('click', function(e){
  go(e.clientX < window.innerWidth * 0.25 ? i-1 : i+1); });
if (location.search.indexOf('print') >= 0) { document.body.className = 'print';
  S.forEach(function(s){ s.classList.add('on'); }); } else go(0);
"""


def inline(s: str) -> str:
    """Escape first, then re-introduce only the four inline forms the deck uses."""
    out = html.escape(s)
    out = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def render_table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    align = cells[1]
    right = [i for i, a in enumerate(align) if a.endswith(":") and a.startswith("-")]
    cls = lambda i: ' class="r"' if i in right else ""
    head = "".join(f"<th{cls(i)}>{inline(c)}</th>" for i, c in enumerate(cells[0]))
    body = "".join(
        "<tr>" + "".join(f"<td{cls(i)}>{inline(c)}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in cells[2:])
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_body(md: str) -> str:
    lines, out, i = md.split("\n"), [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "---" or (ln.strip() == "" and not out[-1:] == [""]):
            i += 1
            continue
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            code = html.escape("\n".join(lines[i + 1: j]))
            out.append(f"<pre><code>{code}</code></pre>")
            i = j + 1
            continue
        if ln.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out.append(render_table(lines[i:j]))
            i = j
            continue
        if ln.lstrip().startswith("- "):
            j, items = i, []
            while j < len(lines) and (lines[j].lstrip().startswith("- ")
                                      or (items and lines[j].startswith("  ") and lines[j].strip())):
                if lines[j].lstrip().startswith("- "):
                    items.append(lines[j].lstrip()[2:])
                else:
                    items[-1] += " " + lines[j].strip()
                j += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            i = j
            continue
        if ln.startswith("## "):
            i += 1
            continue                      # the title is emitted by the caller
        para = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"\s*(\||-\s|```|##\s|---$)", lines[i]):
            para.append(lines[i])
            i += 1
        text = " ".join(x.strip() for x in para).strip()
        if text:
            out.append(f"<p>{inline(text)}</p>")
    return "\n".join(out)


def build(d: pathlib.Path) -> pathlib.Path:
    src = (d / "slides.md").read_text()
    digest = hashlib.sha256(src.encode()).hexdigest()
    marks = list(re.finditer(
        r"<!--\s*slide:\s*(\d+)\s*\|\s*seconds:\s*(\d+)\s*\|\s*criteria:\s*([^>]*?)-->", src))
    parts = []
    for k, m in enumerate(marks):
        chunk = src[m.end(): marks[k + 1].start() if k + 1 < len(marks) else len(src)]
        title = next((l[3:].strip() for l in chunk.split("\n") if l.startswith("## ")), "")
        crit = " ".join(c for c in m.group(3).split() if c != "-")
        parts.append(
            f'<section data-seconds="{m.group(2)}" data-criteria="{html.escape(crit)}">'
            f'<h2><span class="n">Slide {m.group(1)}</span>{inline(title)}</h2>'
            f"{render_body(chunk)}</section>")
    total = sum(int(m.group(2)) for m in marks)
    doc = f"""<!DOCTYPE html>
<meta charset="utf-8">
<title>RoadStar Hackathon 2026 - backhaul matching under hours of service</title>
<!-- generated by build_presentation.py from slides.md
     slides.md sha256: {digest}
     slides: {len(marks)}   scripted length: {total} s ({total // 60}m{total % 60:02d}s)
     Do not edit this file. Edit slides.md and rebuild; verify_presentation.py
     compares the digest above against slides.md and goes red if they differ. -->
<style>{CSS}</style>
<div class="deck">
{chr(10).join(parts)}
</div>
<footer><span id="crit" class="crit"></span><span id="sec"></span><span id="pos"></span></footer>
<script>{JS}</script>
"""
    out = d / "slides.html"
    out.write_text(doc)
    print(f"slides.html  {len(marks)} slides  {total} s  src sha256 {digest[:16]}...  "
          f"{len(doc):,} bytes, no external references")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(pathlib.Path(__file__).resolve().parent))
    build(pathlib.Path(ap.parse_args().dir).resolve())
    sys.exit(0)
