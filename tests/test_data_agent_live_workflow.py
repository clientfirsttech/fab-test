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
         ".github/scripts/check_data_agent_ran.py"]


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



# --- The live run tests the tester -----------------------------------------------------------------
# A Data Agent answers agentically: the same question can pass one run and fail the next, so CI never
# judges which answers were right (the report shows that). It fails only when the tester itself did
# not work: the run broke, or a question came back without a verdict. Exit 1 alone cannot tell, since
# findings, a timeout and a promptfoo crash all exit 1, so a checker reads the envelope instead.

_CHECKER = _ROOT / ".github" / "scripts" / "check_data_agent_ran.py"


def _checker():
    import importlib.util

    spec = importlib.util.spec_from_file_location(_CHECKER.stem, _CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _envelope(passed=("Count characters",), failed=("Tell me a joke",), status=None, message=""):
    results = [{"test_name": name, "passed": True} for name in passed]
    results += [{"test_name": name, "passed": False} for name in failed]
    return {"status": status or ("failed" if failed else "passed"), "message": message,
            "test_results": results}


@pytest.mark.parametrize("failed", [(), ("Tell me a joke",)], ids=["all-pass", "some-fail"])
def test_any_mix_of_verdicts_passes(failed):
    assert _checker().problems(_envelope(failed=failed), asked=1 + len(failed)) == []


def test_a_run_that_broke_fails_even_though_it_exited_1():
    envelope = {"status": "error", "message": "promptfoo eval exited 3: boom"}
    problems = _checker().problems(envelope, asked=2)
    assert len(problems) == 1 and "promptfoo eval exited 3: boom" in problems[0]


def test_a_skipped_run_fails():
    assert _checker().problems(_envelope(status="skipped"), asked=2)


def test_a_question_without_a_verdict_fails():
    assert _checker().problems(_envelope(), asked=3) == ["2 of 3 questions came back with a verdict."]


def test_a_run_with_no_results_fails():
    assert _checker().problems({"status": "passed", "message": ""}, asked=2)


def _write_run(root, item, envelope, tests):
    import json

    (root / item).mkdir()
    (root / item / "envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    (root / item / "effective.promptfoo.yaml").write_text(
        yaml.safe_dump({"tests": [{"description": f"t{i}"} for i in range(tests)]}), encoding="utf-8")


def test_main_fails_without_an_envelope(tmp_path, capsys):
    assert _checker().main(tmp_path) == 1
    assert "No Data Agent envelope" in capsys.readouterr().out


def test_main_reads_every_envelope(tmp_path, capsys):
    _write_run(tmp_path, "good", _envelope(), tests=2)
    _write_run(tmp_path, "bad", {"status": "error", "message": "x"}, tests=2)
    assert _checker().main(tmp_path) == 1
    out = capsys.readouterr().out
    assert "bad" in out and "good: all 2 questions answered (1 passed, 1 failed)" in out


def test_main_passes_when_every_run_answered(tmp_path):
    _write_run(tmp_path, "good", _envelope(), tests=2)
    assert _checker().main(tmp_path) == 0


def _live_steps() -> list[dict]:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["live"]["steps"]


def test_the_workflow_tolerates_findings_but_not_a_usage_or_credential_exit():
    ask = next(step for step in _live_steps() if "fab-test data-agent --workspace" in step.get("run", ""))
    assert "set +e" in ask["run"] and '[ "$code" -le 1 ]' in ask["run"]


def test_the_workflow_checks_the_run_completed():
    steps = _live_steps()
    ask = next(i for i, step in enumerate(steps) if "fab-test data-agent --workspace" in step.get("run", ""))
    check = next(i for i, step in enumerate(steps) if _CHECKER.name in step.get("run", ""))
    assert check == ask + 1
