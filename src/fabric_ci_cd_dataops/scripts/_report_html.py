"""Render an analyzer envelope as a readable HTML report (Human-Readable Reports §3).

One renderer for every analyzer. Tabular Editor emits TRX and `pql-test`
emits JSON, so neither can produce a report a person would want to open;
PBIR Inspector can, and keeps its own. What makes a single renderer
possible is that the envelope already normalizes findings — see
``normalize_findings``, which is the same normalization the terminal
summary uses, so a finding never reads differently in the two places.

The renderer **computes no finding of its own**. Every value on the page
traces to a field it was handed. That is the line that keeps this a
presentation layer rather than a second analyzer, and it is what "facade,
not fork" means here.

Output is a single self-contained file: no external stylesheet, script,
or font, so it opens from disk and survives being uploaded as a CI
artifact where nothing can be fetched.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from ._analyzer_envelope import normalize_findings

# Inlined rather than linked, deliberately — see the module docstring.
# prefers-color-scheme rather than a toggle: no script, and it follows
# whatever the reader's machine already does.
_STYLE = """
:root { color-scheme: light dark; }
body {
  font-family: ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
  margin: 2rem auto; max-width: 70rem; padding: 0 1rem; line-height: 1.5;
}
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
.meta { color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }
.meta code { font-size: 0.9em; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid #8883; }
th { font-weight: 600; border-bottom: 2px solid #8886; }
td.sev { white-space: nowrap; font-variant: small-caps; }
tr.error td.sev { color: #b3261e; font-weight: 600; }
tr.warning td.sev { color: #8a6100; }
td.msg { color: #444; }
.none { color: #666; font-style: italic; }
@media (prefers-color-scheme: dark) {
  body { background: #111; color: #ddd; }
  .meta, td.msg, .none { color: #aaa; }
  tr.error td.sev { color: #f2b8b5; }
  tr.warning td.sev { color: #e8c37a; }
}
"""

_RULE_HEADERS = ("Rule", "Severity", "Object", "Message")
_TEST_HEADERS = ("Test Suite", "Test", "Expected", "Actual", "Result")

# Row classes drive severity colouring in CSS rather than inline styles, so
# the markup stays readable and a finding's text is never mixed with markup.
_SEVERITY_CLASSES = {
    "error": "error",
    "3": "error",
    "warning": "warning",
    "2": "warning",
    "fail": "error",
    "skipped": "warning",
}


def _row_class(marker: Any) -> str:
    return _SEVERITY_CLASSES.get(str(marker).strip().lower(), "")


def _table(headers: tuple[str, ...], rows: list[tuple], class_index: int) -> str:
    """Render one findings table. ``class_index`` selects the severity cell."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            css = "sev" if index == class_index else ("msg" if index == len(row) - 1 else "")
            attr = f' class="{css}"' if css else ""
            cells.append(f"<td{attr}>{escape(str(value))}</td>")
        css_class = _row_class(row[class_index])
        attr = f' class="{css_class}"' if css_class else ""
        body.append(f"<tr{attr}>{''.join(cells)}</tr>")
    return (
        f"<table><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def render_report(envelope: dict[str, Any]) -> str:
    """Return a complete, self-contained HTML report for ``envelope``.

    Deterministic: the same envelope always renders the same bytes. No
    timestamp is stamped into the page — the envelope already records
    ``duration_ms``, and a generation time would make two reports for the
    same run differ for no reason a reader benefits from.
    """
    analyzer = str(envelope.get("analyzer", "analyzer"))
    artifact = str(envelope.get("artifact_path", ""))
    status = str(envelope.get("status", ""))
    message = str(envelope.get("message", ""))
    findings = envelope.get("findings") or []

    kind, rows = normalize_findings(findings)
    if not rows:
        body = '<p class="none">No findings.</p>'
    elif kind == "tests":
        body = _table(_TEST_HEADERS, rows, class_index=4)
    else:
        body = _table(_RULE_HEADERS, rows, class_index=1)

    meta = f"<code>{escape(artifact)}</code> — status: {escape(status)}"
    if message:
        meta += f" — {escape(message)}"

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(analyzer)} — {escape(artifact)}</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        f"<h1>fab-test {escape(analyzer)}</h1>\n"
        f'<p class="meta">{meta}</p>\n'
        f"{body}\n"
        "</body>\n</html>\n"
    )


def write_report(envelope: dict[str, Any], path: Path | str) -> Path:
    """Render ``envelope`` and write it to ``path``, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(envelope), encoding="utf-8")
    return target
