"""-q/--quiet: a flag over the existing ANALYZER_VERBOSITY=summary level.

Terse CLI Output epic, "Quiet Flag" task.
"""

import argparse

import pytest

from fab_test.scripts import fab_test as fab_test_module
from fab_test.scripts.fab_test_execution import _analyzer_sub_env, _verbosity_env

pytestmark = pytest.mark.fab_test


def _parse(*argv: str) -> argparse.Namespace:
    return fab_test_module.build_parser().parse_args(list(argv))


@pytest.mark.parametrize("analyzer", ["bpa", "pbir", "a11y", "rdl", "pql-test", "playwright", "all", "local"])
def test_quiet_flag_is_accepted_by_every_running_analyzer(analyzer):
    """Given -q after any running subcommand, should parse it as quiet."""
    assert _parse(analyzer, "-q").quiet is True
    assert _parse(analyzer, "--quiet").quiet is True


def test_quiet_defaults_off():
    """Given no flag, should not be quiet."""
    assert _parse("bpa").quiet is False


def test_quiet_maps_to_the_summary_verbosity_level():
    """Given -q, should ask every analyzer subprocess for the summary level."""
    args = _parse("bpa", "-q")
    assert _verbosity_env(args) == "summary"
    assert _analyzer_sub_env(args, "text")["ANALYZER_VERBOSITY"] == "summary"


def test_quiet_reaches_subprocesses_under_json_format_too():
    """Given -q with --format json, should still request the summary level."""
    args = _parse("bpa", "-q", "--format", "json")
    assert _analyzer_sub_env(args, "json")["ANALYZER_VERBOSITY"] == "summary"


@pytest.mark.parametrize("argv", [["bpa", "-q", "-v"], ["bpa", "-v", "--quiet"], ["rdl", "-q", "-vv"], ["all", "-q", "-vv"]])
def test_quiet_with_verbose_is_rejected_with_exit_2(argv, capsys):
    """Given -q together with -v, should exit 2 naming the conflict."""
    with pytest.raises(SystemExit) as excinfo:
        _parse(*argv)
    assert excinfo.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_an_explicit_analyzer_verbosity_survives_when_no_flag_is_given(monkeypatch):
    """Given ANALYZER_VERBOSITY already set and no flag, should leave it unchanged."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
    assert _analyzer_sub_env(_parse("bpa"), "text")["ANALYZER_VERBOSITY"] == "debug"


def test_verbose_still_maps_as_before():
    """Given -v/-vv without -q, should keep mapping to verbose/debug."""
    assert _verbosity_env(_parse("bpa", "-v")) == "verbose"
    assert _verbosity_env(_parse("bpa", "-vv")) == "debug"
    assert _verbosity_env(_parse("bpa")) == ""
