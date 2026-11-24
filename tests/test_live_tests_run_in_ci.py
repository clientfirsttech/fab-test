"""Every live test runs somewhere with real credentials, or it never really runs.

A live test (``tests/*_live.py``) skips without credentials, and the default CI job (build.yml) has
none, so a live test no live workflow names passes everywhere without ever touching Fabric. This
checks each one is run by a workflow in the protected ``fabric-demo`` Environment, which holds the
service principal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.fab_test

_ROOT = Path(__file__).resolve().parent.parent
_LIVE_TESTS = sorted(path.name for path in (_ROOT / "tests").glob("test_*_live.py"))


def _runs_with_credentials() -> str:
    """Every `run:` of every job in the fabric-demo Environment, as one string."""
    runs = []
    for workflow in (_ROOT / ".github" / "workflows").glob("*.yml"):
        for job in (yaml.safe_load(workflow.read_text(encoding="utf-8")).get("jobs") or {}).values():
            if job.get("environment") == "fabric-demo":
                runs += [str(step.get("run", "")) for step in job.get("steps") or []]
    return "\n".join(runs)


def test_there_are_live_tests_to_check():
    assert len(_LIVE_TESTS) >= 4, _LIVE_TESTS


@pytest.mark.parametrize("name", _LIVE_TESTS)
def test_a_live_workflow_runs_it(name):
    assert name in _runs_with_credentials(), (
        f"tests/{name} is a live test no fabric-demo workflow runs, so it only ever skips in CI. "
        "Add it to live-ci.yml's pytest step (or a path-filtered live workflow).")
