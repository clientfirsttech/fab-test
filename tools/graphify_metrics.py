"""Content-free, local observations and honest matched-pair savings reports."""

import json
import math
import re
from pathlib import Path
from statistics import median

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
REVISION = re.compile(r"[a-f0-9]{64}\Z")
MEASURES = (
    "elapsed_seconds", "tool_calls", "context_chars", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens",
)
KEYS = ("assistant", "benchmark", "revision", "model", "source", "scope")
REQUIRED = {"assistant", "mode", "benchmark", "revision", "model", "source", "elapsed_seconds", "correct"}
ALLOWED = REQUIRED | set(MEASURES) | {"scope", "token_source"}


def _validate(value: dict) -> dict:
    if not isinstance(value, dict) or not value.keys() >= REQUIRED or value.keys() - ALLOWED:
        raise ValueError("observation fields must be content-free aggregates only")
    value = {"scope": "task", **value}
    if value["assistant"] not in ("claude", "copilot") or value["mode"] not in ("baseline", "graph", "maintenance"):
        raise ValueError("assistant must be claude/copilot; mode baseline/graph/maintenance")
    if value["source"] not in ("manual", "provider", "harness") or value["scope"] not in ("task", "full"):
        raise ValueError("source must be manual/provider/harness; scope task/full")
    if value.get("token_source") not in (None, "provider_reported"):
        raise ValueError("token_source must be provider_reported or null")
    if value.get("token_source") != "provider_reported" and any(
        value.get(key) is not None for key in MEASURES if key.endswith("_tokens")
    ):
        raise ValueError("token counts require token_source provider_reported")
    for key in ("benchmark", "model"):
        if not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key]):
            raise ValueError("use bounded noncontent identifiers, never paths or prompts")
    if not isinstance(value["revision"], str) or not REVISION.fullmatch(value["revision"]):
        raise ValueError("revision must be the 64-character status fingerprint")
    if value["correct"] not in (True, False) or type(value["correct"]) is not bool:
        raise ValueError("correct must be a boolean")
    if value["elapsed_seconds"] is None:
        raise ValueError("elapsed_seconds is required")
    for key in MEASURES:
        measure = value.get(key)
        if measure is None:
            continue
        if (
            isinstance(measure, bool) or not isinstance(measure, (int, float))
            or not 0 <= measure <= 10**15 or not math.isfinite(measure)
        ):
            raise ValueError("measurements must be finite nonnegative numbers or null")
        if key != "elapsed_seconds" and not isinstance(measure, int):
            raise ValueError("counts must be integers")
    return value


def _read(path: Path) -> list[dict]:
    if path.is_symlink():
        raise ValueError("metrics must not be a symlink")
    if not path.exists():
        return []
    return [_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def record(cache: Path, observation: dict) -> dict:
    """Append one aggregate; missing measurements remain unknown, not zero."""
    if cache.is_symlink():
        raise ValueError("cache must not be a symlink")
    value = _validate(observation)
    path = cache / "metrics.jsonl"
    cache.mkdir(exist_ok=True)
    lock = cache / "metrics.lock"
    with lock.open("x", encoding="utf-8"):
        pass
    try:
        _append(path, value)
    finally:
        lock.unlink()
    return {"recorded": True}


def _append(path: Path, value: dict) -> None:
    existing = _read(path)
    identity = tuple(value[key] for key in (*KEYS, "mode"))
    if any(tuple(row[key] for key in (*KEYS, "mode")) == identity for row in existing):
        raise ValueError("duplicate observation: use a new benchmark id for a new trial")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, allow_nan=False) + "\n")


def _summarize(rows: list[dict]) -> dict:
    by_key = {}
    for row in rows:
        key = tuple(row[field] for field in KEYS)
        group = by_key.setdefault(key, {})
        if row["mode"] in group:
            raise ValueError("duplicate metrics found")
        group[row["mode"]] = row
    pairs = [
        group for group in by_key.values()
        if all(mode in group and group[mode]["correct"] for mode in ("baseline", "graph"))
    ]
    modes = ("baseline", "graph")
    complete = [group for group in by_key.values() if all(mode in group for mode in modes)]
    trial_counts = {mode: sum(row["mode"] == mode for row in rows) for mode in modes}
    unmatched = {
        mode: sum(mode in group and other not in group for group in by_key.values())
        for mode, other in (("baseline", "graph"), ("graph", "baseline"))
    }
    result = {
        "total_trials": sum(trial_counts.values()),
        "trial_counts": trial_counts,
        "complete_pairs": len(complete),
        "pairs": len(pairs),
        "incorrect_trial_counts": {
            mode: sum(row["mode"] == mode and not row["correct"] for row in rows) for mode in modes
        },
        "unmatched_workloads": sum(unmatched.values()),
        "unmatched_workload_counts": unmatched,
        "correctness_regressions": sum(
            group["baseline"]["correct"] and not group["graph"]["correct"] for group in complete
        ),
    }
    for measure in MEASURES:
        savings = [
            group["baseline"][measure] - group["graph"][measure]
            for group in pairs
            if group["baseline"].get(measure) is not None and group["graph"].get(measure) is not None
        ]
        name = "actual_" + measure if measure in ("input_tokens", "output_tokens") else measure
        result[f"median_{name}_saved"] = median(savings) if savings else None
        result[f"{name}_measured_pairs"] = len(savings)
    context = result["median_context_chars_saved"]
    result["median_estimated_context_tokens_saved"] = context / 4 if context is not None else None
    percentages = [
        100 * (group["baseline"]["elapsed_seconds"] - group["graph"]["elapsed_seconds"])
        / group["baseline"]["elapsed_seconds"]
        for group in pairs if group["baseline"]["elapsed_seconds"] > 0
    ]
    result["median_elapsed_percent_saved"] = median(percentages) if percentages else None
    maintenance = [row["elapsed_seconds"] for row in rows if row["mode"] == "maintenance"]
    result["maintenance_seconds"] = sum(maintenance) if maintenance else None
    result["maintenance_observations"] = len(maintenance)
    full = [
        group for group in pairs
        if group["baseline"]["scope"] == "full" and "maintenance" in group and group["maintenance"]["correct"]
    ]
    result["full_workload_pairs"] = len(full)
    result["net_elapsed_seconds_saved"] = median([
        group["baseline"]["elapsed_seconds"] - group["graph"]["elapsed_seconds"]
        - group["maintenance"]["elapsed_seconds"] for group in full
    ]) if full else None
    return result


def report(cache: Path) -> dict:
    """Report medians per assistant, paired only on identical measurement provenance."""
    rows = _read(cache / "metrics.jsonl")
    return {
        "assistants": {assistant: _summarize([row for row in rows if row["assistant"] == assistant])
                       for assistant in ("claude", "copilot")},
        "estimate": "context_chars / 4 is approximate context tokens, not provider usage or billing",
        "net_policy": "net elapsed savings require correct matched full workloads and measured maintenance",
    }
