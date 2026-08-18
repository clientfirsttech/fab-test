"""Shared pytest fixtures and hooks for analyzer tests (vision §2.8)."""

import json
import os
import sys
from pathlib import Path

import pytest


from fabric_ci_cd_dataops.scripts._analyzer_report import AnalyzerReporter, _resolve_verbosity

# pytest markers that belong to the analyzer contract tier.
_ANALYZER_MARKERS = {"bpa", "pbir", "pql_test", "pql_lint"}

# Artifact glob per marker — used by zero-artifact detection.
_MARKER_SUFFIX = {
    "bpa": "*.SemanticModel",
    "pbir": "*.Report",
    "pql_test": "*.SemanticModel",
    "pql_lint": "*.SemanticModel",
}


# --------------------------------------------------------------------------- #
# Reporter session fixture (R2)
# --------------------------------------------------------------------------- #

_reporter: AnalyzerReporter = AnalyzerReporter()


@pytest.fixture(scope="session")
def analyzer_reporter() -> AnalyzerReporter:
    """Session-scoped reporter shared by all analyzer integration tests."""
    return _reporter


# --------------------------------------------------------------------------- #
# Marker auto-tagging (existing behaviour preserved)
# --------------------------------------------------------------------------- #


def pytest_collection_modifyitems(config, items):
    """Auto-tag analyzer tests with the aggregate ``analyzers`` marker."""
    for item in items:
        if _ANALYZER_MARKERS & {mark.name for mark in item.iter_markers()}:
            item.add_marker(pytest.mark.analyzers)


# --------------------------------------------------------------------------- #
# Zero-artifact session failure (R1.1)
# --------------------------------------------------------------------------- #


def pytest_sessionfinish(session, exitstatus):
    """Print the reporter summary; fail the session if a marker found nothing."""
    markexpr: str = getattr(session.config.option, "markexpr", "") or ""

    # Print the summary table when any analyzer marker was requested.
    requested = {m for m in _ANALYZER_MARKERS if m in markexpr} | (
        _ANALYZER_MARKERS if "analyzers" in markexpr else set()
    )
    if requested and _reporter._results:
        verbose_count = getattr(session.config.option, "verbose", 0) or 0
        verbosity = _resolve_verbosity(verbose_count)
        print("\n")
        _reporter.print_summary(verbosity=verbosity)

    # Fail loudly when a specific marker was targeted but no artifacts exist.
    if not markexpr:
        return
    artifact_root = Path(__file__).resolve().parents[1] / ".fabric" / "artifacts"
    for marker in _ANALYZER_MARKERS:
        if marker not in markexpr:
            continue
        suffix = _MARKER_SUFFIX.get(marker, "*")
        artifacts = list(artifact_root.glob(suffix))
        if not artifacts:
            message = (
                f"\n⚠️  [analyzers] No artifacts matched '{suffix}' under {artifact_root}.\n"
                f"   Run: pytest -m {marker}  requires at least one {suffix} artifact.\n"
                f"   Add a sample artifact or set ANALYZER_ARTIFACTS to an explicit list."
            )
            print(message, file=sys.stderr)
            # Force a non-zero exit status. pytest_sessionfinish can mutate
            # session.exitstatus in supported versions; otherwise set a marker
            # attribute so a custom exit hook can fail the run.
            session.exitstatus = 1
            session.analyzer_feedback_zero_artifact_failure = marker


# --------------------------------------------------------------------------- #
# ANALYZER_ARTIFACTS include-list helper (R1.2)
# --------------------------------------------------------------------------- #


def filter_artifacts(artifacts: list, glob_suffix: str) -> list:
    """Filter artifact list to those named in ANALYZER_ARTIFACTS env var.

    If the env var is not set all artifacts are returned unchanged.
    Unknown stems that appear in the env var cause a clear error.
    """
    include_raw: str | None = os.environ.get("ANALYZER_ARTIFACTS")
    if not include_raw:
        return artifacts

    requested_stems = {s.strip() for s in include_raw.split(",") if s.strip()}
    available = {p.stem: p for p in artifacts}
    unknown = requested_stems - available.keys()
    if unknown:
        raise ValueError(
            f"ANALYZER_ARTIFACTS lists unknown artifact stems: {sorted(unknown)}.\n"
            f"Available stems: {sorted(available.keys())}"
        )
    return [available[s] for s in sorted(requested_stems) if s in available]


# --------------------------------------------------------------------------- #
# pytest_sessionfinish cannot always mutate exitstatus early enough, so we
# use a final terminal hook registered by _register_terminal_hook below.
# --------------------------------------------------------------------------- #

def _analyzer_feedback_terminal_hook(terminalreporter, exitstatus, config):
    """Terminal hook that promotes a recorded zero-artifact failure to exit 1."""
    session = getattr(terminalreporter, "_session", None)
    if session and getattr(session, "analyzer_feedback_zero_artifact_failure", None):
        return 1
    return exitstatus


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    """Register terminal summary hook for zero-artifact enforcement."""
    config.pluginmanager.register(AnalyzerFeedbackTerminalPlugin(), name="analyzer_feedback_terminal")


class AnalyzerFeedbackTerminalPlugin:
    """Plugin that enforces non-zero exit when a marker resolves zero artifacts."""

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        return _analyzer_feedback_terminal_hook(terminalreporter, exitstatus, config)


@pytest.fixture
def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_analyzers_metadata(tmp_path: Path) -> Path:
    """Create a sample analyzers.json metadata file for testing."""
    metadata = {
        "analyzer_registry": {
            "fake_analyzer": {
                "type": "static",
                "command": "python",
                "args": ["-c", "print('{artifact_name} {artifact_path}')"],
                "description": "A fake analyzer for unit tests",
                "exit_code_success": 0,
            },
            "failing_analyzer": {
                "type": "static",
                "command": "python",
                "args": ["-c", "import sys; sys.exit(1)"],
                "description": "An analyzer that always fails",
                "exit_code_success": 0,
            },
            "missing_analyzer": {
                "type": "static",
                "command": "definitely_not_a_real_command_12345",
                "args": [],
                "description": "Analyzer with a missing command",
                "exit_code_success": 0,
            },
        },
        "artifact_analyzers": {
            "SemanticModel": {"static": ["fake_analyzer"], "dynamic": []},
        },
    }
    metadata_path = tmp_path / "analyzers.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path
