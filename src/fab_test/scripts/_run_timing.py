"""Show how long a run took, where people look (Run Timing epic, task 3).

`run.json` holds the numbers (task 1); this module turns them into the one
line a reader compares between two runs -- wall clock, summed artifact time,
the ratio between them, and the execution settings behind them -- and adds
each artifact's duration to the summary, index, and JSON rows. Runs are
compared by hand (decision 1): give each its own ``--output-dir``, open both
pages, and check the two tested the same artifacts before reading a faster
one as a speedup.
"""

from __future__ import annotations

import argparse
from typing import Any

from ._run_manifest import RunManifest


def format_duration(milliseconds: int | float | None) -> str:
    """``41.0s`` under a minute, ``4m12s`` under an hour, ``1h03m`` beyond; empty when unknown."""
    if not isinstance(milliseconds, (int, float)) or milliseconds < 0:
        return ""
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _manifest(args: argparse.Namespace | None) -> RunManifest | None:
    return getattr(args, "run_manifest", None)


def timing_summary(args: argparse.Namespace | None) -> dict[str, Any] | None:
    """Wall clock so far, summed artifact time, their ratio, and the execution settings; None without a run."""
    manifest = _manifest(args)
    if manifest is None:
        return None
    wall_ms = manifest.elapsed_ms()
    artifact_ms = sum(a["duration_ms"] for a in manifest.artifacts if a.get("duration_ms"))
    return {
        "wall_ms": wall_ms,
        "artifact_ms": artifact_ms,
        # How much ran at once: about 1 with jobs 1, approaching jobs with more.
        "parallel": round(artifact_ms / wall_ms, 1) if wall_ms else None,
        "execution": manifest.execution,
    }


def timing_line(args: argparse.Namespace | None) -> str:
    """``Wall 4m12s · artifact time 14m30s · 3.5x parallel · azure, jobs 4, workers 8``; empty without a run."""
    summary = timing_summary(args)
    if summary is None:
        return ""
    parts = [f"Wall {format_duration(summary['wall_ms'])}", f"artifact time {format_duration(summary['artifact_ms'])}"]
    if summary["parallel"] is not None:
        parts.append(f"{summary['parallel']}x parallel")
    execution = summary["execution"]
    if execution:
        parts.append(f"{execution['backend']}, jobs {execution['jobs']}, workers {execution['workers']}")
    return " · ".join(parts)


def add_durations(rows: list[dict[str, Any]], args: argparse.Namespace | None, analyzer: str | None = None) -> None:
    """Give each row the parent-measured ``duration_ms`` its artifact recorded in the run manifest."""
    manifest = _manifest(args)
    if manifest is None:
        return
    durations = {(a["analyzer"], a["artifact"]): a.get("duration_ms") for a in manifest.artifacts}
    for row in rows:
        row["duration_ms"] = durations.get((row.get("analyzer", analyzer), row.get("artifact")))


def print_timing_line(args: argparse.Namespace) -> None:
    """End a multi-artifact text run with its timing line; -q and --format json keep their own formats."""
    manifest = _manifest(args)
    if manifest is None or len(manifest.artifacts) < 2:
        return
    if getattr(args, "quiet", False) or getattr(args, "output_format", "text") != "text":
        return
    print(f"  ⏱ {timing_line(args)}")
