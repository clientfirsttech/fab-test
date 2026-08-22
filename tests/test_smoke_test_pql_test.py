"""Unit tests for scripts/smoke_test_pql_test.py."""

import json

import pytest

pytestmark = [pytest.mark.smoke_pql_test, pytest.mark.analyzers]


from fabric_ci_cd_dataops.scripts.smoke_test_pql_test import (
    bump_platform_content,
    platform_path,
    validate_branch,
)


class TestPlatformPath:
    """Tests for platform path resolution."""

    def test_resolves_to_sample_model(self):
        """Given the constant is defined, it should point to SampleModel-PQLAssert."""
        path = platform_path()

        assert path.name == ".platform"
        assert path.parts[-2] == "SampleModel-PQLAssert.SemanticModel"


class TestBumpPlatformContent:
    """Tests for bump_platform_content."""

    def test_adds_timestamp_to_config(self):
        """Given a .platform JSON string, should add _smokeTestTimestamp to config."""
        content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "metadata": {"type": "SemanticModel", "displayName": "Sample"},
                "config": {"version": "2.0", "logicalId": "abc-123"},
            },
            indent=2,
        )

        result = json.loads(bump_platform_content(content, "2026-08-06T12:00:00Z"))

        assert result["config"]["_smokeTestTimestamp"] == "2026-08-06T12:00:00Z"
        assert result["config"]["version"] == "2.0"
        assert result["config"]["logicalId"] == "abc-123"
        assert result["metadata"]["displayName"] == "Sample"

    def test_updates_existing_timestamp(self):
        """Given .platform already has timestamp, should update without duplication."""
        content = json.dumps(
            {
                "metadata": {"type": "SemanticModel"},
                "config": {
                    "version": "2.0",
                    "_smokeTestTimestamp": "2026-01-01T00:00:00Z",
                },
            },
            indent=2,
        )

        result = json.loads(bump_platform_content(content, "2026-08-06T12:00:00Z"))

        assert result["config"]["_smokeTestTimestamp"] == "2026-08-06T12:00:00Z"
        assert list(result["config"].keys()).count("_smokeTestTimestamp") == 1

    def test_preserves_trailing_newline(self):
        """Given input ends with newline, output should also end with newline."""
        content = '{"config":{}}\n'

        result = bump_platform_content(content, "2026-08-06T12:00:00Z")

        assert result.endswith("\n")


class TestValidateBranch:
    """Tests for branch validation."""

    def test_develop_is_allowed(self):
        """Given branch 'develop', validation should not raise."""
        validate_branch("develop")

    def test_feature_branch_is_allowed(self):
        """Given a feature branch, validation should not raise."""
        validate_branch("feature/pql-test-smoke")

    def test_main_is_rejected(self):
        """Given branch 'main', validation should raise SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            validate_branch("main")
        assert exc_info.value.code == 1

    def test_random_branch_is_rejected(self):
        """Given an unsupported branch, validation should raise SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            validate_branch("hotfix/123")
        assert exc_info.value.code == 1
