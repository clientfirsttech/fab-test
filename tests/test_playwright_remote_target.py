"""Contract tests for playwright's local-discovery-miss fallback.

Scope
-----
`fab-test playwright --artifact NAME --env ENV` used to silently require a
local `NAME.Report` folder under `--artifact-dir` to exist -- the folder was
never read for playwright (it validates the *deployed* report, never local
file content), but discovery still needed one to find before dispatching a
subprocess. That made a purely-remote report -- any paginated (RDL) report,
since this project's `.fabric/artifacts/` tree only ever holds PBIR-format
interactive reports -- undiscoverable through the real CLI, previously
working only by coincidence when a same-named local folder happened to exist
(Paginated Report Testing epic, live-verification fix).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_execution import (
    _discover_for,
    _playwright_remote_target,
)


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "artifact": None,
        "target": None,
        "environment": "",
        "artifact_dir": ".",
        "output_dir": "fab-test-results",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_remote_target_none_when_nothing_named() -> None:
    """No --artifact/target at all: batch discovery, not a remote fallback."""
    assert _playwright_remote_target(_args(environment="dev")) is None


def test_remote_target_none_without_an_environment() -> None:
    """A named artifact with no --env has nothing to resolve it against."""
    assert _playwright_remote_target(_args(artifact="Invoice RDL")) is None


def test_remote_target_none_for_an_explicit_filesystem_path() -> None:
    """A real path (./src/Sales.Report) that finds nothing locally is a real
    miss, not a signal to resolve remotely."""
    args = _args(artifact="./src/Sales.Report", environment="dev")
    assert _playwright_remote_target(args) is None


def test_remote_target_named_for_a_bare_artifact_name() -> None:
    """A bare --artifact NAME with --env set resolves to a synthetic target
    keyed by that name, so build_playwright_command's artifact.stem still
    carries the real name through to the subprocess."""
    args = _args(artifact="Invoice RDL", environment="dev")
    target = _playwright_remote_target(args)
    assert target == Path("Invoice RDL")


def test_remote_target_named_for_a_workspace_scoped_target() -> None:
    """WORKSPACE.Workspace/NAME.Type also resolves remotely with no local match."""
    args = _args(target="Sales Dev.Workspace/Invoice RDL.PaginatedReport", environment="dev")
    target = _playwright_remote_target(args)
    assert target == Path("Invoice RDL")


def test_discover_for_falls_back_to_remote_target_when_local_discovery_is_empty(
    tmp_path,
) -> None:
    """playwright discovery falls back to the remote target only when local
    discovery under --artifact-dir truly finds nothing."""
    args = _args(artifact="Invoice RDL", environment="dev", artifact_dir=str(tmp_path))
    artifacts = _discover_for("playwright", args, "*.Report")
    assert artifacts == [Path("Invoice RDL")]


def test_discover_for_prefers_a_real_local_match_over_the_remote_fallback(
    tmp_path,
) -> None:
    """A real local folder is used as-is; the remote fallback never overrides it."""
    (tmp_path / "Invoice RDL.Report").mkdir()
    args = _args(artifact="Invoice RDL", environment="dev", artifact_dir=str(tmp_path))
    artifacts = _discover_for("playwright", args, "*.Report")
    assert artifacts == [tmp_path / "Invoice RDL.Report"]


def test_discover_for_does_not_apply_the_fallback_to_other_analyzers(tmp_path) -> None:
    """bpa reads local file content, so an empty local discovery must stay
    empty rather than dispatching against a folder that was never found."""
    args = _args(artifact="Sales", environment="dev", artifact_dir=str(tmp_path))
    artifacts = _discover_for("bpa", args, "*.SemanticModel")
    assert artifacts == []


@pytest.mark.parametrize("environment", ["", None])
def test_discover_for_stays_empty_with_no_environment(tmp_path, environment) -> None:
    """No --env at all: nothing to resolve a bare name against remotely."""
    args = _args(artifact="Invoice RDL", environment=environment, artifact_dir=str(tmp_path))
    artifacts = _discover_for("playwright", args, "*.Report")
    assert artifacts == []
