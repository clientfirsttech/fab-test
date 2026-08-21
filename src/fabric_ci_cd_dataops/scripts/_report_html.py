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

import os
import sys
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
    # Run time comes from the envelope, never from render time: a report
    # regenerated from a stored envelope must not claim a different moment
    # than the original. Labelled UTC because a bare timestamp invites the
    # reader to assume local.
    started_at = str(envelope.get("started_at", ""))
    if started_at:
        meta += f" — run {escape(started_at)} UTC"
    duration_ms = envelope.get("duration_ms")
    if isinstance(duration_ms, (int, float)) and duration_ms:
        meta += f" in {duration_ms / 1000:.1f}s"
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


INDEX_FILENAME = "index.html"

_TRUTHY = {"1", "true", "yes", "on"}


def resolve_report(args: Any, file_config: dict[str, Any] | None = None) -> bool:
    """Resolve whether reports are on, via the centralized precedence chain.

    ``--report`` / ``--no-report`` > ``ANALYZER_REPORT`` > config file >
    default. Lives here rather than in `fab_test.py` so the summary module
    can ask the same question without importing the CLI, which would be a
    cycle. Default False: generation is opt-in.
    """
    from ._config import resolve_setting

    config = file_config if file_config is not None else getattr(args, "file_config", None)
    value, _origin = resolve_setting(
        "report",
        cli_value=getattr(args, "report", None),
        env_var="ANALYZER_REPORT",
        file_config=config or {},
        packaged_default=False,
    )
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return bool(value)


def render_index(rows: list[dict[str, Any]], base_dir: Path) -> str:
    """Render the per-run index linking every report and envelope.

    Takes the same rows the aggregate summary prints, so the two cannot
    report different counts for one run -- there is no second pass over
    the envelopes to disagree with.

    Links are relative to ``base_dir`` (where the index is written) so the
    page keeps working when the results directory is moved or downloaded
    as a CI artifact.
    """

    def _link(path: str | None) -> str:
        if not path:
            return '<span class="none">—</span>'
        try:
            href = Path(path).resolve().relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            href = Path(path).as_posix()
        return f'<a href="{escape(href)}">{escape(Path(path).name)}</a>'

    body = []
    for r in rows:
        css = _row_class(r.get("status"))
        attr = f' class="{css}"' if css else ""
        body.append(
            f"<tr{attr}>"
            f"<td>{escape(str(r.get('analyzer', '')))}</td>"
            f"<td>{escape(str(r.get('artifact', '')))}</td>"
            f"<td class=\"sev\">{escape(str(r.get('status', '')))}</td>"
            f"<td>{escape(str(r.get('errors', 0)))}</td>"
            f"<td>{escape(str(r.get('warnings', 0)))}</td>"
            f"<td>{_link(r.get('report_path'))}</td>"
            f"<td>{_link(r.get('output_path'))}</td>"
            "</tr>"
        )
    headers = ("Analyzer", "Artifact", "Status", "Errors", "Warnings", "Report", "Envelope")
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    totals_errors = sum(int(r.get("errors", 0) or 0) for r in rows)
    totals_warnings = sum(int(r.get("warnings", 0) or 0) for r in rows)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>fab-test run</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        "<h1>fab-test run</h1>\n"
        f'<p class="meta">{totals_errors} error(s), {totals_warnings} warning(s) '
        f"across {len(rows)} artifact(s)</p>\n"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>\n"
        "</body>\n</html>\n"
    )


def write_index(rows: list[dict[str, Any]], output_dir: Path | str) -> Path | None:
    """Write the per-run index under ``output_dir``. Never raises."""
    base = Path(output_dir)
    target = base / INDEX_FILENAME
    try:
        base.mkdir(parents=True, exist_ok=True)
        target.write_text(render_index(rows, base), encoding="utf-8")
    except (OSError, ValueError, TypeError) as exc:
        print(f"::warning::could not write {target}: {exc}", file=sys.stderr)
        return None
    return target


def report_enabled() -> bool:
    """Whether report generation is switched on for this run.

    Reads ``ANALYZER_REPORT``, set by `fab-test` when ``--report`` resolves
    true — the same channel as ``ANALYZER_VERBOSITY`` and
    ``ANALYZER_OUTPUT_MODE``, so no command builder needs a new argument.

    Off by default, deliberately: generation is opt-in so no existing run
    gets slower and no pipeline starts collecting artifacts it did not ask
    for.
    """
    return os.environ.get("ANALYZER_REPORT", "").strip().lower() in _TRUTHY


def attach_report(envelope: dict[str, Any], envelope_path: Path | str) -> None:
    """Render a report beside ``envelope_path`` and record it on the envelope.

    A no-op unless generation is enabled, and a no-op when the envelope
    already carries ``native_html_output_path`` — that means the upstream
    tool produced its own report (PBIR Inspector's ``TestRun.html``),
    which is richer than anything rendered from the envelope and must not
    be overwritten.

    Never raises. A report is a convenience, so a failure to render one is
    reported and swallowed rather than turned into a failed build: exit
    codes belong to findings, not to presentation.
    """
    if not report_enabled() or envelope.get("native_html_output_path"):
        return
    target = Path(envelope_path).parent / "report.html"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_report(envelope), encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"::warning::could not render report for {target}: {exc}", file=sys.stderr)
        return
    envelope["native_html_output_path"] = str(target)
