"""Unit tests for environment configuration validators and generators."""

import sys
from pathlib import Path
from typing import ClassVar
from unittest import mock

import pytest

from fabric_ci_cd_dataops.scripts.generate_fabric_cicd_config import build_environment_config, load_config
from fabric_ci_cd_dataops.scripts.generate_fabric_cicd_config import main as generate_main
from fabric_ci_cd_dataops.scripts.validate_environments_yaml import validate_environments_yaml


@pytest.fixture
def valid_environments(tmp_path: Path):
    """Write a minimal valid environments.yml and return its path."""
    path = tmp_path / "environments.yml"
    path.write_text(
        """
promotion_chain:
  - dev
  - test
defaults:
  repository_directory: ".fabric/artifacts"
  item_type_in_scope:
    - "*"
environments:
  dev:
    description: "Development"
    workspace_id: "ws-dev"
    allowed_branches:
      - develop
    promotion_target: test
    requires_validation: true
    requires_security_scan: true
    requires_ai_validation: false
  test:
    description: "Testing"
    workspace_id: "ws-test"
    allowed_branches:
      - develop
    promotion_target: null
    requires_validation: true
    requires_security_scan: true
    requires_ai_validation: false
"""
    )
    return path


class TestValidateEnvironmentsYaml:
    """Tests for validate_environments_yaml."""

    def test_valid_file(self, valid_environments: Path):
        """A valid file produces no errors."""
        errors = validate_environments_yaml(valid_environments)
        assert errors == []

    def test_missing_file(self, tmp_path: Path):
        """Missing file returns a file-not-found error."""
        errors = validate_environments_yaml(tmp_path / "missing.yml")
        assert any("File not found" in e for e in errors)

    def test_invalid_yaml(self, tmp_path: Path):
        """Malformed YAML is reported."""
        path = tmp_path / "bad.yml"
        path.write_text("environments: [unclosed")
        errors = validate_environments_yaml(path)
        assert any("Invalid YAML" in e for e in errors)

    def test_missing_top_level_key(self, tmp_path: Path):
        """Missing required top-level key is reported."""
        path = tmp_path / "incomplete.yml"
        path.write_text("environments:\n  dev:\n    workspace_id: ws\n")
        errors = validate_environments_yaml(path)
        assert any("Missing top-level keys" in e for e in errors)

    def test_empty_environments(self, tmp_path: Path):
        """Empty environments mapping is reported."""
        path = tmp_path / "empty.yml"
        path.write_text(
            "defaults:\n  repository_directory: .\nenvironments: {}\n"
        )
        errors = validate_environments_yaml(path)
        assert any("'environments' must be a non-empty mapping" in e for e in errors)

    def test_promotion_chain_mismatch(self, tmp_path: Path):
        """Environments not listed in promotion_chain are reported."""
        path = tmp_path / "mismatch.yml"
        path.write_text(
            """
defaults:
  repository_directory: "."
environments:
  dev:
    description: "Dev"
    workspace_id: "ws-dev"
    allowed_branches: [develop]
    promotion_target: null
promotion_chain: []
"""
        )
        errors = validate_environments_yaml(path)
        assert any("Environments missing from promotion_chain" in e for e in errors)


class TestValidateEnvironmentsSchema:
    """Tests for validate_environments_schema."""

    def test_valid_config(self, valid_environments: Path):
        """The schema validator accepts the same valid file."""
        from fabric_ci_cd_dataops.scripts.validate_environments_schema import main as schema_main

        with mock.patch.object(sys, "argv", ["validate_environments_schema.py", "--file", str(valid_environments)]):
            with pytest.raises(SystemExit) as exc_info:
                schema_main()
            assert exc_info.value.code == 0


class TestValidateEnvBlock:
    """Tests for _validate_env_block's structural branches."""

    BASE_BLOCK: ClassVar = {
        "description": "Development",
        "workspace_id": "ws-dev",
        "allowed_branches": ["develop"],
        "promotion_target": "test",
        "requires_validation": True,
        "requires_security_scan": True,
        "requires_ai_validation": False,
    }

    def test_allowed_branches_not_a_list(self):
        """A string allowed_branches is reported as needing a list."""
        from fabric_ci_cd_dataops.scripts.validate_environments_schema import _validate_env_block

        block = {**self.BASE_BLOCK, "allowed_branches": "develop"}
        errors = _validate_env_block("environments.dev", block)
        assert any(e.path == "environments.dev.allowed_branches" and "Must be a list" in e.message for e in errors)

    def test_allowed_branches_empty(self):
        """An empty allowed_branches list is reported as must-not-be-empty."""
        from fabric_ci_cd_dataops.scripts.validate_environments_schema import _validate_env_block

        block = {**self.BASE_BLOCK, "allowed_branches": []}
        errors = _validate_env_block("environments.dev", block)
        assert any(
            e.path == "environments.dev.allowed_branches" and "Must not be empty" in e.message for e in errors
        )

    def test_boolean_field_not_a_bool(self):
        """A non-boolean requires_validation is reported as needing a boolean."""
        from fabric_ci_cd_dataops.scripts.validate_environments_schema import _validate_env_block

        block = {**self.BASE_BLOCK, "requires_validation": "true"}
        errors = _validate_env_block("environments.dev", block)
        assert any(
            e.path == "environments.dev.requires_validation" and "Must be a boolean" in e.message for e in errors
        )

    def test_deployment_window_not_a_mapping(self):
        """A non-mapping deployment_window is reported as needing a mapping."""
        from fabric_ci_cd_dataops.scripts.validate_environments_schema import _validate_env_block

        block = {**self.BASE_BLOCK, "deployment_window": "always"}
        errors = _validate_env_block("environments.prod", block)
        assert any(
            e.path == "environments.prod.deployment_window" and "Must be a mapping" in e.message for e in errors
        )

    def test_deployment_window_missing_enabled(self):
        """A deployment_window mapping missing 'enabled' names the missing key."""
        from fabric_ci_cd_dataops.scripts.validate_environments_schema import _validate_env_block

        block = {**self.BASE_BLOCK, "deployment_window": {"allowed_days": ["Mon"], "allowed_hours_utc": "9-17"}}
        errors = _validate_env_block("environments.prod", block)
        assert any(
            e.path == "environments.prod.deployment_window.enabled"
            and "Missing required deployment_window key" in e.message
            for e in errors
        )


class TestGenerateFabricCicdConfig:
    """Tests for generate_fabric_cicd_config."""

    def test_load_config(self, valid_environments: Path, tmp_path: Path):
        """load_config reads environments.yml from repo root."""
        repo = tmp_path
        metadata = repo / ".github" / "metadata"
        metadata.mkdir(parents=True)
        (metadata / "environments.yml").write_text(valid_environments.read_text())
        config = load_config(repo)
        assert "environments" in config
        assert config["environments"]["dev"]["workspace_id"] == "ws-dev"

    def test_build_environment_config(self, valid_environments: Path):
        """build_environment_config merges defaults and strips metadata keys."""
        import yaml

        config = yaml.safe_load(valid_environments.read_text())
        env_config = build_environment_config(config, "dev", "")
        assert env_config["workspace_id"] == "ws-dev"
        assert "allowed_branches" not in env_config
        assert "requires_validation" not in env_config

    def test_build_with_override_workspace(self, valid_environments: Path):
        """CLI workspace ID overrides the configured value."""
        import yaml

        config = yaml.safe_load(valid_environments.read_text())
        env_config = build_environment_config(config, "dev", "override-ws")
        assert env_config["workspace_id"] == "override-ws"

    def test_missing_environment_exits(self, valid_environments: Path):
        """Unknown environment causes sys.exit(1)."""
        import yaml

        config = yaml.safe_load(valid_environments.read_text())
        with pytest.raises(SystemExit) as exc_info:
            build_environment_config(config, "prod", "")
        assert exc_info.value.code == 1

    def test_main_generates_output(self, valid_environments: Path, tmp_path: Path, monkeypatch):
        """Main writes a YAML config file for the requested environment."""
        repo = tmp_path
        metadata = repo / ".github" / "metadata"
        metadata.mkdir(parents=True)
        (metadata / "environments.yml").write_text(valid_environments.read_text())

        output = tmp_path / "fabric-cicd-env-config.yml"
        argv = [
            "generate_fabric_cicd_config.py",
            "--environment",
            "dev",
            "--output",
            str(output),
        ]
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
        generate_main()

        assert output.exists()
        generated = output.read_text()
        assert "workspace_id: ws-dev" in generated
