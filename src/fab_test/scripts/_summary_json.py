"""`--format json` for one analyzer's results: exactly one document on stdout.

Split out of `fab_test_summary._print_summary` (which it was pushing past the
branch budget, in a module at its size ceiling). Under `all` and `local` the
command prints one aggregate document itself, so an analyzer's own document
used to make stdout several concatenated documents that `json.load` refused
("Extra data"). There the rows are kept on ``args`` for `local` to fold into
its one document; `all` already lists every artifact in its aggregate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .fab_test_summary import _envelope_error_warning_counts, _read_artifact_envelope, _report_path_for

_AGGREGATE_COMMANDS = ("all", "local")


def json_rows(name: str, results: list[tuple[str, int]], output_dir: Path | None) -> list[dict[str, Any]]:
    """One row per artifact: its status, counts, and where its envelope and report are."""
    rows: list[dict[str, Any]] = []
    for stem, code in results:
        data = _read_artifact_envelope(output_dir, name, stem) if output_dir is not None else None
        errors, warnings = _envelope_error_warning_counts(data)
        if data and data.get("status") in {"skipped", "warning"} and code == 0:
            status = data["status"]
        else:
            status = "failed" if code != 0 else "passed"
        rows.append({
            "artifact": stem,
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "output_path": str(output_dir / name / stem / "envelope.json") if output_dir else "",
            # Same key as the `all` summary emits. A consumer should not
            # have to branch on how many analyzers happened to run.
            "report_path": _report_path_for(data),
        })
    return rows


def print_json_summary(
    name: str, results: list[tuple[str, int]], output_dir: Path | None, args: argparse.Namespace | None
) -> int:
    """Print this analyzer's document, or keep its rows for the aggregate; return the worst exit code."""
    rows = json_rows(name, results, output_dir)
    if getattr(args, "analyzer", None) in _AGGREGATE_COMMANDS:
        args.__dict__.setdefault("_json_rows", {})[name] = rows
    else:
        print(json.dumps({"analyzer": name, "artifacts": rows}, indent=2))
    return max((code for _, code in results), default=0)
