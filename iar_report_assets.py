"""
iar_report_assets.py
====================
CSS, JavaScript assets, and HTMLReporter for the OIC IAR Diff HTML report.

Imported by oic_iar_diff.py — edit this file to customise report styling,
client-side behaviour, or HTML structure without touching the core diff logic.
"""

import html
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from oic_iar_diff import ChangeSet

CSS = """
/* Oracle Redwood Design System color palette */
:root {
  --bg: #F8F8F6; --card: #FFFFFF;
  --primary: #C74634; --primary-dark: #8B2500; --accent: #0572CE;
  --green: #2BA24C; --red: #D73D25; --yellow: #EB7F00; --neutral: #504E4B;
  --green-bg: #EBF7EE; --red-bg: #FDF0EE; --yellow-bg: #FEF4E8;
  --border: #D9DBE3; --text: #161613; --muted: #6C6866;
  --header-bg: #312D2A;
  --font: 'Oracle Sans', 'Helvetica Neue', Arial, sans-serif;
  --mono: 'Oracle Mono', 'Cascadia Code', 'Consolas', monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font); background: var(--bg); color: var(--text); }
.header { background: var(--header-bg); color: #fff; padding: 2rem 2rem 1.6rem; border-bottom: 4px solid var(--primary); }
.header h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -.01em; }
.header .oracle-badge { display: inline-block; background: var(--primary); color: #fff; font-size: .7rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; padding: .15rem .55rem; border-radius: 3px; margin-bottom: .6rem; }
.header .meta { font-size: 0.84rem; color: #C5BEB9; margin-top: .45rem; }
.header .meta strong { color: #F0EDE9; }
.summary-bar { display: flex; flex-wrap: wrap; gap: 1rem; padding: 1rem 2rem; background: var(--card); border-bottom: 1px solid var(--border); }
.summary-chip { display: flex; align-items: center; gap: .4rem; padding: .3rem .85rem; border-radius: 3px; font-size: .82rem; font-weight: 600; }
.chip-add  { background: var(--green-bg); color: var(--green); }
.chip-rem  { background: var(--red-bg);   color: var(--red);   }
.chip-mod  { background: var(--yellow-bg); color: var(--yellow); }
.chip-ok   { background: #EAF3FC; color: var(--accent); }
.content { max-width: 1400px; margin: 1.5rem auto; padding: 0 1.5rem 3rem; }
.category { background: var(--card); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.cat-header { display: flex; align-items: center; justify-content: space-between; padding: .85rem 1.2rem; cursor: pointer; border-radius: 4px; user-select: none; }
.cat-header:hover { background: #F2F1EF; }
.cat-title { font-size: .97rem; font-weight: 600; }
.cat-badges { display: flex; gap: .4rem; }
.badge { font-size: .73rem; font-weight: 700; padding: .2rem .55rem; border-radius: 3px; }
.badge-add { background: var(--green-bg); color: var(--green); }
.badge-rem { background: var(--red-bg); color: var(--red); }
.badge-mod { background: var(--yellow-bg); color: var(--yellow); }
.badge-ok  { background: #EAF3FC; color: var(--accent); }
.cat-body { border-top: 1px solid var(--border); padding: .8rem 1.2rem; display: none; }
.cat-body.open { display: block; }
.change-group { margin-bottom: .6rem; }
.change-group h4 { font-size: .75rem; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); margin-bottom: .35rem; font-weight: 600; }
.change-item { padding: .45rem .8rem; border-radius: 3px; margin-bottom: .3rem; font-size: .86rem; }
.change-item.add  { background: var(--green-bg); border-left: 3px solid var(--green); }
.change-item.rem  { background: var(--red-bg);   border-left: 3px solid var(--red);   }
.change-item.mod  { background: var(--yellow-bg); border-left: 3px solid var(--yellow); }
.change-label { font-weight: 600; }
.change-detail { color: var(--muted); font-size: .81rem; margin-top: .15rem; }
.diff-toggle { font-size: .74rem; color: var(--accent); cursor: pointer; text-decoration: underline; margin-top: .2rem; display: inline-block; }
.diff-panel { display: none; margin-top: .5rem; overflow-x: auto; }
.diff-panel.open { display: block; }
table.diff { border-collapse: collapse; font-family: var(--mono); font-size: .77rem; width: 100%; }
table.diff td, table.diff th { padding: 2px 6px; border: 1px solid var(--border); white-space: pre-wrap; word-break: break-all; }
table.diff th { background: #F2F1EF; font-weight: 600; color: var(--neutral); }
.diff_add td { background: #DCF5E4; }
.diff_chg td { background: #FEF0D0; }
.diff_sub td { background: #FADDDA; }
.no-changes { padding: 1rem; color: var(--muted); font-style: italic; text-align: center; }
ins { background: #B3EDBE; text-decoration: none; border-radius: 2px; padding: 0 2px; }
del { background: #F5BDB5; text-decoration: none; border-radius: 2px; padding: 0 2px; }
code { font-family: var(--mono); font-size: .84em; background: #F2F1EF; padding: 1px 4px; border-radius: 3px; color: var(--primary-dark); }
.expand-all { font-size: .8rem; color: var(--accent); cursor: pointer; text-decoration: underline; padding: .5rem 2rem; display: inline-block; }
"""


JS = """
document.querySelectorAll('.cat-header').forEach(h => {
  h.addEventListener('click', () => {
    const body = h.nextElementSibling;
    body.classList.toggle('open');
    const arrow = h.querySelector('.arrow');
    if (arrow) arrow.textContent = body.classList.contains('open') ? '▲' : '▼';
  });
});
document.querySelectorAll('.diff-toggle').forEach(t => {
  t.addEventListener('click', e => {
    e.stopPropagation();
    const panel = t.nextElementSibling;
    if (panel && panel.classList.contains('diff-panel')) {
      panel.classList.toggle('open');
      t.textContent = panel.classList.contains('open') ? 'Hide diff ▲' : 'Show diff ▼';
    }
  });
});
document.querySelectorAll('.cat-header').forEach(h => {
  // Auto-expand categories with changes
  const badges = h.querySelectorAll('.badge-add, .badge-rem, .badge-mod');
  if (badges.length > 0) {
    const body = h.nextElementSibling;
    body.classList.add('open');
    const arrow = h.querySelector('.arrow');
    if (arrow) arrow.textContent = '▲';
  }
});
"""


class HTMLReporter:

    def __init__(self, changesets: "List[ChangeSet]",
                 label1: str, label2: str,
                 title: str = "OIC IAR Diff Report"):
        self.changesets = changesets
        self.label1 = label1
        self.label2 = label2
        self.title = title

    def render(self) -> str:
        total_add = sum(len(c.added) for c in self.changesets)
        total_rem = sum(len(c.removed) for c in self.changesets)
        total_mod = sum(len(c.modified) for c in self.changesets)
        total_ok  = sum(c.unchanged_count for c in self.changesets)

        cats_html = "\n".join(self._render_category(c) for c in self.changesets)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(self.title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="header">
  <div class="oracle-badge">Oracle Integration Cloud</div>
  <h1>{html.escape(self.title)}</h1>
  <div class="meta">
    Comparing <strong>{html.escape(self.label1)}</strong> vs <strong>{html.escape(self.label2)}</strong>
    &nbsp;·&nbsp; Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  </div>
</div>
<div class="summary-bar">
  <div class="summary-chip chip-add">&#43; {total_add} Added</div>
  <div class="summary-chip chip-rem">&#8722; {total_rem} Removed</div>
  <div class="summary-chip chip-mod">&#126; {total_mod} Modified</div>
  <div class="summary-chip chip-ok">&#10003; {total_ok} Unchanged</div>
</div>
<div class="content">
{cats_html}
</div>
<script>{JS}</script>
</body>
</html>"""

    def _render_category(self, cs: "ChangeSet") -> str:
        badges = []
        if cs.added:
            badges.append(f'<span class="badge badge-add">+{len(cs.added)} added</span>')
        if cs.removed:
            badges.append(f'<span class="badge badge-rem">-{len(cs.removed)} removed</span>')
        if cs.modified:
            badges.append(f'<span class="badge badge-mod">~{len(cs.modified)} modified</span>')
        if cs.unchanged_count:
            badges.append(f'<span class="badge badge-ok">{cs.unchanged_count} unchanged</span>')

        badges_html = " ".join(badges) if badges else '<span class="badge badge-ok">No changes</span>'

        icon = cs.icon + " " if cs.icon else ""

        header = f"""<div class="cat-header">
  <span class="cat-title">{icon}{html.escape(cs.name)}</span>
  <span><span class="cat-badges">{badges_html}</span> &nbsp;<span class="arrow">▼</span></span>
</div>"""

        if not cs.has_changes():
            body_inner = f'<div class="no-changes">No changes in this category ({cs.unchanged_count} items checked)</div>'
        else:
            sections = []
            if cs.added:
                items = "\n".join(self._item_html(i, "add") for i in cs.added)
                sections.append(f'<div class="change-group"><h4>Added ({len(cs.added)})</h4>{items}</div>')
            if cs.removed:
                items = "\n".join(self._item_html(i, "rem") for i in cs.removed)
                sections.append(f'<div class="change-group"><h4>Removed ({len(cs.removed)})</h4>{items}</div>')
            if cs.modified:
                items = "\n".join(self._item_html(i, "mod") for i in cs.modified)
                sections.append(f'<div class="change-group"><h4>Modified ({len(cs.modified)})</h4>{items}</div>')
            body_inner = "\n".join(sections)

        return f"""<div class="category">
{header}
<div class="cat-body">
{body_inner}
</div>
</div>"""

    def _item_html(self, item: Dict, kind: str) -> str:
        label = html.escape(item.get("label", ""))
        detail = item.get("detail", "")  # may contain HTML (del/ins tags)
        diff_html = item.get("diff", "")

        diff_block = ""
        if diff_html:
            diff_block = (
                f'<span class="diff-toggle">Show diff ▼</span>'
                f'<div class="diff-panel">{diff_html}</div>'
            )

        return f"""<div class="change-item {kind}">
  <div class="change-label">{label}</div>
  {'<div class="change-detail">' + detail + '</div>' if detail else ''}
  {diff_block}
</div>"""
