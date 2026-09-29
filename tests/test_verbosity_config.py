"""`verbosity:` in fab-test.yml: the -q/-v ladder, pinnable per repository.

Terse CLI Output epic, "Verbosity Config Key" task. Precedence is the same
as every other setting: flag > ANALYZER_VERBOSITY > fab-test.yml > default.
"""

import argparse
import json

import pytest

from fab_test.scripts import fab_test as fab_test_module
from fab_test.scripts._config import ConfigError, apply_verbosity_default, validate_config
from fab_test.scripts.fab_test_admin import _config_show
from fab_test.scripts.fab_test_execution import _verbosity_env

pytestmark = pytest.mark.fab_test


@pytest.fixture(autouse=True)
def _no_ambient_verbosity(monkeypatch):
    monkeypatch.delenv("ANALYZER_VERBOSITY", raising=False)


def _args(*argv: str) -> argparse.Namespace:
    return fab_test_module.build_parser().parse_args(["bpa", *argv])


def _resolved(config: dict, *argv: str) -> argparse.Namespace:
    args = _args(*argv)
    apply_verbosity_default(args, config)
    return args


@pytest.mark.parametrize("level", ["summary", "default", "verbose", "debug"])
def test_each_ladder_level_is_a_valid_config_value(level):
    """Given a level on the verbosity ladder, should accept it."""
    validate_config({"verbosity": level})


def test_unknown_level_is_rejected_naming_the_allowed_values():
    """Given a level off the ladder, should say which levels exist."""
    with pytest.raises(ConfigError) as excinfo:
        validate_config({"verbosity": "loud"})
    message = str(excinfo.value)
    assert "verbosity" in message and "'loud'" in message
    for level in ("summary", "default", "verbose", "debug"):
        assert level in message


def test_level_of_the_wrong_type_is_rejected():
    """Given a non-string verbosity, should fail the type check."""
    with pytest.raises(ConfigError, match="verbosity"):
        validate_config({"verbosity": 3})


def test_file_summary_behaves_as_quiet():
    """Given verbosity: summary and no flag, should act as -q."""
    args = _resolved({"verbosity": "summary"})
    assert args.quiet is True
    assert _verbosity_env(args) == "summary"


@pytest.mark.parametrize(("level", "expected"), [("verbose", "verbose"), ("debug", "debug")])
def test_file_verbose_levels_behave_as_repeated_v(level, expected):
    """Given verbosity: verbose/debug and no flag, should act as -v/-vv."""
    args = _resolved({"verbosity": level})
    assert args.quiet is False
    assert _verbosity_env(args) == expected


def test_file_default_changes_nothing():
    """Given verbosity: default, should leave the run as it is with no setting."""
    args = _resolved({"verbosity": "default"})
    assert (args.quiet, args.verbose) == (False, 0)
    assert _verbosity_env(args) == ""


def test_environment_beats_the_file(monkeypatch):
    """Given ANALYZER_VERBOSITY and a file value, should follow the environment."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "verbose")
    args = _resolved({"verbosity": "summary"})
    assert args.quiet is False
    assert _verbosity_env(args) == "verbose"


def test_environment_summary_makes_the_parent_quiet_too(monkeypatch):
    """Given ANALYZER_VERBOSITY=summary, should quiet the parent's narration, not only the children."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
    assert _resolved({}).quiet is True


def test_an_unrecognised_environment_value_falls_through_to_the_file(monkeypatch):
    """Given a garbled ANALYZER_VERBOSITY, should ignore it and use the file."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "loud")
    assert _resolved({"verbosity": "summary"}).quiet is True


def test_environment_value_is_case_insensitive(monkeypatch):
    """Given ANALYZER_VERBOSITY=SUMMARY, should treat it as summary, as the wrappers do."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "SUMMARY")
    assert _resolved({}).quiet is True


@pytest.mark.parametrize(
    ("argv", "quiet", "verbose"),
    [(["-v"], False, 1), (["-vv"], False, 2)],
)
def test_verbose_flag_beats_a_file_that_says_summary(argv, quiet, verbose):
    """Given -v and verbosity: summary, should follow the flag."""
    args = _resolved({"verbosity": "summary"}, *argv)
    assert (args.quiet, args.verbose) == (quiet, verbose)


def test_quiet_flag_beats_an_environment_that_says_debug(monkeypatch):
    """Given -q and ANALYZER_VERBOSITY=debug, should follow the flag."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
    args = _resolved({}, "-q")
    assert (args.quiet, args.verbose) == (True, 0)


def test_no_setting_anywhere_leaves_the_default():
    """Given nothing set anywhere, should change nothing."""
    args = _resolved({})
    assert (args.quiet, args.verbose) == (False, 0)


def test_subcommands_without_the_flags_are_left_alone():
    """Given a subcommand that has no -q/-v (doctor), should not add attributes."""
    args = fab_test_module.build_parser().parse_args(["doctor"])
    apply_verbosity_default(args, {"verbosity": "summary"})
    assert not hasattr(args, "quiet")


def _show(capsys, file_config: dict) -> dict:
    args = argparse.Namespace(validate=False, output_format="json", file_config=file_config)
    _config_show(args)
    rows = json.loads(capsys.readouterr().out)["settings"]
    return next(row for row in rows if row["key"] == "verbosity")


def test_config_show_reports_the_file_origin(capsys):
    """Given verbosity in the file, should show its value and that it came from the file."""
    row = _show(capsys, {"verbosity": "summary"})
    assert (row["value"], row["origin"]) == ("summary", "fab-test.yml:verbosity")


def test_config_show_reports_the_environment_origin(capsys, monkeypatch):
    """Given ANALYZER_VERBOSITY set, should show that it won over the file."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
    row = _show(capsys, {"verbosity": "summary"})
    assert (row["value"], row["origin"]) == ("debug", "env:ANALYZER_VERBOSITY")


def test_config_show_reports_the_default_when_nothing_is_set(capsys):
    """Given no setting, should show the default and say so."""
    row = _show(capsys, {})
    assert (row["value"], row["origin"]) == ("default", "default")


def test_prepare_step_applies_the_file_value_before_dispatch():
    """Given verbosity: summary in the loaded config, should reach the run as -q."""
    args = _args()
    args.file_config = {"verbosity": "summary"}
    assert fab_test_module._prepare_verbosity(args) is None
    assert args.quiet is True


def test_init_scaffold_documents_the_key_and_every_level():
    """Given `fab-test init`, should show the key and the levels it accepts, commented out."""
    from fab_test.scripts._config import VERBOSITY_LEVELS
    from fab_test.scripts.fab_test_admin import _FAB_TEST_YML_TEMPLATE

    line = next(row for row in _FAB_TEST_YML_TEMPLATE.splitlines() if "verbosity:" in row)
    assert line.startswith("# verbosity:")
    assert all(level in line for level in VERBOSITY_LEVELS)
