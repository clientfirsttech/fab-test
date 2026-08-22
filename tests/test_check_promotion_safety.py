"""Unit tests for scripts/check_promotion_safety.py."""

import sys
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.check_promotion_safety import PromotionSafetyChecker, main


@pytest.fixture
def checker(tmp_path: Path):
    """Create a PromotionSafetyChecker backed by a temporary environments.yml."""
    config = tmp_path / "environments.yml"
    config.write_text(
        """
promotion_chain:
  - testbed
  - dev
  - test
  - prod
environments:
  testbed:
    description: "TestBed"
    workspace_id: "ws-testbed"
    allowed_branches:
      - testbed
      - "feature/**"
      - "release/**"
    promotion_target: dev
    previous_environment: null
    requires_validation: true
    requires_security_scan: true
    requires_ai_validation: true
    allows_rollback: true
  dev:
    description: "Dev"
    workspace_id: "ws-dev"
    allowed_branches:
      - develop
      - "feature/**"
      - "release/**"
    promotion_target: test
    previous_environment: testbed
    requires_validation: true
    requires_security_scan: true
    requires_ai_validation: false
    allows_rollback: true
  test:
    description: "Test"
    workspace_id: "ws-test"
    allowed_branches:
      - develop
      - "feature/**"
      - "release/**"
    promotion_target: prod
    previous_environment: dev
    requires_validation: true
    requires_security_scan: true
    requires_ai_validation: false
    allows_rollback: true
  prod:
    description: "Prod"
    workspace_id: "ws-prod"
    allowed_branches:
      - main
    promotion_target: null
    previous_environment: test
    requires_validation: true
    requires_security_scan: true
    requires_ai_validation: false
    allows_rollback: false
    deployment_window:
      enabled: false
      allowed_days:
        - Monday
      allowed_hours_utc:
        start: "00:00"
        end: "23:59"
"""
    )
    return PromotionSafetyChecker(str(config))


class TestPromotionChain:
    """Tests for promotion chain validation."""

    def test_valid_adjacent_step(self, checker: PromotionSafetyChecker):
        """Adjacent promotion step is allowed."""
        assert checker.validate_promotion_chain("dev", "test", terse=True) is True

    def test_skip_step_fails(self, checker: PromotionSafetyChecker):
        """Skipping a step in the chain is rejected."""
        assert checker.validate_promotion_chain("testbed", "test", terse=True) is False

    def test_unknown_environment_fails(self, checker: PromotionSafetyChecker):
        """Unknown source or target is rejected."""
        assert checker.validate_promotion_chain("dev", "staging", terse=True) is False


class TestBranchGuard:
    """Tests for branch/environment guard."""

    def test_dev_allows_feature_branch(self, checker: PromotionSafetyChecker):
        """Dev environment allows feature branches per metadata."""
        assert checker.validate_branch_for_target("dev", branch="feature/x", terse=True) is True

    def test_dev_blocks_testbed_branch(self, checker: PromotionSafetyChecker):
        """Dev environment does not allow the testbed branch."""
        assert checker.validate_branch_for_target("dev", branch="testbed", terse=True) is False

    def test_testbed_requires_allowed_branch(self, checker: PromotionSafetyChecker):
        """Testbed deployment requires an allowed branch."""
        assert checker.validate_branch_for_target("testbed", branch="testbed", terse=True) is True
        assert checker.validate_branch_for_target("testbed", branch="feature/x", terse=True) is True
        assert checker.validate_branch_for_target("testbed", branch="release/1.0", terse=True) is True
        assert checker.validate_branch_for_target("testbed", branch="develop", terse=True) is False
        assert checker.validate_branch_for_target("testbed", branch="dev", terse=True) is False
        assert checker.validate_branch_for_target("testbed", branch="development", terse=True) is False

    def test_prod_requires_main_branch(self, checker: PromotionSafetyChecker):
        """Production deployments require the main branch."""
        assert checker.validate_branch_for_target("prod", branch="develop", terse=True) is False

    def test_prod_requires_workflow_dispatch(self, checker: PromotionSafetyChecker):
        """Production deployments require workflow_dispatch event."""
        assert checker.validate_branch_for_target(
            "prod", branch="main", event_name="push", terse=True
        ) is False

    def test_prod_main_dispatch_allowed(self, checker: PromotionSafetyChecker):
        """Production deployments allowed from main via workflow_dispatch."""
        assert checker.validate_branch_for_target(
            "prod", branch="main", event_name="workflow_dispatch", terse=True
        ) is True


class TestDeploymentWindow:
    """Tests for deployment window validation."""

    def test_disabled_window_always_passes(self, checker: PromotionSafetyChecker):
        """Disabled deployment window always passes."""
        assert checker.check_deployment_window("prod", terse=True) is True


class TestCheckRequirements:
    """Tests for the aggregate check_requirements entry point."""

    def test_dev_to_test_passes(self, checker: PromotionSafetyChecker):
        """Promoting dev -> test from a feature branch passes."""
        results = checker.check_requirements(
            "SalesModel", "dev", "test", branch="feature/x", terse=True
        )
        assert results["all_passed"] is True

    def test_testbed_to_dev_passes(self, checker: PromotionSafetyChecker):
        """Promoting testbed -> dev passes."""
        results = checker.check_requirements(
            "SalesModel", "testbed", "dev", branch="develop", terse=True
        )
        assert results["all_passed"] is True

    def test_skip_step_blocked(self, checker: PromotionSafetyChecker):
        """Skipping a promotion step is blocked."""
        results = checker.check_requirements(
            "SalesModel", "testbed", "test", branch="develop", terse=True
        )
        assert results["all_passed"] is False

    def test_prod_from_develop_blocked(self, checker: PromotionSafetyChecker):
        """Promoting to prod from develop is blocked."""
        results = checker.check_requirements(
            "SalesModel", "test", "prod", branch="develop", terse=True
        )
        assert results["all_passed"] is False


class TestMain:
    """Tests for the CLI entry point."""

    def test_main_approved_exit(self, checker: PromotionSafetyChecker, tmp_path: Path, monkeypatch):
        """Approved promotion exits 0 and writes JSON when requested."""
        output = tmp_path / "promotion-result.json"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "check_promotion_safety.py",
                "--artifact-name",
                "SalesModel",
                "--source-environment",
                "dev",
                "--target-environment",
                "test",
                "--branch",
                "feature/x",
                "--output-json",
                str(output),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        assert output.exists()

    def test_main_blocked_exit(self, checker: PromotionSafetyChecker, tmp_path: Path, monkeypatch):
        """Blocked promotion exits 1."""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "check_promotion_safety.py",
                "--artifact-name",
                "SalesModel",
                "--source-environment",
                "testbed",
                "--target-environment",
                "test",
                "--branch",
                "develop",
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
