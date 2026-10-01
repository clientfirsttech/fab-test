"""`fab-test rdl` on the shared verbosity ladder (RDL Quiet Output epic).

Runs the real CLI in a subprocess -- the console script is not installed in
every environment, `python -m fab_test.scripts.fab_test` is the same entry
point -- so -q, -v and -vv are proven through the parser, the parent's
narration and the wrapper, not just the wrapper.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_FIXTURES = _REPO / ".fabric" / "artifacts" / "rdl"

_CLEAN = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">'
    "<ReportSections><ReportSection><Body><ReportItems /><Height>1in</Height></Body>"
    "<Width>6in</Width><Page><PageWidth>8.5in</PageWidth></Page></ReportSection></ReportSections></Report>"
)

_QUIET_LINE = re.compile(r"^rdl (passed|warning|failed) e=\d+ w=\d+ \S.*envelope\.json$")


def _run(tmp_path: Path, *args: str, artifact: str = "DS-02", env: dict | None = None):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    if artifact == "CLEAN":
        (artifacts / "CLEAN.rdl").write_text(_CLEAN, encoding="utf-8")
    elif artifact == "BROKEN":
        (artifacts / "BROKEN.rdl").write_text("<Report", encoding="utf-8")
    else:
        shutil.copy(_FIXTURES / f"{artifact}.rdl", artifacts / f"{artifact}.rdl")
    full_env = {
        **{k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "CI", "ANALYZER_VERBOSITY")},
        "PYTHONPATH": str(_REPO / "src"),
        "PYTHONIOENCODING": "utf-8",
        **(env or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "rdl", "--artifact-dir", str(artifacts),
         "--output-dir", str(tmp_path / "out"), *args],
        cwd=tmp_path, env=full_env, capture_output=True, text=True, encoding="utf-8", check=False, timeout=120,
    )


class TestQuiet:
    def test_prints_exactly_one_line_for_a_failing_artifact_and_still_fails(self, tmp_path):
        proc = _run(tmp_path, "-q")

        lines = proc.stdout.strip().splitlines()
        assert len(lines) == 1, proc.stdout
        assert _QUIET_LINE.match(lines[0]), lines[0]
        assert lines[0].startswith("rdl failed e=")
        assert proc.returncode == 1

    def test_the_line_counts_errors_and_warnings_from_the_envelope(self, tmp_path):
        proc = _run(tmp_path, "-q")

        envelope = next((tmp_path / "out").rglob("envelope.json"))
        findings = json.loads(envelope.read_text(encoding="utf-8"))["findings"]
        errors = sum(f["severity"] == "error" for f in findings)
        warnings = sum(f["severity"] == "warning" for f in findings)
        assert f"e={errors} w={warnings}" in proc.stdout

    def test_a_clean_report_is_one_passed_line_and_exit_0(self, tmp_path):
        proc = _run(tmp_path, "-q", artifact="CLEAN")

        assert proc.stdout.strip().splitlines() == [
            f"rdl passed e=0 w=0 {Path('out') / 'rdl' / 'CLEAN' / 'envelope.json'}"
        ]
        assert proc.returncode == 0

    def test_the_path_is_relative_to_the_working_directory(self, tmp_path):
        proc = _run(tmp_path, "-q")

        assert str(tmp_path) not in proc.stdout

    @pytest.mark.parametrize("verbose", ["-v", "-vv"])
    def test_quiet_with_verbose_exits_2_naming_the_conflict(self, tmp_path, verbose):
        proc = _run(tmp_path, "-q", verbose)

        assert proc.returncode == 2
        assert "-q" in proc.stderr

    def test_json_format_stays_pure_json_and_stderr_is_silent_for_a_pass(self, tmp_path):
        proc = _run(tmp_path, "-q", "--format", "json", artifact="CLEAN")

        json.loads(proc.stdout)
        assert proc.stderr.strip() == ""

    def test_ci_annotations_still_reach_stderr(self, tmp_path):
        proc = _run(tmp_path, "-q", env={"GITHUB_ACTIONS": "true"})

        assert "::error::" in proc.stderr

    def test_results_on_disk_are_the_same_as_without_the_flag(self, tmp_path):
        _run(tmp_path / "q", "-q")
        _run(tmp_path / "v", "-v")

        def rules(root: Path):
            envelope = next((root / "out").rglob("envelope.json"))
            return json.loads(envelope.read_text(encoding="utf-8"))["findings"]

        assert [f["rule"] for f in rules(tmp_path / "q")] == [f["rule"] for f in rules(tmp_path / "v")]


class TestLevels:
    def test_default_names_the_banner_and_no_rules_path_or_table(self, tmp_path):
        out = _run(tmp_path).stdout

        assert "RDL Static Analysis" in out
        assert "Rules:" not in out
        assert "╭" not in out

    def test_verbose_adds_the_rules_path_and_the_findings_table(self, tmp_path):
        out = _run(tmp_path, "-v").stdout

        assert "Rules:" in out
        assert "╭" in out
        assert "DS-02" in out

    def test_debug_adds_the_rule_counts(self, tmp_path):
        out = _run(tmp_path, "-vv").stdout

        assert re.search(r"\d+ active, \d+ planned", out)


class TestQuietEdges:
    def test_the_environment_variable_alone_gives_the_quiet_line(self, tmp_path):
        proc = _run(tmp_path, env={"ANALYZER_VERBOSITY": "summary"})

        lines = proc.stdout.strip().splitlines()
        assert len(lines) == 1 and _QUIET_LINE.match(lines[0]), proc.stdout

    def test_a_malformed_report_is_still_one_line_with_an_error_count(self, tmp_path):
        proc = _run(tmp_path, "-q", artifact="BROKEN")

        assert proc.stdout.strip().splitlines()[0].startswith("rdl failed e=1 w=0 ")
        assert proc.returncode == 1

    def test_a_missing_rules_file_is_not_hidden_by_an_earlier_run_under_q(self, tmp_path):
        _run(tmp_path, "-q")

        proc = _run(tmp_path, "-q", "--rules-path", str(tmp_path / "nope.json"))

        assert proc.returncode == 1
        assert proc.stdout.strip().splitlines()[0].startswith("rdl failed e=1 w=0 ")
