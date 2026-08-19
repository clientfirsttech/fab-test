"""Unit tests for security scanning helpers.

These tests exercise the aggregation and scanning scripts without running
real secret-detection against the repository. They validate file parsing,
exclusion logic, and output schemas.
"""

import json
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.aggregate_security_findings import load_findings
from fabric_ci_cd_dataops.scripts.aggregate_security_findings import main as aggregate_main
from fabric_ci_cd_dataops.scripts.scan_credentials import PATTERNS, scan_file_for_credentials
from fabric_ci_cd_dataops.scripts.scan_entropy import calculate_entropy, scan_file_for_high_entropy


class TestAggregateSecurityFindings:
    """Tests for aggregate_security_findings."""

    def test_load_findings_secret_format(self, tmp_path: Path):
        """Secret findings use top-level 'results' list."""
        path = tmp_path / "secret-findings.json"
        path.write_text(json.dumps({"results": [{"file": "a.py", "line": 1}]}))
        findings = load_findings(str(path), "secret")
        assert len(findings) == 1
        assert findings[0]["file"] == "a.py"

    def test_load_findings_entropy_format(self, tmp_path: Path):
        """Entropy findings use top-level 'findings' list and get a type tag."""
        path = tmp_path / "entropy-findings.json"
        path.write_text(json.dumps({"findings": [{"file": "b.py", "line": 2}]}))
        findings = load_findings(str(path), "high-entropy")
        assert len(findings) == 1
        assert findings[0]["type"] == "high-entropy"

    def test_load_findings_missing_file(self, tmp_path: Path):
        """Missing files produce an empty list rather than crashing."""
        findings = load_findings(str(tmp_path / "missing.json"), "secret")
        assert findings == []

    def test_aggregate_main(self, tmp_path: Path, monkeypatch):
        """Main aggregates all three finding sources and writes JSON."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "secret-findings.json").write_text(
            json.dumps({"results": [{"file": "a.py"}]})
        )
        (tmp_path / "entropy-findings.json").write_text(
            json.dumps({"findings": [{"file": "b.py"}]})
        )
        (tmp_path / "credential-findings.json").write_text(
            json.dumps({"findings": [{"file": "c.py"}]})
        )

        rc = aggregate_main()
        assert rc == 0
        output = json.loads((tmp_path / "security-findings.json").read_text())
        assert output["count"] == 3
        assert len(output["findings"]) == 3


class TestScanCredentials:
    """Tests for scan_credentials."""

    @pytest.fixture
    def sample_file(self, tmp_path: Path):
        """Create a file with a known credential pattern."""
        path = tmp_path / "sample.py"
        path.write_text('api_key = "AKIAIOSFODNN7EXAMPLE"\n')
        return path

    def test_detects_aws_key(self, sample_file: Path):
        """AWS access key pattern is detected."""
        findings = scan_file_for_credentials(sample_file)
        assert any(f["pattern"] == "aws_key" for f in findings)

    def test_skips_safe_files(self, tmp_path: Path):
        """SAFE_FILES are not scanned."""
        readme = tmp_path / "README.md"
        readme.write_text('password = "super_secret_12345678"\n')
        assert scan_file_for_credentials(readme) == []

    def test_skills_docs_excluded(self, tmp_path: Path):
        """Markdown files inside .github/skills path are skipped."""
        skills_dir = tmp_path / ".github" / "skills"
        skills_dir.mkdir(parents=True)
        doc = skills_dir / "guide.md"
        doc.write_text('token = "******"\n')
        assert scan_file_for_credentials(doc) == []

    def test_patterns_cover_expected_keys(self):
        """Expected credential pattern names are registered."""
        expected = {
            "aws_key",
            "azure_storage_key",
            "github_token",
            "slack_token",
            "private_key",
            "api_key",
            "password",
            "secret",
            "token",
            "connection_string",
        }
        assert expected.issubset(set(PATTERNS))


class TestScanEntropy:
    """Tests for scan_entropy."""

    def test_entropy_empty_string(self):
        """Empty string has zero entropy."""
        assert calculate_entropy("") == 0.0

    def test_entropy_uniform_string(self):
        """A repeated single character has low entropy."""
        assert calculate_entropy("aaaaaaaaaa") < 1.0

    def test_entropy_high_random_string(self):
        """A diverse long string has high entropy."""
        value = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        assert calculate_entropy(value) > 4.5

    def test_scan_finds_high_entropy_value(self, tmp_path: Path):
        """A high-entropy quoted string is reported."""
        path = tmp_path / "secrets.txt"
        high_entropy = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        path.write_text(f'secret = "{high_entropy}"\n')
        findings = scan_file_for_high_entropy(path)
        assert len(findings) >= 1
        assert findings[0]["line"] == 1

    def test_scan_respects_threshold(self, tmp_path: Path):
        """Low-entropy strings are not reported."""
        path = tmp_path / "safe.txt"
        path.write_text('value = "aaaaaaaaaaaaaaaaaaaaaaaa"\n')
        findings = scan_file_for_high_entropy(path)
        assert findings == []

    def test_scan_skips_excluded_extensions(self, tmp_path: Path):
        """Files with excluded extensions are skipped."""
        path = tmp_path / "data.pbix"
        path.write_bytes(b"x" * 100)
        assert scan_file_for_high_entropy(path) == []
