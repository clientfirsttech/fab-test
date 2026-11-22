"""The Data Agent docs keep up with the parser (vision: an epic isn't done until all three callers are documented).

The walkthrough's flag table names every flag of the run and both verbs, so a new flag fails here rather
than going undocumented. Each pipeline example pins the current release and lints before it asks.
"""

import argparse
import re
from pathlib import Path

import pytest

from fab_test import __version__
from fab_test.scripts.fab_test_parser import build_parser

pytestmark = [pytest.mark.data_agent, pytest.mark.fab_test]

_ROOT = Path(__file__).resolve().parent.parent
_WALKTHROUGH = _ROOT / "docs" / "DATA-AGENT-TESTS-WALKTHROUGH.md"
_PIPELINES = [_ROOT / "docs" / "examples" / "github-actions" / "data-agent-tests.yml",
              _ROOT / "docs" / "examples" / "azure-devops" / "data-agent-tests.yml"]
_UNLISTED = {"-h", "--help", "--workspace-id", "--from-workspace", "--no-report", "--no-telemetry", "--verbose",
             "--quiet"}  # aliases and negations of a listed flag


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


def _flags() -> set[str]:
    run = _subparsers(build_parser())["data-agent"]
    verbs = _subparsers(_subparsers(run)["tests"]).values()
    return {flag for parser in (run, *verbs) for flag in parser._option_string_actions} - _UNLISTED


def test_the_walkthrough_flag_table_names_every_flag():
    table = _WALKTHROUGH.read_text(encoding="utf-8").split("## Flags: init, lint and the run", 1)[1]
    table = table.split("\n## ", 1)[0]
    missing = sorted(flag for flag in _flags() if not re.search(rf"`{re.escape(flag)}[` \\]", table))
    assert missing == [], f"add a row or a mention to the walkthrough's flag table: {missing}"


@pytest.mark.parametrize("pipeline", _PIPELINES, ids=lambda path: path.parent.name)
def test_each_pipeline_pins_this_release_and_lints_before_it_asks(pipeline):
    text = pipeline.read_text(encoding="utf-8")
    assert f'cft-fab-test=={__version__}"' in text
    assert text.index("fab-test data-agent tests lint") < text.index("fab-test data-agent --format json")
    assert "*.DataAgent.promptfoo.yaml" in text and "*.DataAgent/**" in text
    assert "cron:" in text  # answers drift with the data, not only with commits
    assert "pull_request_target" not in text.replace("never switch this to `pull_request_target`", "")
