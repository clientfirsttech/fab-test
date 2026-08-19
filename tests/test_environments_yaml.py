"""Contract tests for scripts/validate_environments_yaml.py."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from fabric_ci_cd_dataops.scripts.validate_environments_yaml import validate_environments_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = REPO_ROOT / ".github" / "metadata" / "environments.yml"
VALIDATOR_SCRIPT = "validate-environments-yaml"

pytestmark = pytest.mark.fab_test


def _write_yaml(tmp_path: Path, data: dict[str, Any]) -> Path:
    import yaml

    path = tmp_path / "environments.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestValidateEnvironmentsYaml:
    """Unit tests for the environments.yml validator."""

    def test_valid_minimal_config_passes(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path,
            {
                "defaults": {"repository_directory": ".fabric/artifacts"},
                "environments": {
                    "dev": {
                        "description": "Dev",
                        "workspace_id": "",
                        "allowed_branches": ["develop"],
                        "promotion_target": "test",
                    }
                },
            },
        )
        assert validate_environments_yaml(path) == []

    def test_missing_file_reported(self, tmp_path: Path):
        missing = tmp_path / "environments.yml"
        errors = validate_environments_yaml(missing)
        assert len(errors) == 1
        assert "File not found" in errors[0]

    def test_invalid_yaml_reported(self, tmp_path: Path):
        path = tmp_path / "environments.yml"
        path.write_text("environments: [unclosed", encoding="utf-8")
        errors = validate_environments_yaml(path)
        assert any("Invalid YAML" in e for e in errors)

    def test_missing_top_level_keys_reported(self, tmp_path: Path):
        path = _write_yaml(tmp_path, {"defaults": {}})
        errors = validate_environments_yaml(path)
        assert any("Missing top-level keys" in e and "environments" in e for e in errors)

    def test_environments_must_be_non_empty_mapping(self, tmp_path: Path):
        path = _write_yaml(tmp_path, {"defaults": {}, "environments": []})
        errors = validate_environments_yaml(path)
        assert any("non-empty mapping" in e for e in errors)

    def test_environment_missing_required_keys_reported(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path,
            {
                "defaults": {},
                "environments": {"dev": {"description": "Dev"}},
            },
        )
        errors = validate_environments_yaml(path)
        assert any("missing required keys" in e for e in errors)

    def test_environment_unexpected_keys_reported(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path,
            {
                "defaults": {},
                "environments": {
                    "dev": {
                        "description": "Dev",
                        "workspace_id": "",
                        "allowed_branches": ["develop"],
                        "promotion_target": "test",
                        "unknown_key": True,
                    }
                },
            },
        )
        errors = validate_environments_yaml(path)
        assert any("unexpected keys" in e and "unknown_key" in e for e in errors)

    def test_allowed_branches_must_be_list(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path,
            {
                "defaults": {},
                "environments": {
                    "dev": {
                        "description": "Dev",
                        "workspace_id": "",
                        "allowed_branches": "develop",
                        "promotion_target": "test",
                    }
                },
            },
        )
        errors = validate_environments_yaml(path)
        assert any("allowed_branches must be a list" in e for e in errors)

    def test_promotion_chain_must_reference_known_environments(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path,
            {
                "defaults": {},
                "promotion_chain": ["dev", "prod"],
                "environments": {
                    "dev": {
                        "description": "Dev",
                        "workspace_id": "",
                        "allowed_branches": ["develop"],
                        "promotion_target": "test",
                    }
                },
            },
        )
        errors = validate_environments_yaml(path)
        assert any("Unknown environments in promotion_chain" in e and "prod" in e for e in errors)

    def test_all_environments_must_appear_in_promotion_chain(self, tmp_path: Path):
        path = _write_yaml(
            tmp_path,
            {
                "defaults": {},
                "promotion_chain": ["dev"],
                "environments": {
                    "dev": {
                        "description": "Dev",
                        "workspace_id": "",
                        "allowed_branches": ["develop"],
                        "promotion_target": None,
                    },
                    "test": {
                        "description": "Test",
                        "workspace_id": "",
                        "allowed_branches": ["develop"],
                        "promotion_target": "prod",
                    },
                },
            },
        )
        errors = validate_environments_yaml(path)
        assert any("Environments missing from promotion_chain" in e and "test" in e for e in errors)

    def test_default_environments_yml_is_valid(self):
        """The committed environments.yml must always satisfy the schema."""
        assert DEFAULT_ENV_PATH.exists()
        errors = validate_environments_yaml(DEFAULT_ENV_PATH)
        assert errors == [], f"Committed environments.yml is invalid: {errors}"


class TestValidateEnvironmentsYamlCli:
    """CLI smoke tests for the validator script."""

    def test_cli_returns_zero_for_default_path(self):
        result = subprocess.run(
            [VALIDATOR_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_cli_returns_one_for_invalid_yaml(self, tmp_path: Path):
        path = tmp_path / "environments.yml"
        path.write_text("not: valid: [", encoding="utf-8")
        result = subprocess.run(
            [VALIDATOR_SCRIPT, "--path", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        assert result.returncode == 1
        assert result.stderr is not None
        assert "Invalid YAML" in result.stderr
