"""Unit tests for the shared analyzer pytest reporter (vision §2.8 F2 + R3)."""

import io
import sys
from pathlib import Path
from typing import Any


from fabric_ci_cd_dataops.scripts._analyzer_report import (
    AnalyzerReporter,
    AnalyzerResult,
    _resolve_verbosity,
)


class TestResolveVerbosity:
    """Tests for verbosity resolution from env var and pytest counts."""

    def test_default_level(self, monkeypatch):
        """Given no env var and no -v, returns default."""
        monkeypatch.delenv("ANALYZER_VERBOSITY", raising=False)
        assert _resolve_verbosity(0) == "default"

    def test_env_summary_suppresses_pytest_default(self, monkeypatch):
        """Given ANALYZER_VERBOSITY=summary, returns summary even with -v."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
        assert _resolve_verbosity(1) == "summary"

    def test_pytest_vv_reaches_debug(self, monkeypatch):
        """Given -vv, maps to debug level (highest pytest count)."""
        monkeypatch.delenv("ANALYZER_VERBOSITY", raising=False)
        assert _resolve_verbosity(2) == "debug"

    def test_pytest_v_reaches_verbose(self, monkeypatch):
        """Given -v, maps to verbose level."""
        monkeypatch.delenv("ANALYZER_VERBOSITY", raising=False)
        assert _resolve_verbosity(1) == "verbose"

    def test_env_debug_wins(self, monkeypatch):
        """Given ANALYZER_VERBOSITY=debug, returns debug regardless of -v count."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
        assert _resolve_verbosity(0) == "debug"

    def test_env_verbose(self, monkeypatch):
        """Given ANALYZER_VERBOSITY=verbose, returns verbose."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "verbose")
        assert _resolve_verbosity(0) == "verbose"


class TestAnalyzerReporter:
    """Tests for AnalyzerReporter rendering behavior."""

    def _make(self, **kwargs: Any) -> AnalyzerResult:
        defaults: dict[str, Any] = {
            "analyzer": "bpa",
            "artifact": "SalesModel",
            "status": "passed",
            "findings_count": 0,
            "duration_ms": 42,
            "envelope_path": "analyzer-results/bpa/SalesModel/envelope.json",
            "native_path": "",
            "skip_reason": "",
            "findings": [],
            "debug_info": "",
        }
        defaults.update(kwargs)
        return AnalyzerResult(**defaults)

    def test_empty_run_table(self):
        """Given no results, summary prints a clear 'No results' message."""
        reporter = AnalyzerReporter()
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="default")
        rendered = out.getvalue()
        assert "No analyzer results recorded" in rendered

    def test_default_includes_per_artifact_line_and_table(self):
        """Given default verbosity, output has per-artifact line and summary table."""
        reporter = AnalyzerReporter()
        reporter.record(self._make(status="passed"))
        reporter.record(self._make(artifact="SampleModel", status="failed", findings_count=3))
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="default")
        rendered = out.getvalue()
        assert "[bpa] SalesModel" in rendered
        assert "[bpa] SampleModel" in rendered
        assert "analyzer" in rendered
        assert "artifact" in rendered
        assert "status" in rendered
        assert "findings" in rendered

    def test_summary_level_table_only(self):
        """Given summary verbosity, only the table is printed."""
        reporter = AnalyzerReporter()
        reporter.record(self._make(status="passed"))
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="summary")
        rendered = out.getvalue()
        assert "[bpa] SalesModel" not in rendered
        assert "analyzer" in rendered
        assert "artifact" in rendered

    def test_verbose_includes_findings(self):
        """Given verbose, per-finding detail is rendered."""
        reporter = AnalyzerReporter()
        findings = [{"rule": "AvoidBiDi", "severity": 2, "object": "Relationship"}]
        reporter.record(self._make(status="warning", findings_count=1, findings=findings))
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="verbose")
        rendered = out.getvalue()
        assert "AvoidBiDi" in rendered
        assert "sev=2" in rendered
        assert "Relationship" in rendered

    def test_debug_includes_debug_info(self):
        """Given debug, command/stdout detail is rendered."""
        reporter = AnalyzerReporter()
        reporter.record(self._make(debug_info="TabularEditor.exe -A rules.json\nstdout line"))
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="debug")
        rendered = out.getvalue()
        assert "TabularEditor.exe" in rendered
        assert "stdout line" in rendered

    def test_skip_reason_visible(self):
        """Given a skipped result, the skip reason appears in default output."""
        reporter = AnalyzerReporter()
        reporter.record(self._make(status="skipped", skip_reason="Linux-only analyzer on Windows"))
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="default")
        rendered = out.getvalue()
        assert "Linux-only analyzer on Windows" in rendered

    def test_job_summary_written(self, tmp_path: Path, monkeypatch):
        """Given GITHUB_STEP_SUMMARY is set, append a Markdown table."""
        summary_file = tmp_path / "summary.md"
        summary_file.write_text("", encoding="utf-8")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        reporter = AnalyzerReporter()
        reporter.record(self._make(status="passed"))
        reporter.record(self._make(artifact="SampleModel", status="failed", findings_count=1))
        out = io.StringIO()
        reporter._print_summary_to(out, verbosity="default")

        content = summary_file.read_text(encoding="utf-8")
        assert "## Analyzer Results" in content
        assert "| analyzer | artifact | status |" in content
        assert "| bpa | SalesModel | ✅ passed |" in content
        assert "| bpa | SampleModel | ❌ failed |" in content
