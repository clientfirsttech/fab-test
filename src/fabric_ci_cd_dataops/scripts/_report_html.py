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
or font -- it opens from disk and survives being uploaded as a CI
artifact where nothing can be fetched. The full test-results table also
carries a small inline script (search and column sort); "self-contained"
is the invariant that holds, not "no script" -- the script never fetches,
links, or references anything outside the page itself.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from ._analyzer_envelope import normalize_findings, normalize_test_results
from ._git_context import git_context

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
/* Filter-by-status control (HTML Report Format §4): pure CSS.
   Hidden radios drive tab-styled labels; each label's :checked state hides
   every table row whose data-status disagrees, via a sibling selector.
   Search and column sort (Search and Sort epic) are the one exception to
   "no script" -- see .search-box and _SEARCH_SORT_SCRIPT in
   _filterable_table; they only ever touch elements inside .filter-bar. */
.filter-bar input[type=radio] { position: absolute; opacity: 0; pointer-events: none; }
.filter-bar label {
  display: inline-block; padding: 0.3rem 0.9rem; margin: 0 0.3rem 1rem 0;
  border: 1px solid #8886; border-radius: 999px; cursor: pointer; font-size: 0.85rem;
}
.filter-bar input:checked + label { background: #8882; font-weight: 600; }
#f-error:checked ~ table tr[data-status]:not([data-status="error"]) { display: none; }
#f-warning:checked ~ table tr[data-status]:not([data-status="warning"]) { display: none; }
#f-pass:checked ~ table tr[data-status]:not([data-status="pass"]) { display: none; }
.search-box {
  display: block; width: 100%; max-width: 20rem; margin-bottom: 0.75rem;
  padding: 0.35rem 0.6rem; font-size: 0.85rem;
  border: 1px solid #8886; border-radius: 0.4rem; background: transparent; color: inherit;
}
.filter-bar table th { cursor: pointer; user-select: none; }
.filter-bar table th:hover { background: #8882; }
.sort-arrow { font-size: 0.85em; }
.empty-msg { color: #666; font-style: italic; }
@media (prefers-color-scheme: dark) {
  .empty-msg { color: #aaa; }
}
"""

_RULE_HEADERS = ("Rule", "Severity", "Object", "Message")
_RULE_STATUS_HEADERS = (*_RULE_HEADERS, "Status")
_TEST_HEADERS = ("Test Suite", "Test", "Expected", "Actual", "Result")
_TEST_EVIDENCE_HEADERS = (*_TEST_HEADERS, "Evidence")
_TEST_REPORT_HEADERS = (*_TEST_HEADERS, "Report Page")
_TEST_EVIDENCE_REPORT_HEADERS = (*_TEST_EVIDENCE_HEADERS, "Report Page")

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

# The filter's four buckets. A row whose status maps to none of these
# (an unrecognized label) still gets "skip" -- visible under All, hidden
# under every specific filter, rather than dropped or crashing.
_STATUS_BUCKETS = {
    "pass": "pass",
    "passed": "pass",
    "error": "error",
    "fail": "error",
    "failed": "error",
    "warning": "warning",
    "warn": "warning",
    "skip": "skip",
    "skipped": "skip",
}

_STATUS_FILTERS = (("all", "All"), ("error", "Errors"), ("warning", "Warnings"), ("pass", "Passed"))

# Search and sort for the full test-results table (Search and Sort epic).
# Scoped entirely to one .filter-bar's own elements -- no global listener,
# no external reference (no src=, fetch, or http(s)://) -- so it stays
# within the self-contained-report guarantee the module docstring states.
# Search sets each row's own inline `display`; leaving it empty (rather
# than "") when a row matches lets the status-filter CSS rule above keep
# deciding that row's visibility, so the two filters compose instead of
# fighting over the same property.
# Each header gets its own `.sort-arrow` child span at setup time (Sort
# Direction Indicator epic) rather than concatenating text into the header
# itself, so clearing a previous column's arrow is one targeted textContent
# reset instead of string surgery on whatever label the header started with.
_SEARCH_SORT_SCRIPT = """<script>
(function () {
  document.querySelectorAll(".filter-bar").forEach(function (bar) {
    var table = bar.querySelector("table");
    var tbody = table && table.querySelector("tbody");
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.rows);
    var emptyMsg = bar.querySelector(".empty-msg");

    function refreshEmptyMessage() {
      if (!emptyMsg) return;
      var anyVisible = rows.some(function (row) {
        return row.style.display !== "none" && getComputedStyle(row).display !== "none";
      });
      emptyMsg.hidden = anyVisible;
    }

    var search = bar.querySelector(".search-box");
    if (search) {
      search.addEventListener("input", function () {
        var query = search.value.toLowerCase();
        rows.forEach(function (row) {
          row.style.display = row.textContent.toLowerCase().indexOf(query) === -1 ? "none" : "";
        });
        refreshEmptyMessage();
      });
    }
    bar.querySelectorAll('input[name="statusFilter"]').forEach(function (radio) {
      radio.addEventListener("change", refreshEmptyMessage);
    });

    var headers = Array.prototype.slice.call(table.querySelectorAll("th"));
    headers.forEach(function (th, index) {
      var ascending = true;
      var arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      th.appendChild(arrow);
      th.addEventListener("click", function () {
        var sorted = rows.slice().sort(function (a, b) {
          var left = a.cells[index].textContent.trim();
          var right = b.cells[index].textContent.trim();
          var result = left.localeCompare(right, undefined, { numeric: true });
          return ascending ? result : -result;
        });
        sorted.forEach(function (row) { tbody.appendChild(row); });
        headers.forEach(function (h) { h.querySelector(".sort-arrow").textContent = ""; });
        arrow.textContent = ascending ? " ▲" : " ▼";
        ascending = !ascending;
      });
    });

    refreshEmptyMessage();
  });
})();
</script>"""


def _row_class(marker: Any) -> str:
    return _SEVERITY_CLASSES.get(str(marker).strip().lower(), "")


def _status_bucket(marker: Any) -> str:
    return _STATUS_BUCKETS.get(str(marker).strip().lower(), "skip")


def _evidence_link(label: str, path_str: str, base_dir: Path | None) -> str:
    """One evidence link, relative to ``base_dir`` (the report's own directory).

    Evidence (Playwright's screenshot/console/network files) lives under a
    sibling directory of the report, not a descendant of it, so this uses
    ``os.path.relpath`` rather than ``Path.relative_to`` (which only
    resolves an ancestor relationship) -- the same distinction that would
    make `render_index`'s `_link` fail here too if it were reused as-is.
    """
    try:
        href = (
            Path(os.path.relpath(str(Path(path_str).resolve()), start=str(base_dir.resolve()))).as_posix()
            if base_dir is not None
            else Path(path_str).as_posix()
        )
    except ValueError:
        href = Path(path_str).as_posix()
    return f'<a href="{escape(href)}">{escape(label)}</a>'


def _report_link_cell(link: Any) -> str:
    """Render a row's ``{label, href}`` deep link to the live report page/bookmark.

    Unlike evidence (a sibling file on disk), ``href`` is an external,
    already-absolute URL -- no ``base_dir``-relative resolution applies.
    """
    if not link or not link.get("href"):
        return ""
    href = escape(link["href"])
    label = escape(link.get("label") or link["href"])
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>'


def _evidence_cell(evidence: Any, base_dir: Path | None) -> str:
    """Render a row's evidence dict (``{label: path}``) as space-joined links."""
    if not evidence:
        return ""
    return " ".join(
        _evidence_link(label, path_str, base_dir)
        for label, path_str in evidence.items()
        if path_str
    )


def _table(
    headers: tuple[str, ...],
    rows: list[tuple],
    class_index: int,
    status_index: int | None = None,
    msg_index: int | None = None,
    evidence_index: int | None = None,
    report_link_index: int | None = None,
    base_dir: Path | None = None,
) -> str:
    """Render one findings table. ``class_index`` selects the severity cell.

    ``status_index``, when given, additionally drives row colouring (over
    ``class_index``) and tags each row with ``data-status`` for the CSS
    filter -- used only by the full-list view, so existing findings-only
    callers render exactly as before. ``evidence_index``, when given,
    renders that column's value (a ``{label: path}`` dict) as links
    instead of escaped text -- used only when a `test_results` row
    actually carries evidence (see `normalize_test_results`).
    ``report_link_index``, when given, renders that column's value (a
    ``{label, href}`` dict) as a single external link -- used only when a
    `test_results` row actually carries a report deep link.
    """
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = []
    for row in rows:
        row_msg_index = msg_index if msg_index is not None else len(row) - 1
        cells = []
        for index, value in enumerate(row):
            if index == evidence_index:
                cells.append(f"<td>{_evidence_cell(value, base_dir)}</td>")
                continue
            if index == report_link_index:
                cells.append(f"<td>{_report_link_cell(value)}</td>")
                continue
            css = "sev" if index == class_index else ("msg" if index == row_msg_index else "")
            attr = f' class="{css}"' if css else ""
            cells.append(f"<td{attr}>{escape(str(value))}</td>")
        marker = row[status_index] if status_index is not None else row[class_index]
        css_class = _row_class(marker)
        class_attr = f' class="{css_class}"' if css_class else ""
        data_attr = f' data-status="{_status_bucket(marker)}"' if status_index is not None else ""
        body.append(f"<tr{class_attr}{data_attr}>{''.join(cells)}</tr>")
    return (
        f"<table><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _filter_controls() -> str:
    """Four radio-input tabs, checked state driving the CSS in ``_STYLE``."""
    parts = []
    for key, label in _STATUS_FILTERS:
        checked = " checked" if key == "all" else ""
        parts.append(
            f'<input type="radio" name="statusFilter" id="f-{key}"{checked}>'
            f'<label for="f-{key}">{escape(label)}</label>'
        )
    return "".join(parts)


def _filterable_table(
    headers: tuple[str, ...],
    rows: list[tuple],
    class_index: int,
    status_index: int,
    msg_index: int | None = None,
    evidence_index: int | None = None,
    report_link_index: int | None = None,
    base_dir: Path | None = None,
) -> str:
    """A full test-result table with a status filter, search box, and column sort.

    The status filter is pure CSS; search and sort are the small inline
    script in ``_SEARCH_SORT_SCRIPT`` -- see its docstring for how the two
    compose without one undoing the other.
    """
    table = _table(
        headers,
        rows,
        class_index=class_index,
        status_index=status_index,
        msg_index=msg_index,
        evidence_index=evidence_index,
        report_link_index=report_link_index,
        base_dir=base_dir,
    )
    return (
        '<div class="filter-bar">'
        f"{_filter_controls()}"
        '<input type="search" class="search-box" placeholder="Search…" aria-label="Search results">'
        f"{table}"
        '<p class="empty-msg" hidden>No matching rows.</p>'
        f"{_SEARCH_SORT_SCRIPT}"
        "</div>"
    )


def _render_test_results_table(rows: list[tuple], base_dir: Path | None) -> str:
    """Render the full test-results table, with Evidence and Report Page as
    independent additive columns (index 5 and 6 respectively).

    Split out of ``render_report`` so its four evidence/report_link
    combinations don't push that function's own branch count over budget --
    each row always carries both fields (see ``normalize_test_results``);
    only their presence across the whole table decides which columns show.
    """
    has_evidence = any(row[5] for row in rows)
    has_report_link = any(row[6] for row in rows)
    common = {"class_index": 4, "status_index": 4, "msg_index": 3, "base_dir": base_dir}

    if has_evidence and has_report_link:
        return _filterable_table(
            _TEST_EVIDENCE_REPORT_HEADERS, rows, evidence_index=5, report_link_index=6, **common
        )
    if has_evidence:
        return _filterable_table(
            _TEST_EVIDENCE_HEADERS, [row[:6] for row in rows], evidence_index=5, **common
        )
    if has_report_link:
        return _filterable_table(
            _TEST_REPORT_HEADERS,
            [row[:5] + row[6:] for row in rows],
            report_link_index=5,
            **common,
        )
    return _filterable_table(_TEST_HEADERS, [row[:5] for row in rows], class_index=4, status_index=4)


def render_report(envelope: dict[str, Any], base_dir: Path | None = None) -> str:
    """Return a complete, self-contained HTML report for ``envelope``.

    Deterministic given the same ``base_dir``: the same envelope always
    renders the same bytes. No timestamp is stamped into the page — the
    envelope already records ``duration_ms``, and a generation time would
    make two reports for the same run differ for no reason a reader
    benefits from. ``base_dir`` is the directory the report itself will
    live in -- the one piece of filesystem context this otherwise-pure
    function needs, so evidence links (Playwright's screenshots/logs) can
    resolve relative to the report the same way `render_index`'s links
    resolve relative to the index; omit it and a `test_results` row that
    happens to carry evidence links with an absolute path instead.
    """
    analyzer = str(envelope.get("analyzer", "analyzer"))
    artifact = str(envelope.get("artifact_path", ""))
    status = str(envelope.get("status", ""))
    message = str(envelope.get("message", ""))
    test_results = envelope.get("test_results") or []

    if test_results:
        # Every test conducted, filterable by status -- an analyzer opts in
        # simply by populating this field; no new HTML to write. Supersedes
        # the findings-only table below, since findings is a subset of this.
        kind, rows = normalize_test_results(test_results)
        if kind == "tests":
            # Evidence (index 5) and report_link (index 6) are both additive
            # columns -- present only when some row actually carries one, so
            # an analyzer with neither (pql-test today) renders exactly as
            # it did before either column existed. See
            # `_render_test_results_table` for the four combinations.
            body = _render_test_results_table(rows, base_dir)
        else:
            body = _filterable_table(
                _RULE_STATUS_HEADERS, rows, class_index=1, status_index=4, msg_index=3
            )
    else:
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
    target.write_text(render_report(envelope, base_dir=target.parent), encoding="utf-8")
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


def _format_run_metadata(metadata: dict[str, str]) -> str:
    """Return the escaped 'who/when/where' line for the index header.

    Absent fields (no git checkout, no CI env vars) render as an em-dash
    rather than an empty cell -- a blank reads as a bug, a placeholder
    reads as "not available here".
    """
    generated_at = metadata.get("generated_at") or ""
    actor = escape(metadata.get("actor") or "—")
    branch = escape(metadata.get("branch") or "—")
    commit = metadata.get("commit") or ""
    commit_short = escape(commit[:7]) if commit else "—"
    when = f"Generated {escape(generated_at)} UTC — " if generated_at else ""
    return f"{when}{actor} on {branch} @ {commit_short}"


def render_index(
    rows: list[dict[str, Any]],
    base_dir: Path,
    metadata: dict[str, str] | None = None,
) -> str:
    """Render the per-run index linking every report and envelope.

    Takes the same rows the aggregate summary prints, so the two cannot
    report different counts for one run -- there is no second pass over
    the envelopes to disagree with.

    Links are relative to ``base_dir`` (where the index is written) so the
    page keeps working when the results directory is moved or downloaded
    as a CI artifact.

    ``metadata`` (generated_at/actor/branch/commit) is optional and
    rendered verbatim -- gathering it is `write_index`'s job, not this
    function's, so the same input here always renders the same bytes.
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
    run_meta_line = (
        f'<p class="meta run-meta">{_format_run_metadata(metadata)}</p>\n' if metadata else ""
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>fab-test run</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        "<h1>fab-test run</h1>\n"
        f"{run_meta_line}"
        f'<p class="meta">{totals_errors} error(s), {totals_warnings} warning(s) '
        f"across {len(rows)} artifact(s)</p>\n"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>\n"
        "</body>\n</html>\n"
    )


def _collect_run_metadata() -> dict[str, str]:
    """Gather the index's 'who/when/where' -- the IO half `render_index` avoids.

    ``git_context()`` already degrades to empty strings outside a git
    checkout and with no CI env vars set, so this never raises; the empty
    strings become the index's "—" placeholders.
    """
    ctx = git_context()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "actor": ctx.get("actor", ""),
        "branch": ctx.get("branch", ""),
        "commit": ctx.get("commit", ""),
    }


def write_index(
    rows: list[dict[str, Any]],
    output_dir: Path | str,
    metadata: dict[str, str] | None = None,
) -> Path | None:
    """Write the per-run index under ``output_dir``. Never raises.

    Gathers run metadata (timestamp, git identity) itself when ``metadata``
    is not supplied -- the one call site that needs the real clock and the
    real repository, so `render_index` can stay a pure function of its
    arguments.
    """
    base = Path(output_dir)
    target = base / INDEX_FILENAME
    run_metadata = metadata if metadata is not None else _collect_run_metadata()
    try:
        base.mkdir(parents=True, exist_ok=True)
        target.write_text(render_index(rows, base, metadata=run_metadata), encoding="utf-8")
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
        target.write_text(render_report(envelope, base_dir=target.parent), encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"::warning::could not render report for {target}: {exc}", file=sys.stderr)
        return
    envelope["native_html_output_path"] = str(target)
