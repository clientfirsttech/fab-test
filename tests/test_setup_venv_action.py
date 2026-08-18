"""Contract tests for the setup-venv GitHub Actions composite action."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "setup-venv" / "action.yml"


@pytest.mark.fab_test
def test_setup_venv_adds_venv_bin_to_github_path():
    """The composite action must export the venv bin directory to $GITHUB_PATH.

    Console scripts installed by the local package (e.g. `fab-test`) live in
    the virtual environment's `bin/` (Linux/macOS) or `Scripts/` (Windows)
    directory. GitHub Actions composite steps run in isolated shells, so
    activating the venv inside the composite step does not persist to
    downstream steps. Exporting the directory to $GITHUB_PATH makes the
    console scripts available without requiring callers to know the venv
    layout or activate it explicitly.
    """
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    runs = action.get("runs", {})
    assert runs.get("using") == "composite", "setup-venv must be a composite action"

    steps = runs.get("steps", [])
    assert steps, "setup-venv must define at least one step"

    found = False
    for step in steps:
        run_script = step.get("run", "")
        if isinstance(run_script, str) and (
            "$VENV_BIN" in run_script and "$GITHUB_PATH" in run_script
        ):
            found = True
            break

    assert found, (
        "setup-venv action must append $VENV_BIN to $GITHUB_PATH so that "
        "console scripts installed in the virtual environment (e.g. fab-test) "
        "are available on PATH in downstream workflow steps"
    )
