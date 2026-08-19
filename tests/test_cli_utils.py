"""Contract tests for the fab-test output channel helper (CLI Agent Ergonomics §1).

Scope
-----
`narrate()` decides where a human-facing narration line goes: stdout for
--format text (today's behavior), stderr for --format json (so stdout stays
reserved for the machine-readable payload), and nowhere at all when --quiet.
"""

import pytest

from fabric_ci_cd_dataops.scripts._cli_utils import narrate


@pytest.mark.fab_test
def test_narrate_json_format_writes_to_stderr(capsys):
    """--format json: narrate() writes to stderr, leaving stdout untouched."""
    narrate("hello", output_format="json")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "hello\n"


@pytest.mark.fab_test
def test_narrate_text_format_writes_to_stdout(capsys):
    """--format text: narrate() writes to stdout exactly as print() does today."""
    narrate("hello", output_format="text")
    captured = capsys.readouterr()
    assert captured.out == "hello\n"
    assert captured.err == ""


@pytest.mark.fab_test
def test_narrate_default_format_is_text(capsys):
    """Omitting output_format behaves like text mode."""
    narrate("hello")
    captured = capsys.readouterr()
    assert captured.out == "hello\n"
    assert captured.err == ""


@pytest.mark.fab_test
def test_narrate_quiet_suppresses_output_in_text_mode(capsys):
    """--quiet suppresses the line in text mode; neither stream gets it."""
    narrate("hello", output_format="text", quiet=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.fab_test
def test_narrate_quiet_suppresses_output_in_json_mode(capsys):
    """--quiet suppresses the line in json mode too."""
    narrate("hello", output_format="json", quiet=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
