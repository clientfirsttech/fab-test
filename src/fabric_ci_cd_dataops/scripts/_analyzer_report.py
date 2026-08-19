"""Shared analyzer pytest reporter (vision §2.8 R2 + R3).

Collected by ``conftest.py`` via::

    from tests._analyzer_report import AnalyzerReporter

Every marker-tagged test calls ``reporter.record(...)`` when it finishes.
At session end the reporter prints a per-artifact summary and a Markdown table,
writing the same table to ``$GITHUB_STEP_SUMMARY`` when that env var is set.

Verbosity is controlled by the ``ANALYZER_VERBOSITY`` env var (case-insensitive)
or by pytest ``-v`` / ``-vv`` counts — whichever gives the higher level:

  summary  — end-of-run table only
  default  — one line per artifact + table  (no flag)
  verbose  — default + per-finding detail   (-v  or ANALYZER_VERBOSITY=verbose)
  debug    — verbose + command/stdout/paths (-vv or ANALYZER_VERBOSITY=debug)

Verbosity never changes the files written to disk.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Any

# Ordered level mapping so we can compare levels numerically.
_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}
_DEFAULT_LEVEL = "default"


def _resolve_verbosity(pytest_verbose_count: int = 0) -> str:
    """Return the effective verbosity level string.

    Env var takes precedence when it is an explicit, recognised level.
    pytest -v / -vv is used only when the env var is absent or unrecognised.
    """
    env = os.environ.get("ANALYZER_VERBOSITY", "").lower().strip()
    if env in _LEVELS:
        return env
    # pytest -v → 1, -vv → 2
    pytest_level = min(pytest_verbose_count, 2) + 1 if pytest_verbose_count else 1
    return {v: k for k, v in _LEVELS.items()}.get(pytest_level, _DEFAULT_LEVEL)


@dataclass
class AnalyzerResult:
    analyzer: str
    artifact: str
    status: str
    findings_count: int
    duration_ms: int
    envelope_path: str = ""
    native_path: str = ""
    skip_reason: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    debug_info: str = ""  # resolved CLI command + captured stdout/stderr


class AnalyzerReporter:
    """Accumulates per-artifact results and renders them at session end."""

    def __init__(self) -> None:
        self._results: list[AnalyzerResult] = []

    def record(self, result: AnalyzerResult) -> None:
        self._results.append(result)

    def print_summary(self, verbosity: str = _DEFAULT_LEVEL) -> None:
        """Print the per-artifact lines and summary table to stdout.

        The optional ``out`` parameter makes the method testable without
        capturing ``sys.stdout``.
        """
        self._print_summary_to(sys.stdout, verbosity=verbosity)

    def _print_summary_to(self, out, verbosity: str = _DEFAULT_LEVEL) -> None:
        """Internal testable print implementation."""
        level = _LEVELS.get(verbosity, 1)

        def _write(line: str = "") -> None:
            print(line, file=out)

        if level >= _LEVELS["default"]:
            for r in self._results:
                icon = {"passed": "✅", "failed": "❌", "error": "🔥", "skipped": "⏭", "timeout": "⏰"}.get(
                    r.status, "❓"
                )
                skip_note = f"  ({r.skip_reason})" if r.skip_reason else ""
                _write(
                    f"  {icon} [{r.analyzer}] {r.artifact}  "
                    f"status={r.status}  findings={r.findings_count}  "
                    f"{r.duration_ms}ms{skip_note}"
                )
                if level >= _LEVELS["verbose"] and r.findings:
                    for f in r.findings:
                        rule = f.get("rule") or f.get("RuleName") or "?"
                        sev = f.get("severity") or f.get("Severity") or ""
                        obj = f.get("object") or f.get("ObjectName") or ""
                        _write(f"      • {rule}  sev={sev}  obj={obj}")
                if level >= _LEVELS["debug"] and r.debug_info:
                    for line in r.debug_info.splitlines():
                        _write(f"    | {line}")

        _write()
        self._print_table_to(out, self._results)
        self._write_job_summary(self._results)

    @staticmethod
    def _print_table_to(out, results: list[AnalyzerResult]) -> None:
        rows = [
            (
                r.analyzer,
                r.artifact,
                r.status,
                str(r.findings_count),
                f"{r.duration_ms}ms",
                r.envelope_path or r.native_path,
            )
            for r in results
        ]
        if not rows:
            print("No analyzer results recorded.", file=out)
            return

        headers = ("analyzer", "artifact", "status", "findings", "duration", "output")
        widths = [max(len(h), max((len(row[i]) for row in rows), default=0)) for i, h in enumerate(headers)]

        def _row(cells: tuple) -> str:
            return "  ".join(c.ljust(w) for c, w in zip(cells, widths))

        def _write(line: str = "") -> None:
            print(line, file=out)

        _write("=" * (sum(widths) + 2 * (len(widths) - 1)))
        _write(_row(headers))
        _write("-" * (sum(widths) + 2 * (len(widths) - 1)))
        for row in rows:
            _write(_row(row))
        _write("=" * (sum(widths) + 2 * (len(widths) - 1)))

    # ------------------------------------------------------------------ #



    @staticmethod
    def _write_job_summary(results: list[AnalyzerResult]) -> None:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not summary_path:
            return
        lines = [
            "## Analyzer Results\n",
            "| analyzer | artifact | status | findings | duration | output |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in results:
            icon = {"passed": "✅", "failed": "❌", "error": "🔥", "skipped": "⏭", "timeout": "⏰"}.get(r.status, "❓")
            out = r.envelope_path or r.native_path
            lines.append(
                f"| {r.analyzer} | {r.artifact} | {icon} {r.status} | {r.findings_count} | {r.duration_ms}ms | {out} |"
            )
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
