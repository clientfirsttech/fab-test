"""fab-test's own `--report` page for a PBIR run (PBIR Slicer Default State epic).

Every other analyzer's report is fab-test's page (bpa, pql_test, rdl): a
header, the run's meta line and one filterable table, rendered from the
envelope by `render_report`. PBIR Inspector writes its own TestRun.html,
richer (screenshots, page wireframes) but laid out its own way and blind to
the slicer contract. This is the same page for PBIR: one table holding both
rule sets, a Source column saying which each row came from (the PBIR rules,
or the slicer contract by its file name), a line above it with where the
contract lives, and PBIR Inspector's page collapsed at the bottom in a frame,
so it keeps its own look and scripts.

Like `render_report`, it computes no finding of its own: every row traces to
the envelope's `test_results` and `contract`.
"""

from __future__ import annotations

import os
import sys
from html import escape
from pathlib import Path
from typing import Any

from ._analyzer_envelope import normalize_test_results
from ._pbir_rule_sources import CONTRACT, contract_rows, describe
from ._report_html import render_report, report_table

PAGE_NAME = "report.html"
RULES_SOURCE = "PBIR rules"
_HEADERS = ("Source", "Rule", "Severity", "Object", "Message", "Status")
_RANK = {"ERROR": 0, "FAIL": 0, "WARNING": 1, "SKIPPED": 2, "SKIP": 2, "NOT RUN": 2, "PASS": 3}  # failures first

_STYLE = """
nav.toc { margin: 0 0 1.5rem; font-size: 0.95rem; }
nav.toc a { margin-right: 1.25rem; }
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

_NAV = ('<nav class="toc">On this page: <a href="#results">Results</a>'
        '<a href="#inspector">PBIR Inspector&#x27;s page</a></nav>\n')


def render_pbir_report(envelope: dict[str, Any], unpaired: str, inspector_html: Path | None,
                       base_dir: Path) -> str:
    """The page for one PBIR run.

    ``unpaired`` says why no contract paired (shown only when none did);
    ``inspector_html`` is PBIR Inspector's TestRun.html, or
    None when it wrote none; ``base_dir`` is where the page will live, so the
    frame's link is relative and the folder can move.
    """
    summary = envelope.get("contract")
    rows = rule_rows(summary, envelope.get("test_results") or [])
    table = report_table(_HEADERS, rows, class_index=2, status_index=5, msg_index=4)
    before = _NAV + _sources(summary, unpaired, rows)
    after = _inspector_section(inspector_html, base_dir) + _OPEN_SCRIPT
    return render_report(envelope, base_dir, before=before, after=after, style=_STYLE, table=table)


def write_pbir_report(envelope: dict[str, Any], path: Path, unpaired: str,
                      inspector_html: Path | None) -> Path | None:
    """Write the page to ``path``; None, with a warning, when it can't be. Never raises: a report is a convenience."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_pbir_report(envelope, unpaired, inspector_html, path.parent), encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"::warning::could not render report for {path}: {exc}", file=sys.stderr)
        return None
    return path


def rule_rows(summary: dict | None, results: list[dict[str, Any]]) -> list[tuple]:
    """(source, rule, severity, object, message, status) for both rule sets, failures first.

    A contract check is one row, its worst result across the pages it ran on:
    the message is what it found when it didn't pass, else what it expects.
    A PBIR rule is a row per object it ran on, as on every other report.
    """
    rows: list[tuple] = []
    if summary:
        source = f"Slicer contract ({Path(summary['file']).name})"
        rows += [(source, rule, severity, page, found or expects, status.upper())
                 for rule, severity, page, expects, found, status in contract_rows(summary, results)]
    _kind, rules = normalize_test_results([r for r in results if r.get("source") != CONTRACT])
    rows += [(RULES_SOURCE, *row) for row in rules]
    return sorted(rows, key=lambda row: _RANK.get(row[5], 1))


_NOT_RUN = ("NOT RUN", "SKIP", "SKIPPED")


def _outcome(rows: list[tuple]) -> str:
    """`2 failed`, `all passed`, `1 passed, 2 not run`, or `nothing ran` (never "all passed" for no passes)."""
    passed = sum(row[5] == "PASS" for row in rows)
    not_run = sum(row[5] in _NOT_RUN for row in rows)
    failed = len(rows) - passed - not_run
    if not failed and not passed:
        return "nothing ran"
    counts = [f"{failed} failed"] if failed else [f"{passed} passed"] if not_run else ["all passed"]
    return ", ".join(counts + ([f"{not_run} not run"] if not_run else []))


def _sources(summary: dict | None, unpaired: str, rows: list[tuple]) -> str:
    """Where each rule set came from, with its counts: the contract's file, or why none paired."""
    contract = [row for row in rows if row[0] != RULES_SOURCE]
    rules = [row for row in rows if row[0] == RULES_SOURCE]
    if summary:
        name, checks = describe(summary)
        line = f"Slicer contract: <code>{escape(name)}</code> · {escape(checks)} · {_outcome(contract)}"
    else:
        line = f"Slicer contract: none paired: {escape(unpaired)}"
    count = f"{len(rules)} result{'' if len(rules) == 1 else 's'}"
    return f'<p class="meta" id="results">{line}<br>{RULES_SOURCE}: {count} · {_outcome(rules)}</p>\n'


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
