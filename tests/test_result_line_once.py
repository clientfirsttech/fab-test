"""A wrapper's result line prints once outside CI (Standalone bug).

Each wrapper ends with its result as a CI annotation on stderr, e.g.
`::warning::PBIR Inspector found 11 finding(s) (errors: 11, warnings: 0, exit code 0)`.
Outside CI the parent replayed it -- after the wrapper's own `📊 11 finding(s)`
line and before the summary row that says it a third time. The replayed text
is exactly the envelope's `message` for bpa, pbir, a11y and rdl (checked
live), so the parent skips that one line; CI still gets stderr verbatim.
"""

import subprocess
from types import SimpleNamespace

import pytest

from fab_test.scripts import fab_test_execution

MESSAGE = "PBIR Inspector found 11 finding(s) (errors: 11, warnings: 0, exit code 0)"
STDERR = f"::warning::{MESSAGE}\n::error::PBIR Inspector stderr detail\n"


def _proc():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=STDERR)


def test_given_a_local_run_should_skip_the_replayed_result_line(capsys):
    ctx = SimpleNamespace(in_ci=False, seen_stderr=set())
    fab_test_execution._emit_process_output(_proc(), False, ctx, "text", said=MESSAGE)
    printed = capsys.readouterr()
    text = printed.out + printed.err
    assert MESSAGE not in text
    assert "PBIR Inspector stderr detail" in text  # anything else the analyzer said still shows


def test_given_ci_should_keep_stderr_verbatim_for_annotations(capsys):
    ctx = SimpleNamespace(in_ci=True, seen_stderr=set())
    fab_test_execution._emit_process_output(_proc(), False, ctx, "text", said=MESSAGE)
    assert capsys.readouterr().err == STDERR


@pytest.mark.parametrize("said", ["", "some other message"])
def test_given_no_matching_message_should_replay_the_line(capsys, said):
    ctx = SimpleNamespace(in_ci=False, seen_stderr=set())
    fab_test_execution._emit_process_output(_proc(), False, ctx, "text", said=said)
    printed = capsys.readouterr()
    assert MESSAGE in printed.out + printed.err
