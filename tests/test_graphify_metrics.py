"""Aggregate observations cannot leak content or invent token savings."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from graphify_metrics import record, report


def observation(mode="baseline", **changes):
    return {
        "assistant": "copilot",
        "mode": mode,
        "benchmark": "review1",
        "revision": "a" * 64,
        "model": "model1",
        "source": "manual",
        "elapsed_seconds": 100 if mode == "baseline" else 50,
        "tool_calls": 10 if mode == "baseline" else 5,
        "context_chars": 4000 if mode == "baseline" else 2000,
        "correct": True,
        **changes,
    }


def test_paired_report_distinguishes_estimates_from_actual_tokens(tmp_path):
    record(tmp_path, observation())
    record(tmp_path, observation("graph"))
    result = report(tmp_path)
    assert result["assistants"]["copilot"]["pairs"] == 1
    assert result["assistants"]["copilot"]["median_context_chars_saved"] == 2000
    assert result["assistants"]["copilot"]["median_estimated_context_tokens_saved"] == 500
    assert result["assistants"]["copilot"]["median_actual_input_tokens_saved"] is None
    assert result["assistants"]["copilot"]["net_elapsed_seconds_saved"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"elapsed_seconds": float("nan")},
        {"elapsed_seconds": -1},
        {"tool_calls": 1.5},
        {"benchmark": "/private/file"},
        {"query": "private"},
        {"correct": "yes"},
        {"assistant": "unknown"},
        {"input_tokens": -1},
        {"elapsed_seconds": None},
        {"elapsed_seconds": 10**1000},
    ],
)
def test_rejects_invalid_or_content_bearing_metrics(tmp_path, changes):
    with pytest.raises(ValueError):
        record(tmp_path, observation(**changes))


def test_no_cross_revision_model_or_incorrect_pairs(tmp_path):
    record(tmp_path, observation())
    record(tmp_path, observation("graph", model="model2"))
    record(tmp_path, observation("graph", revision="b" * 64))
    record(tmp_path, observation("graph", correct=False))
    assert report(tmp_path)["assistants"]["copilot"]["pairs"] == 0


def test_duplicates_rejected_and_empty_report_safe(tmp_path):
    empty = report(tmp_path)["assistants"]["claude"]
    assert empty["pairs"] == 0
    assert empty["maintenance_seconds"] is None
    record(tmp_path, observation())
    with pytest.raises(ValueError, match="duplicate"):
        record(tmp_path, observation())


def test_actual_tokens_and_full_workload_net_cost(tmp_path):
    record(tmp_path, observation(
        input_tokens=100, cache_read_tokens=90, scope="full", token_source="provider_reported",
    ))
    record(tmp_path, observation(
        "graph", input_tokens=50, cache_read_tokens=80, scope="full", token_source="provider_reported",
    ))
    record(
        tmp_path,
        {
            "assistant": "copilot", "mode": "maintenance", "benchmark": "review1",
            "revision": "a" * 64, "model": "model1", "source": "manual",
            "elapsed_seconds": 10, "correct": True, "scope": "full",
        },
    )
    result = report(tmp_path)["assistants"]["copilot"]
    assert result["median_actual_input_tokens_saved"] == 50
    assert result["median_cache_read_tokens_saved"] == 10
    assert result["net_elapsed_seconds_saved"] == 40


def test_zero_baseline_does_not_divide_or_claim_percentage(tmp_path):
    record(tmp_path, observation(elapsed_seconds=0, context_chars=0))
    record(tmp_path, observation("graph"))
    assert report(tmp_path)["assistants"]["copilot"]["median_elapsed_percent_saved"] is None


def test_measurement_sources_are_not_combined(tmp_path):
    record(tmp_path, observation())
    record(tmp_path, observation("graph", source="provider"))
    assert report(tmp_path)["assistants"]["copilot"]["pairs"] == 0


def test_concurrent_record_fails_closed_without_duplicate(tmp_path):
    (tmp_path / "metrics.lock").write_text("", encoding="utf-8")
    with pytest.raises(FileExistsError):
        record(tmp_path, observation())
    assert not (tmp_path / "metrics.jsonl").exists()


def test_report_exposes_incorrect_and_unmatched_trials_per_assistant(tmp_path):
    trials = [
        observation(benchmark="success"),
        observation("graph", benchmark="success"),
        observation(benchmark="regression"),
        observation("graph", benchmark="regression", correct=False),
        observation(benchmark="improvement", correct=False),
        observation("graph", benchmark="improvement"),
        observation(benchmark="both-failed", correct=False),
        observation("graph", benchmark="both-failed", correct=False),
        observation(benchmark="baseline-only"),
        observation("graph", benchmark="graph-only", correct=False),
        observation("maintenance", benchmark="maintenance-only", correct=False),
        observation("graph", assistant="claude", correct=False),
    ]
    for trial in trials:
        record(tmp_path, trial)
    result = report(tmp_path)["assistants"]
    copilot = result["copilot"]
    assert copilot["total_trials"] == 10
    assert copilot["trial_counts"] == {"baseline": 5, "graph": 5}
    assert copilot["complete_pairs"] == 4
    assert copilot["pairs"] == 1
    assert copilot["incorrect_trial_counts"] == {"baseline": 2, "graph": 3}
    assert copilot["unmatched_workloads"] == 2
    assert copilot["unmatched_workload_counts"] == {"baseline": 1, "graph": 1}
    assert copilot["correctness_regressions"] == 1
    assert copilot["median_elapsed_seconds_saved"] == 50
    assert result["claude"]["total_trials"] == 1
    assert result["claude"]["unmatched_workloads"] == 1
    assert result["claude"]["incorrect_trial_counts"] == {"baseline": 0, "graph": 1}
    assert result["claude"]["correctness_regressions"] == 0


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"])
@pytest.mark.parametrize("tokens", [0, 10])
def test_tokens_require_explicit_provider_provenance(tmp_path, field, tokens):
    with pytest.raises(ValueError, match="token_source"):
        record(tmp_path, observation(**{field: tokens}))
    record(tmp_path, observation(token_source="provider_reported", **{field: tokens}))


@pytest.mark.parametrize("token_source", ["manual", "provider", "estimated", "", 1])
def test_rejects_other_token_provenance_even_without_tokens(tmp_path, token_source):
    with pytest.raises(ValueError, match="token_source"):
        record(tmp_path, observation(token_source=token_source))


def test_missing_tokens_do_not_disqualify_elapsed_pair(tmp_path):
    record(tmp_path, observation(input_tokens=None, token_source=None))
    record(tmp_path, observation("graph", input_tokens=20, token_source="provider_reported"))
    result = report(tmp_path)["assistants"]["copilot"]
    assert result["pairs"] == 1
    assert result["median_elapsed_seconds_saved"] == 50
    assert result["actual_input_tokens_measured_pairs"] == 0
    assert result["median_actual_input_tokens_saved"] is None
