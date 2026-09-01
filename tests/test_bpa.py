"""Contract tests for the Tabular Editor BPA wrapper (vision §2.7).

Scope
-----
These tests validate that the *framework wrapper* is correct:
CLI surface, envelope schema, artifact discovery.
No external tools required. Always passes on any machine.

    pytest -m bpa        # all wrapper contract tests
    pytest -m analyzers  # all analyzer contract tests

Real execution (running BPA against your actual .fabric artifacts)
is done via ``fab-test bpa`` — a separate command that is not
pytest, just as running your code is not the same as testing it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.bpa, pytest.mark.analyzers]

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / ".fabric" / "artifacts"
BPA_WRAPPER = "tabular-editor-bpa"

SEMANTIC_MODELS = sorted(ARTIFACT_ROOT.glob("*.SemanticModel"))

CLI_ARGUMENTS = (
    "--tmdl-path",
    "--bpa-rules-path",
    "--tabular-editor-path",
    "--output-path",
    "--native-output-path",
)


def _tabular_editor_path() -> Path:
    """Resolve the Tabular Editor executable (env override -> repo default)."""
    return Path(
        os.environ.get(
            "TABULAR_EDITOR_PATH", str(REPO_ROOT / "TabularEditor" / "TabularEditor.exe")
        )
    )


def _bpa_rules_path() -> Path:
    """Resolve the BPA rules JSON (env override -> repo default)."""
    return Path(
        os.environ.get("BPA_RULES_PATH", str(REPO_ROOT / "Rules" / "BPARules.json"))
    )


# --------------------------------------------------------------------------- #
# Contract tests (@bpa)  — always pass, no external tools required.
# --------------------------------------------------------------------------- #


@pytest.mark.bpa
def test_semantic_models_discovered():
    """At least one .fabric SemanticModel must exist to analyze."""
    assert SEMANTIC_MODELS, f"No *.SemanticModel found under {ARTIFACT_ROOT}"


@pytest.mark.bpa
def test_cli_help_lists_all_arguments():
    """`--help` must document every argument the pipeline passes."""
    result = subprocess.run(
        [BPA_WRAPPER, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for argument in CLI_ARGUMENTS:
        assert argument in result.stdout, f"{argument} missing from --help output"


@pytest.mark.bpa
def test_cli_requires_mandatory_arguments():
    """Invoking with no arguments must fail on the required flags."""
    result = subprocess.run(
        [BPA_WRAPPER],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "--tmdl-path" in result.stderr


@pytest.mark.bpa
def test_envelope_names_artifact(tmp_path: Path):
    """Envelope JSON must capture the artifact path so the reporter can name the model."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from fab_test.scripts._analyzer_envelope import WrapperResult
    from fab_test.scripts.invoke_tabular_editor_bpa import write_results

    output = tmp_path / "envelope.json"
    model = tmp_path / "SalesModel.SemanticModel"
    model.mkdir()
    write_results(
        WrapperResult(output, "passed", [], model, message="OK"),
        tmp_path / "rules.json",
    )
    import json
    data = json.loads(output.read_text(encoding="utf-8"))
    # artifact_path must be set — it's what the reporter displays as the model name.
    assert "artifact_path" in data, "envelope missing artifact_path; reporter cannot name the model"
    assert "SalesModel" in data["artifact_path"], "artifact stem not reflected in artifact_path"



