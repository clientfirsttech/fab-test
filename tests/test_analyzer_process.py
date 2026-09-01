"""Contract tests for the shared tool runner (Complexity and Coverage §6).

Scope
-----
`run_tool` holds the three-way failure classification every analyzer
wrapper had duplicated: timeout, executable missing, anything else. The
wording stays with each caller because those messages are part of an
analyzer's contract with its user; only the structure is shared.

The one property that matters most is that it never raises. A wrapper's
job is to produce an envelope describing what happened, and an exception
escaping here would leave no envelope at all — the single outcome a caller
cannot interpret.
"""

import subprocess
import sys

import pytest

from fab_test.scripts._analyzer_process import ProcessOutcome, run_tool

_OK = [sys.executable, "-c", "print('hello')"]


@pytest.mark.fab_test
def test_a_successful_run_reports_no_failure():
    outcome = run_tool(_OK, timeout=30, label="t", missing_message="m")

    assert outcome.failed is False
    assert outcome.status == ""
    assert outcome.proc is not None
    assert "hello" in outcome.proc.stdout


@pytest.mark.fab_test
def test_a_nonzero_exit_is_not_a_failure_here():
    """Exit codes are the wrapper's to interpret; the tool did run."""
    outcome = run_tool(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        timeout=30,
        label="t",
        missing_message="m",
    )

    assert outcome.failed is False
    assert outcome.proc.returncode == 3


@pytest.mark.fab_test
def test_a_missing_executable_uses_the_caller_s_wording():
    """The message is part of the analyzer's contract, so the caller owns it."""
    outcome = run_tool(
        ["definitely-not-a-real-binary-9f3c"],
        timeout=30,
        label="t",
        missing_message="Tabular Editor executable not found: /x. Download from https://e.com",
    )

    assert outcome.status == "error"
    assert outcome.message == (
        "Tabular Editor executable not found: /x. Download from https://e.com"
    )


@pytest.mark.fab_test
def test_a_timeout_reports_the_duration_in_minutes():
    outcome = run_tool(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=1,
        label="pql-test",
        missing_message="m",
    )

    assert outcome.status == "timeout"
    assert "pql-test timed out after 1 seconds" in outcome.message


@pytest.mark.fab_test
def test_a_caller_can_override_the_timeout_wording():
    outcome = run_tool(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=1,
        label="t",
        missing_message="m",
        timeout_message="Tabular Editor BPA timed out after 5 minutes",
    )

    assert outcome.message == "Tabular Editor BPA timed out after 5 minutes"


@pytest.mark.fab_test
def test_any_other_exception_becomes_an_error_outcome(monkeypatch):
    """Deliberately catches everything: an escaped exception leaves no envelope."""

    def _boom(*args, **kwargs):
        raise ValueError("something unforeseen")

    monkeypatch.setattr(subprocess, "run", _boom)

    outcome = run_tool(_OK, timeout=30, label="pql-test", missing_message="m")

    assert outcome.status == "error"
    assert outcome.message == "Unexpected error running pql-test: something unforeseen"


@pytest.mark.fab_test
def test_stdin_is_closed_so_a_prompting_tool_cannot_hang():
    """Inheriting stdin turns a misconfiguration into a slow failure."""
    outcome = run_tool(
        [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"],
        timeout=30,
        label="t",
        missing_message="m",
    )

    assert outcome.proc.stdout.strip() == "0"


@pytest.mark.fab_test
def test_output_outside_the_locale_encoding_does_not_crash():
    """Regression: the locale default is cp1252 on Windows.

    A tool emitting anything outside it crashed subprocess's reader thread
    with a UnicodeDecodeError raised in a background thread, which no
    caller could catch. Replacing an undecodable byte loses a character;
    not replacing it loses the run.
    """
    outcome = run_tool(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write('caf\\u00e9 \\u2014 \\u4e2d\\u6587'.encode())",
        ],
        timeout=30,
        label="t",
        missing_message="m",
    )

    assert outcome.failed is False
    assert "café" in outcome.proc.stdout


@pytest.mark.fab_test
def test_undecodable_bytes_are_replaced_rather_than_fatal():
    """Invalid UTF-8 must degrade to a replacement character, not an exception."""
    outcome = run_tool(
        [sys.executable, "-c", r"import sys; sys.stdout.buffer.write(b'ok\xff\xfebad')"],
        timeout=30,
        label="t",
        missing_message="m",
    )

    assert outcome.failed is False
    assert "ok" in outcome.proc.stdout


@pytest.mark.fab_test
def test_outcome_is_immutable():
    """It is a record of what happened; nothing downstream should edit it."""
    outcome = ProcessOutcome(None, "error", "m")

    with pytest.raises(AttributeError):
        outcome.status = "timeout"
