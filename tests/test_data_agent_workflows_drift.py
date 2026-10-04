"""Guard the copy-pasteable data-agent workflow examples."""

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_GH = _ROOT / "docs" / "examples" / "github-actions" / "data-agent.yml"
_ADO = _ROOT / "docs" / "examples" / "azure-devops" / "data-agent.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.fab_test
@pytest.mark.parametrize("path", [_GH, _ADO], ids=["github", "azure-devops"])
def test_examples_filter_dataagent_paths_and_run_fab_test(path: Path):
    text = path.read_text(encoding="utf-8")
    assert ".DataAgent" in text
    assert "promptfooconfig.yaml" in text
    assert "fab-test data-agent" in text


@pytest.mark.fab_test
def test_github_actions_example_is_manual_and_uploads_results():
    data = _load(_GH)
    triggers = data.get("on", data.get(True)) or {}
    job = data["jobs"]["validate"]
    upload = next(step for step in job["steps"] if "upload-artifact" in step.get("uses", ""))

    assert set(triggers) == {"workflow_dispatch"}
    assert upload["if"] == "always()"
    assert ".DataAgent/**" in str(triggers)


@pytest.mark.fab_test
def test_azure_devops_example_is_manual_and_publishes_on_failure():
    data = _load(_ADO)
    publishers = [step for step in data["steps"] if step.get("task", "").startswith("Publish")]

    assert data["trigger"] == data["pr"] == "none"
    assert publishers
    assert all(step["condition"] == "always()" for step in publishers)
