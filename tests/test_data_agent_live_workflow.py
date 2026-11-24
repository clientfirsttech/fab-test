"""The live Data Agent workflow runs only when what `fab-test data-agent` depends on changes.

Asking the real agent needs a paid, running Fabric capacity, so `.github/workflows/data-agent-live.yml`
is path-filtered rather than run on every change. A filter written by hand drifts as imports change, so
this computes the run path's import closure and checks the filter covers every file in it.
"""

from __future__ import annotations

import ast
from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.data_agent

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _ROOT / ".github" / "workflows" / "data-agent-live.yml"
_SRC = _ROOT / "src"
# What `fab-test data-agent` runs; `tests init`/`tests lint` are offline and covered by the unit suite.
_RUN_PATH = {"invoke_data_agent", "fabric_data_agent_provider", "_data_agent_run", "_data_agent_resolution",
             "_data_agent_suite", "_data_agent_progress"}
# Not Python, but the run depends on them: the promptfoo pin, the package's dependencies, the suites.
_ALSO = ["src/fab_test/metadata/analyzers.json", "pyproject.toml",
         "fab-tests/data-agent/agent-sample-model.DataAgent.promptfoo.yaml", ".github/workflows/data-agent-live.yml",
         "tests/test_data_agent_live.py",
         "tests/test_playwright_generation_parity_live.py"]


def _module(path: Path) -> str:
    return ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")


def _imports(path: Path, modules: dict[str, Path]) -> set[str]:
    name = _module(path)
    package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*parts, *([base] if base else [])])
            found |= {base, *(f"{base}.{alias.name}" for alias in node.names)}
    return {module for module in found if module in modules}


def _run_path_closure() -> set[str]:
    modules = {_module(path): path for path in _SRC.rglob("*.py")}
    todo = [name for name in modules if name.rsplit(".", 1)[-1] in _RUN_PATH]
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(_imports(modules[name], modules))
    return {modules[name].relative_to(_ROOT).as_posix() for name in seen}


def _triggers() -> dict:
    document = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return document.get("on", document.get(True))  # YAML 1.1 reads a bare `on:` as True


def test_the_closure_reaches_the_service_code():
    """A guard on the guard: an import-walk bug would pass every file trivially."""
    closure = _run_path_closure()
    assert "src/fab_test/scripts/_http_policy.py" in closure
    assert "src/fab_test/scripts/_credentials.py" in closure
    assert "src/fab_test/scripts/playwright_validation/fabric_service_client.py" in closure


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_the_path_filter_covers_everything_the_run_depends_on(event):
    patterns = _triggers()[event]["paths"]
    missed = sorted(path for path in [*_run_path_closure(), *_ALSO]
                    if not any(fnmatch(path, pattern) for pattern in patterns))
    assert missed == [], f"{event}.paths misses files `fab-test data-agent` depends on: {missed}"


def test_it_runs_only_on_change_or_by_hand():
    triggers = _triggers()
    # No schedule (capacity costs) and never pull_request_target (a suite is code).
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}




def test_the_workflow_runs_the_live_integration_test():
    steps = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["live"]["steps"]
    runs = " ".join(str(step.get("run", "")) for step in steps)
    assert "pytest tests/test_data_agent_live.py" in runs
    assert "DATA_AGENT_WORKSPACE" in yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["live"]["env"]
