"""fab-test's own `--report` page for a PBIR run (PBIR Slicer Default State epic).

Every other analyzer's report is fab-test's page (bpa, pql_test, rdl): a
header, the run's meta line and one filterable table, rendered from the
envelope by `render_report`. PBIR Inspector writes its own TestRun.html,
richer (screenshots, page wireframes) but laid out its own way and blind to
the slicer contract. This is the same page for PBIR: the slicer contract's
checks and the PBIR rules as two sections, links to each at the top, and
PBIR Inspector's page collapsed at the bottom in a frame, so it keeps its
own look and scripts.

Like `render_report`, it computes no finding of its own: every row traces to
the envelope's `test_results` and `contract`.
"""

from __future__ import annotations

import os
import sys
from html import escape
from pathlib import Path
from typing import Any

from ._pbir_rule_sources import CONTRACT, contract_rows, describe
from ._report_html import render_report, report_table

PAGE_NAME = "report.html"

_STYLE = """
nav.toc { margin: 0 0 1.5rem; font-size: 0.95rem; }
nav.toc a { margin-right: 1.25rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 0.25rem; }
details#inspector { margin-top: 2.5rem; padding-top: 1rem; border-top: 2px solid #8886; }
details#inspector > summary { cursor: pointer; font-weight: 600; font-size: 1.15rem; }
iframe { width: 100%; height: 85vh; margin-top: 0.5rem; border: 1px solid #8884; border-radius: 0.5rem;
         background: #fff; }
"""

# A link to a collapsed section opens it; so does arriving with its #id in the address.
_OPEN_SCRIPT = """<script>
(function () {
  function show(id) {
    var target = document.getElementById(id);
    if (target && target.tagName === "DETAILS") target.open = true;
  }
  document.querySelectorAll("nav.toc a").forEach(function (a) {
    a.addEventListener("click", function () { show(a.hash.slice(1)); });
  });
  if (location.hash) show(location.hash.slice(1));
})();
</script>
"""

_NAV = ('<nav class="toc">On this page: <a href="#contract">Slicer contract</a>'
        '<a href="#rules">PBIR rules</a><a href="#inspector">PBIR Inspector&#x27;s page</a></nav>\n')


def render_pbir_report(envelope: dict[str, Any], contract_note: str, inspector_html: Path | None,
                       base_dir: Path) -> str:
    """The page for one PBIR run.

    ``contract_note`` is the run header's contract line (it says why no
    contract paired); ``inspector_html`` is PBIR Inspector's TestRun.html, or
    None when it wrote none; ``base_dir`` is where the page will live, so the
    frame's link is relative and the folder can move.
    """
    results = envelope.get("test_results") or []
    rules = [r for r in results if r.get("source") != CONTRACT]
    page_envelope = {**envelope, "test_results": rules,
                     "findings": [f for f in envelope.get("findings") or [] if f.get("source") != CONTRACT]}
    before = _NAV + _contract_section(envelope.get("contract"), contract_note, results) + _rules_heading(rules)
    after = _inspector_section(inspector_html, base_dir) + _OPEN_SCRIPT
    return render_report(page_envelope, base_dir, before=before, after=after, style=_STYLE)


def write_pbir_report(envelope: dict[str, Any], path: Path, contract_note: str,
                      inspector_html: Path | None) -> Path | None:
    """Write the page to ``path``; None, with a warning, when it can't be. Never raises: a report is a convenience."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_pbir_report(envelope, contract_note, inspector_html, path.parent), encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"::warning::could not render report for {path}: {exc}", file=sys.stderr)
        return None
    return path


def _outcome(statuses: list[str]) -> str:
    failed = sum(status not in ("pass", "not run") for status in statuses)
    return f"{failed} failed" if failed else "all passed"


def _contract_section(summary: dict | None, note: str, results: list[dict]) -> str:
    heading = '<h2 id="contract">Slicer contract</h2>\n'
    if not summary:
        reason = note.removeprefix("📜 Slicer contract: ").removeprefix("none (").removesuffix(")")
        return f'{heading}<p class="none">none paired: {escape(reason)}</p>\n'
    rows = contract_rows(summary, results)
    name, checks = describe(summary)
    meta = f"<code>{escape(name)}</code> · {escape(checks)} · {_outcome([row[-1] for row in rows])}"
    table = report_table(("Rule", "Severity", "Page", "Expects", "Found", "Status"), rows, status_index=5, msg_index=4)
    return f'{heading}<p class="meta">{meta}</p>\n{table}\n'


def _rules_heading(rules: list[dict]) -> str:
    count = f"{len(rules)} result{'' if len(rules) == 1 else 's'}"
    outcome = _outcome([str(r.get("status", "pass")) for r in rules])
    return f'<h2 id="rules">PBIR rules</h2>\n<p class="meta">{count} · {outcome}</p>\n'


def _inspector_section(inspector_html: Path | None, base_dir: Path) -> str:
    summary = "<summary>PBIR Inspector&#x27;s page: screenshots, page wireframes and its own filters</summary>"
    if inspector_html is None:
        none = '<p class="none">PBIR Inspector wrote no page this run.</p>'
        return f'<details id="inspector">{summary}{none}</details>\n'
    try:
        href = escape(Path(os.path.relpath(inspector_html, base_dir)).as_posix())
    except ValueError:  # another drive, on Windows
        href = escape(inspector_html.resolve().as_uri())
    return (f'<details id="inspector">{summary}'
            f'<p class="meta"><a href="{href}" target="_blank" rel="noopener">Open it in its own tab</a></p>'
            f'<iframe src="{href}" title="PBIR Inspector&#x27;s TestRun.html" loading="lazy"></iframe>'
            "</details>\n")
