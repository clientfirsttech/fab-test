"""Contract tests for terminal colour.

Scope
-----
Colour marks what needs attention: status, and error/warning counts when
they are non-zero. Zero counts stay plain so the eye lands only on work.

Three things must hold no matter what. Colour never reaches `--format
json`, whose stdout is contractually a single JSON document. It is off
when stdout is not a terminal, so redirected output and CI logs stay
clean. And `NO_COLOR` always wins, per no-color.org.

Always passes on any machine — every check drives the helpers directly or
forces the decision through an environment variable.
"""

import json
import os
import re
import subprocess
import sys

import pytest

from fab_test.scripts.fab_test_summary import (
    _paint,
    _print_all_summary,
    color_enabled,
)

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible(text: str) -> str:
    return _ANSI_RE.sub("", text)


class _FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _run_cli(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        check=False,
    )


# --------------------------------------------------------------------------- #
# When colour is on
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_colour_is_on_for_a_terminal(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    assert color_enabled(_FakeStream(tty=True)) is True


@pytest.mark.fab_test
def test_colour_is_off_when_redirected(monkeypatch):
    """A file or a pipe should receive plain text."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    assert color_enabled(_FakeStream(tty=False)) is False


@pytest.mark.fab_test
@pytest.mark.parametrize("value", ["1", "", "anything"])
def test_no_color_always_wins(monkeypatch, value):
    """no-color.org: any value, even empty, disables colour."""
    monkeypatch.setenv("NO_COLOR", value)
    monkeypatch.setenv("FORCE_COLOR", "1")

    assert color_enabled(_FakeStream(tty=True)) is False


@pytest.mark.fab_test
def test_force_color_enables_it_off_a_terminal(monkeypatch):
    """So a CI job that renders ANSI can opt back in."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")

    assert color_enabled(_FakeStream(tty=False)) is True


# --------------------------------------------------------------------------- #
# Painting
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_paint_is_a_no_op_when_disabled():
    assert _paint("FAILED", "red", enabled=False) == "FAILED"


@pytest.mark.fab_test
def test_paint_wraps_and_always_resets():
    """An unreset colour would bleed into everything printed afterwards."""
    painted = _paint("FAILED", "red", enabled=True)

    assert painted.startswith("\033[")
    assert painted.endswith("\033[0m")
    assert _visible(painted) == "FAILED"


@pytest.mark.fab_test
def test_paint_leaves_the_visible_text_unchanged():
    """Column alignment depends on the visible width not moving."""
    for colour in ("red", "yellow", "green"):
        assert _visible(_paint("warning", colour, enabled=True)) == "warning"


# --------------------------------------------------------------------------- #
# In the summary
# --------------------------------------------------------------------------- #


def _summary_args(artifact_dir, output_dir, output_format="text"):
    import argparse

    return argparse.Namespace(
        artifact_dir=str(artifact_dir),
        output_dir=str(output_dir),
        dry_run=False,
        output_format=output_format,
        artifact=None,
        target=None,
        resolved_target=None,
    )


def _envelope_with(output_dir, analyzer, stem, findings):
    from fab_test.scripts._analyzer_envelope import EnvelopeIdentity, build_envelope

    path = output_dir / analyzer / stem
    path.mkdir(parents=True, exist_ok=True)
    (path / "envelope.json").write_text(
        json.dumps(
            build_envelope(EnvelopeIdentity(analyzer, stem), status="passed", findings=findings)
        ),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_table_alignment_survives_colouring(tmp_path, capsys, monkeypatch):
    """tabulate is ANSI-aware, but that must be proven, not assumed."""
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.Report").mkdir(parents=True)
    output_dir = tmp_path / "results"
    _envelope_with(
        output_dir, "pbir", "Sales", [{"rule": "R", "severity": "error", "object": "o"}]
    )

    _print_all_summary(
        output_dir, ("pbir",), [0], _summary_args(artifact_dir, output_dir)
    )

    out = capsys.readouterr().out
    borders = [ln for ln in out.splitlines() if "│" in ln or "╭" in ln or "╰" in ln]
    widths = {len(_visible(ln)) for ln in borders}
    assert len(widths) == 1, f"rows have differing visible widths: {widths}"


@pytest.mark.fab_test
def test_json_output_is_never_coloured(tmp_path):
    """stdout under --format json is contractually one JSON document."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)

    result = _run_cli(
        "all",
        "--artifact-dir",
        str(artifact_dir),
        "--dry-run",
        "--format",
        "json",
        env={"FORCE_COLOR": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert "\033[" not in result.stdout
    json.loads(result.stdout)


@pytest.mark.fab_test
def test_text_output_is_plain_when_not_a_terminal(tmp_path):
    """A captured subprocess is not a tty, so nothing should be painted."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)

    result = _run_cli(
        "all", "--artifact-dir", str(artifact_dir), "--dry-run",
        env={"NO_COLOR": "1"},
    )

    assert "\033[" not in result.stdout
