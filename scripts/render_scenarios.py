"""Render a scenario set as a review page.

    .venv/bin/python scripts/render_scenarios.py <output.html>
    .venv/bin/python scripts/render_scenarios.py <output.html> --durability

The page is generated rather than hand-written so it can never drift from the data it reviews.
"""

from __future__ import annotations

import html
import sys
from collections import Counter
from pathlib import Path

from course_correction.risk.dataset import CATEGORIES, load_scenarios

CATEGORY_LABELS = {
    "pii_at_rest": "Personal data at rest",
    "client_secret": "Secrets in client code",
    "unauthenticated_endpoint": "Unauthenticated endpoint",
    "destructive_operation": "Destructive operation",
    "unbounded_cost": "Unbounded cost",
    "health_data": "Health data",
}

STYLE = """
/* Layout: a measured review column — one card per pair, risky and benign side by side,
   shared turns beneath, the reference risk as a footnote the grader is held to. */
:root {
  --bg: #f6f6f4;
  --surface: #fffffe;
  --surface-sunk: #eeeeea;
  --fg: #1b1d21;
  --fg-dim: #5d6168;
  --fg-faint: #898e96;
  --rule: #dcdcd6;
  --risky: #9c4221;
  --risky-bg: #f7ece6;
  --benign: #2c5f5a;
  --benign-bg: #e7efed;
  --accent: #30356b;
  --font-display: "Spectral", Georgia, "Times New Roman", serif;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15161a;
    --surface: #1d1f24;
    --surface-sunk: #24262c;
    --fg: #ecedf0;
    --fg-dim: #a7acb5;
    --fg-faint: #7e848e;
    --rule: #32353d;
    --risky: #e9a183;
    --risky-bg: #2c2220;
    --benign: #8fc4bd;
    --benign-bg: #1c2727;
    --accent: #a6adf2;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #15161a;
  --surface: #1d1f24;
  --surface-sunk: #24262c;
  --fg: #ecedf0;
  --fg-dim: #a7acb5;
  --fg-faint: #7e848e;
  --rule: #32353d;
  --risky: #e9a183;
  --risky-bg: #2c2220;
  --benign: #8fc4bd;
  --benign-bg: #1c2727;
  --accent: #a6adf2;
  color-scheme: dark;
}
body {
  background: var(--bg);
  color: var(--fg);
  font-family: var(--font-body);
  font-size: 15px;
  line-height: 1.55;
}
.wrap {
  max-width: 1080px;
  margin: 0 auto;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
  padding-block: 40px 72px;
}
header { border-bottom: 1px solid var(--rule); padding-bottom: 28px; margin-bottom: 28px; }
h1 {
  font-family: var(--font-display);
  font-size: clamp(28px, 4.5vw, 40px);
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -0.01em;
  margin: 0 0 10px;
  text-wrap: balance;
}
.standfirst { color: var(--fg-dim); max-width: 62ch; margin: 0 0 24px; }
.counts { display: flex; flex-wrap: wrap; gap: 10px 28px; font-family: var(--font-mono); font-size: 12px; }
.counts div { display: flex; flex-direction: column; gap: 2px; }
.counts dt, .counts .k { color: var(--fg-faint); text-transform: uppercase; letter-spacing: 0.08em; font-size: 10px; }
.counts .v { font-size: 20px; font-variant-numeric: tabular-nums; color: var(--fg); }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 26px 0 8px; }
.controls .label {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--fg-faint); margin-right: 4px;
}
button.chip {
  font: inherit; font-size: 12px; font-family: var(--font-mono);
  background: var(--surface); color: var(--fg-dim);
  border: 1px solid var(--rule); border-radius: 999px;
  padding: 5px 12px; cursor: pointer;
}
button.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--bg); }
button.chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.progress { font-family: var(--font-mono); font-size: 12px; color: var(--fg-dim); margin-left: auto; }
.pairs { display: flex; flex-direction: column; gap: 18px; margin-top: 22px; }
article {
  background: var(--surface); border: 1px solid var(--rule); border-radius: 4px;
  padding: 18px 18px 16px;
}
article[data-done="1"] { opacity: 0.55; }
.pair-head { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: baseline; margin-bottom: 14px; }
.pair-id { font-family: var(--font-mono); font-size: 12px; color: var(--fg); }
.tag {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--fg-dim); border: 1px solid var(--rule); border-radius: 3px; padding: 2px 6px;
}
.tag.salience-stated { border-color: var(--risky); color: var(--risky); }
.review { margin-left: auto; display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--fg-dim); font-family: var(--font-mono); }
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 720px) { .sides { grid-template-columns: 1fr; } }
.side { min-width: 0; border-radius: 3px; padding: 12px 13px; }
.side.risky { background: var(--risky-bg); }
.side.benign { background: var(--benign-bg); }
.side h3 {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase;
  margin: 0 0 7px;
}
.side.risky h3 { color: var(--risky); }
.side.benign h3 { color: var(--benign); }
.turn { margin: 0; }
.shared { margin-top: 14px; border-top: 1px solid var(--rule); padding-top: 12px; }
.shared h3 {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--fg-faint); margin: 0 0 7px;
}
ol.turns { margin: 0; padding-left: 22px; color: var(--fg-dim); }
ol.turns li { margin-bottom: 5px; }
.risk {
  margin-top: 14px; background: var(--surface-sunk); border-left: 2px solid var(--risky);
  padding: 11px 13px; border-radius: 0 3px 3px 0;
}
.risk h3 {
  font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--fg-faint); margin: 0 0 5px;
}
.risk p { margin: 0; font-family: var(--font-display); font-size: 15px; }
.note { margin: 10px 0 0; font-size: 12px; color: var(--fg-faint); }
footer { margin-top: 44px; border-top: 1px solid var(--rule); padding-top: 18px; color: var(--fg-dim); font-size: 13px; }
footer code { font-family: var(--font-mono); font-size: 12px; }
.empty { color: var(--fg-dim); font-style: italic; padding: 24px 0; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

SCRIPT = """
const KEY = 'cc-scenario-review';
let done = {};
try { done = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { done = {}; }

const cards = Array.from(document.querySelectorAll('article'));
const progress = document.getElementById('progress');

function paint() {
  let count = 0;
  for (const card of cards) {
    const isDone = !!done[card.dataset.pair];
    card.dataset.done = isDone ? '1' : '0';
    const box = card.querySelector('input[type=checkbox]');
    if (box) box.checked = isDone;
    if (isDone) count += 1;
  }
  progress.textContent = count + ' of ' + cards.length + ' marked reviewed';
}

for (const card of cards) {
  const box = card.querySelector('input[type=checkbox]');
  if (!box) continue;
  box.addEventListener('change', () => {
    done[card.dataset.pair] = box.checked;
    try { localStorage.setItem(KEY, JSON.stringify(done)); } catch (e) { /* private window */ }
    paint();
  });
}

let filter = 'all';
const chips = Array.from(document.querySelectorAll('button.chip'));
for (const chip of chips) {
  chip.addEventListener('click', () => {
    filter = chip.dataset.filter;
    for (const c of chips) c.setAttribute('aria-pressed', String(c === chip));
    let shown = 0;
    for (const card of cards) {
      const match = filter === 'all'
        || card.dataset.category === filter
        || card.dataset.salience === filter;
      card.hidden = !match;
      if (match) shown += 1;
    }
    document.getElementById('empty').hidden = shown > 0;
  });
}
paint();
"""


def render(path: Path) -> None:
    scenarios = load_scenarios()
    by_pair: dict[str, dict[str, object]] = {}
    for s in scenarios:
        entry = by_pair.setdefault(
            s.pair_id, {"category": s.category, "salience": s.salience, "notes": s.notes}
        )
        entry[s.variant] = s

    cat_counts = Counter(s.category for s in scenarios if s.variant == "risky")
    sal_counts = Counter(s.salience for s in scenarios if s.variant == "risky")

    chips = ['<button class="chip" data-filter="all" aria-pressed="true">all 24</button>']
    for cat in CATEGORIES:
        chips.append(
            f'<button class="chip" data-filter="{cat}">'
            f"{html.escape(CATEGORY_LABELS[cat])} {cat_counts[cat]}</button>"
        )
    for sal in ("stated", "implicit"):
        chips.append(f'<button class="chip" data-filter="{sal}">{sal} {sal_counts[sal]}</button>')

    cards = []
    for pair_id, entry in by_pair.items():
        risky, benign = entry["risky"], entry["benign"]  # type: ignore[index]
        shared = "".join(f"<li>{html.escape(t)}</li>" for t in risky.turns[1:])  # type: ignore[attr-defined]
        cards.append(f"""
<article data-pair="{pair_id}" data-category="{entry["category"]}" data-salience="{entry["salience"]}">
  <div class="pair-head">
    <span class="pair-id">{html.escape(pair_id)}</span>
    <span class="tag">{html.escape(CATEGORY_LABELS[str(entry["category"])])}</span>
    <span class="tag salience-{entry["salience"]}">{entry["salience"]} risk</span>
    <label class="review"><input type="checkbox"> reviewed</label>
  </div>
  <div class="sides">
    <div class="side risky">
      <h3>Risky &middot; turn 1</h3>
      <p class="turn">{html.escape(risky.turns[0])}</p>
    </div>
    <div class="side benign">
      <h3>Benign twin &middot; turn 1</h3>
      <p class="turn">{html.escape(benign.turns[0])}</p>
    </div>
  </div>
  <div class="shared">
    <h3>Turns 2 and 3 &middot; identical on both sides</h3>
    <ol class="turns" start="2">{shared}</ol>
  </div>
  <div class="risk">
    <h3>What a flag has to name</h3>
    <p>{html.escape(str(risky.reference_risk))}</p>
  </div>
  <p class="note">{html.escape(str(entry["notes"]))}</p>
</article>""")

    page = f"""<title>Risk Scenario Pairs</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{STYLE}</style>
<div class="wrap">
  <header>
    <h1>Risk scenario pairs</h1>
    <p class="standfirst">Module A of Course Correction. Each pair asks a coding agent to build
      something; the risky side carries a security, privacy, cost or data-loss problem the user never
      mentions, and the benign twin is the same request with that problem removed. Turns 2 and 3 are
      word-for-word identical across a pair, so any difference in what the agent says comes from
      turn 1 alone.</p>
    <div class="counts">
      <div><span class="k">Pairs</span><span class="v">{len(by_pair)}</span></div>
      <div><span class="k">Scenarios</span><span class="v">{len(scenarios)}</span></div>
      <div><span class="k">Categories</span><span class="v">{len(CATEGORIES)}</span></div>
      <div><span class="k">Risk stated by the user</span><span class="v">{sal_counts["stated"]}</span></div>
      <div><span class="k">Risk left implicit</span><span class="v">{sal_counts["implicit"]}</span></div>
    </div>
  </header>
  <div class="controls">
    <span class="label">Filter</span>
    {"".join(chips)}
    <span class="progress" id="progress"></span>
  </div>
  <p class="empty" id="empty" hidden>Nothing matches that filter.</p>
  <div class="pairs">{"".join(cards)}</div>
  <footer>
    <p>Generated from <code>data/risk/scenarios.yaml</code> by
      <code>scripts/render_scenarios.py</code>. Edit the YAML, not this page. The invariants shown
      here &mdash; pair counts, category balance, identical later turns, no risky material in a
      benign twin &mdash; are enforced by <code>tests/test_scenarios.py</code>.</p>
  </footer>
</div>
<script>{SCRIPT}</script>
"""
    path.write_text(page)
    print(f"wrote {path} ({len(page):,} bytes, {len(by_pair)} pairs)")


def render_durability(path: Path) -> None:
    """The confirmatory set, paired by mechanism so severity matching is checkable at a glance."""
    import yaml

    from course_correction.risk.dataset import DURABILITY

    raw = yaml.safe_load(DURABILITY.read_text())
    by_mechanism: dict[str, dict[str, dict]] = {}
    for item in raw:
        by_mechanism.setdefault(item["mechanism"], {})[item["harm_falls_on"]] = item

    cards = []
    for mechanism, sides in by_mechanism.items():
        owner, third = sides["owner"], sides["third_party"]
        shared = "".join(f"<li>{html.escape(' '.join(t.split()))}</li>" for t in owner["turns"][1:])
        cards.append(f"""
<article data-pair="{mechanism}" data-category="{mechanism}" data-salience="implicit">
  <div class="pair-head">
    <span class="pair-id">{html.escape(mechanism.replace("_", " "))}</span>
    <label class="review"><input type="checkbox"> reviewed</label>
  </div>
  <div class="sides">
    <div class="side risky">
      <h3>Harm falls on the owner</h3>
      <p class="turn">{html.escape(" ".join(owner["turns"][0].split()))}</p>
      <p class="note">{html.escape(" ".join(owner["reference_risk"].split()))}</p>
    </div>
    <div class="side benign">
      <h3>Harm falls on other people</h3>
      <p class="turn">{html.escape(" ".join(third["turns"][0].split()))}</p>
      <p class="note">{html.escape(" ".join(third["reference_risk"].split()))}</p>
    </div>
  </div>
  <div class="shared">
    <h3>Turns 2 and 3 &middot; the owner side (the other differs only where the sentence must)</h3>
    <ol class="turns" start="2">{shared}</ol>
  </div>
</article>""")

    page = f"""<title>Whose Harm Gets Dropped</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{STYLE}</style>
<div class="wrap">
  <header>
    <h1>Whose harm gets dropped</h1>
    <p class="standfirst">The confirmatory set for the pre-registered question: when a user waves a
      warning away, is it dropped more readily when the harm falls on them than when it falls on
      someone else? Each mechanism is written twice and differs only in who gets hurt, so that
      severity cannot explain a difference. <strong>The thing to check is whether the two sides of
      each row really are comparable in severity.</strong></p>
    <div class="counts">
      <div><span class="k">Scenarios</span><span class="v">{len(raw)}</span></div>
      <div><span class="k">Mechanisms</span><span class="v">{len(by_mechanism)}</span></div>
      <div><span class="k">Owner harm</span><span class="v">8</span></div>
      <div><span class="k">Third-party harm</span><span class="v">8</span></div>
    </div>
  </header>
  <div class="controls"><span class="progress" id="progress"></span></div>
  <p class="empty" id="empty" hidden></p>
  <div class="pairs">{"".join(cards)}</div>
  <footer>
    <p>Generated from <code>data/risk/durability.yaml</code>. The prediction and the analysis were
      fixed in <code>docs/preregistration-durability.md</code> before these scenarios were written.</p>
  </footer>
</div>
<script>{SCRIPT}</script>
"""
    path.write_text(page)
    print(f"wrote {path} ({len(page):,} bytes, {len(by_mechanism)} mechanisms)")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "scenarios-review.html")
    if "--durability" in sys.argv:
        render_durability(out)
    else:
        render(out)
