"""Render writeup/post.md as a reading page.

    .venv/bin/python scripts/render_post.py <output.html>

Generated from the markdown so the two cannot drift. The markdown is the source; edit that.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

SOURCE = Path("writeup/post.md")

STYLE = """
/* Layout: one reading column, the table and the quoted pushbacks allowed to sit apart from it. */
:root {
  --bg: #fbfaf7; --surface: #ffffff; --sunk: #f1efe9; --fg: #1a1c20; --fg-dim: #53575e;
  --fg-faint: #8b9098; --rule: #e0ddd4; --accent: #30356b; --alarm: #9c4221;
  --font-display: "Spectral", Georgia, "Times New Roman", serif;
  --font-ui: "IBM Plex Sans", system-ui, -apple-system, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #15161a; --surface: #1d1f24; --sunk: #22242a; --fg: #eceef1; --fg-dim: #a8adb6;
  --fg-faint: #7c828c; --rule: #32353d; --accent: #a6adf2; --alarm: #e9a183; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #15161a; --surface: #1d1f24; --sunk: #22242a; --fg: #eceef1; --fg-dim: #a8adb6;
  --fg-faint: #7c828c; --rule: #32353d; --accent: #a6adf2; --alarm: #e9a183; color-scheme: dark; }
body { background: var(--bg); color: var(--fg); font-family: var(--font-display);
  font-size: 18px; line-height: 1.66; }
.wrap { max-width: 40rem; margin: 0 auto;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 52px 80px; }
h1 { font-size: clamp(30px, 5.4vw, 42px); line-height: 1.12; font-weight: 600;
  letter-spacing: -0.02em; margin: 0 0 24px; text-wrap: balance; }
h2 { font-family: var(--font-ui); font-size: 15px; font-weight: 600; margin: 42px 0 14px; }
h2::before { content: ""; display: block; width: 26px; height: 2px; background: var(--accent);
  margin-bottom: 14px; }
p { margin: 0 0 17px; }
blockquote { margin: 22px 0; padding: 12px 0 12px 18px; border-left: 2px solid var(--alarm);
  font-style: italic; color: var(--fg); background: linear-gradient(to right, var(--sunk), transparent 70%); }
blockquote p { margin: 0; }
code { font-family: var(--font-mono); font-size: 0.84em; background: var(--sunk);
  padding: 1px 5px; border-radius: 3px; }
blockquote code { background: transparent; padding: 0; }
.scroll { overflow-x: auto; margin: 24px 0; }
table { width: 100%; border-collapse: collapse; font-family: var(--font-ui); font-size: 14px; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--rule); }
th { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--fg-faint);
  font-weight: 500; }
td:last-child { font-variant-numeric: tabular-nums; }
hr { border: 0; border-top: 1px solid var(--rule); margin: 40px 0 24px; }
.closing { color: var(--fg-dim); font-size: 15px; font-style: italic; }
"""


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def render(markdown: str) -> str:
    out: list[str] = []
    blocks = re.split(r"\n\s*\n", markdown.strip())
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        if lines[0].startswith("# "):
            out.append(f"<h1>{inline(lines[0][2:])}</h1>")
        elif lines[0].startswith("## "):
            out.append(f"<h2>{inline(lines[0][3:])}</h2>")
        elif lines[0].startswith(">"):
            text = " ".join(line.lstrip("> ").strip() for line in lines)
            out.append(f"<blockquote><p>{inline(text)}</p></blockquote>")
        elif lines[0].startswith("|"):
            rows = [r for r in lines if r.startswith("|") and not set(r) <= set("|-: ")]
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            head = "".join(f"<th>{inline(c)}</th>" for c in cells[0])
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                for row in cells[1:]
            )
            out.append(f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>')
        else:
            text = " ".join(lines)
            cls = ' class="closing"' if text.startswith("*") and text.endswith("*") else ""
            if cls:
                text = text.strip("*")
            out.append(f"<p{cls}>{inline(text)}</p>")
    return "\n  ".join(out)


def main() -> None:
    body = render(SOURCE.read_text())
    title = re.search(r"^# (.+)$", SOURCE.read_text(), re.M).group(1)
    short = "Your Coding Assistant Stops Telling You"
    page = f"""<title>{html.escape(short)}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&display=swap">
<style>{STYLE}</style>
<div class="wrap">
  {body}
</div>
"""
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "post.html")
    out.write_text(page)
    print(f"wrote {out} ({len(page):,} bytes) from {SOURCE}, title {title!r}")


if __name__ == "__main__":
    main()
