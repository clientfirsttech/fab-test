"""Contract tests for report generation and the --report flag (§4-5).

Scope
-----
Generation is **opt-in**: nothing is rendered unless `--report` is passed,
so no existing run gets slower and no pipeline collects artifacts it did
not ask for.

PBIR is deliberately untouched by any of this: its `TestRun.html` comes
from the upstream tool, so the slot is already filled and the generated
report must never overwrite it.

Always passes on any machine — no analyzer binary is invoked.
"""

import json
import os
import subprocess
import sys

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_envelope import build_envelope
from fabric_ci_cd_dataops.scripts._report_html import attach_report, report_enabled

_FINDING = {"rule": "R1", "severity": "warning", "object": "o", "message": "m"}


def _envelope(**overrides):
    base = {
        "analyzer": "bpa",
        "artifact_path": "Sales.SemanticModel",
        "status": "passed",
        "findings": [_FINDING],
    }
    base.update(overrides)
    return build_envelope(**base)


def _run_cli(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        check=False,
    )


# --------------------------------------------------------------------------- #
# The toggle
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_reports_are_off_by_default(monkeypatch):
    """Opt-in: an unflagged run must behave exactly as it does today."""
    monkeypatch.delenv("ANALYZER_REPORT", raising=False)

    assert report_enabled() is False


@pytest.mark.fab_test
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_the_env_var_turns_generation_on(monkeypatch, value):
    monkeypatch.setenv("ANALYZER_REPORT", value)

    assert report_enabled() is True


@pytest.mark.fab_test
@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_falsey_values_leave_generation_off(monkeypatch, value):
    monkeypatch.setenv("ANALYZER_REPORT", value)

    assert report_enabled() is False


# --------------------------------------------------------------------------- #
# attach_report
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_nothing_is_written_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("ANALYZER_REPORT", raising=False)
    envelope = _envelope()

    attach_report(envelope, tmp_path / "envelope.json")

    assert "native_html_output_path" not in envelope
    assert list(tmp_path.iterdir()) == []


@pytest.mark.fab_test
def test_a_report_is_written_beside_the_envelope_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYZER_REPORT", "1")
    envelope = _envelope()

    attach_report(envelope, tmp_path / "envelope.json")

    report = tmp_path / "report.html"
    assert report.exists()
    assert envelope["native_html_output_path"] == str(report)
    assert "R1" in report.read_text(encoding="utf-8")


@pytest.mark.fab_test
def test_an_upstream_report_is_never_overwritten(tmp_path, monkeypatch):
    """PBIR already filled this slot; the generated report must defer to it."""
    monkeypatch.setenv("ANALYZER_REPORT", "1")
    envelope = _envelope(native_html_output_path_str="upstream/TestRun.html")

    attach_report(envelope, tmp_path / "envelope.json")

    assert envelope["native_html_output_path"] == "upstream/TestRun.html"
    assert not (tmp_path / "report.html").exists()


@pytest.mark.fab_test
def test_a_render_failure_never_raises(tmp_path, monkeypatch):
    """A broken report must not fail a passing build."""
    monkeypatch.setenv("ANALYZER_REPORT", "1")
    from fabric_ci_cd_dataops.scripts import _report_html

    def _boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(_report_html, "render_report", _boom)
    envelope = _envelope()

    attach_report(envelope, tmp_path / "envelope.json")  # must not raise

    assert "native_html_output_path" not in envelope


# --------------------------------------------------------------------------- #
# The CLI flag
# --------------------------------------------------------------------------- #


@pytest.fixture
def artifact_tree(tmp_path):
    (tmp_path / "Sales.SemanticModel").mkdir()
    return tmp_path


@pytest.mark.fab_test
def test_report_flag_exists_on_an_analyzer_subcommand():
    result = _run_cli("bpa", "--help")

    assert result.returncode == 0, result.stderr
    assert "--report" in result.stdout
    assert "--no-report" in result.stdout


@pytest.mark.fab_test
def test_dry_run_writes_no_report(artifact_tree):
    """--dry-run runs nothing, so there is nothing to report on."""
    output_dir = artifact_tree / "results"
    result = _run_cli(
        "bpa",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(output_dir),
        "--report",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert not list(output_dir.rglob("report.html"))


@pytest.mark.fab_test
def test_no_index_is_written_without_the_flag(artifact_tree):
    """Opt-in applies to the index too: no unasked-for file appears."""
    output_dir = artifact_tree / "results"
    _run_cli(
        "all",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(output_dir),
        "--dry-run",
    )

    assert not (output_dir / "index.html").exists()


@pytest.mark.fab_test
def test_a_single_analyzer_run_writes_no_index(artifact_tree):
    """Indexing one analyzer is a page pointing at a single link."""
    output_dir = artifact_tree / "results"
    _run_cli(
        "bpa",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(output_dir),
        "--report",
        "--dry-run",
    )

    assert not (output_dir / "index.html").exists()


@pytest.mark.fab_test
def test_report_is_a_valid_config_key():
    from fabric_ci_cd_dataops.scripts._config import validate_config

    validate_config({"report": True})


@pytest.mark.fab_test
def test_report_config_key_must_be_a_boolean():
    from fabric_ci_cd_dataops.scripts._config import ConfigError, validate_config

    with pytest.raises(ConfigError):
        validate_config({"report": "yes"})


@pytest.mark.fab_test
def test_report_key_is_in_the_published_schema():
    """The schema and the loader's key list must not drift."""
    from pathlib import Path

    import fabric_ci_cd_dataops

    schema_path = (
        Path(fabric_ci_cd_dataops.__file__).parent / "schemas" / "fab-test.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "report" in schema["properties"]
