"""Unit tests for scripts/deploy.py."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from fabric_ci_cd_dataops.scripts.deploy import (
    build_dependency_graph,
    build_environment_config,
    build_plan,
    compute_deployment_phases,
    load_environments_config,
    main,
)


@pytest.fixture
def repo_with_config(tmp_path: Path):
    """Create a temporary repository with a valid environments.yml."""
    metadata = tmp_path / ".github" / "metadata"
    metadata.mkdir(parents=True)
    artifact = tmp_path / ".fabric" / "artifacts" / "SalesModel.SemanticModel"
    artifact.mkdir(parents=True)
    (metadata / "environments.yml").write_text(
        """
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
"""
    )
    return tmp_path


class TestLoadEnvironmentsConfig:
    """Tests for load_environments_config."""

    def test_loads_existing_config(self, repo_with_config: Path):
        """Existing environments.yml is loaded and validated."""
        config = load_environments_config(repo_with_config, terse=True)
        assert "environments" in config
        assert config["environments"]["dev"]["workspace_id"] == "ws-dev"

    def test_missing_config_exits(self, tmp_path: Path):
        """Missing environments.yml causes sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            load_environments_config(tmp_path, terse=True)
        assert exc_info.value.code == 1

    def test_missing_required_key_exits(self, tmp_path: Path):
        """Config missing required keys causes sys.exit(1)."""
        metadata = tmp_path / ".github" / "metadata"
        metadata.mkdir(parents=True)
        (metadata / "environments.yml").write_text("environments: {}\n")
        with pytest.raises(SystemExit) as exc_info:
            load_environments_config(tmp_path, terse=True)
        assert exc_info.value.code == 1


class TestBuildEnvironmentConfig:
    """Tests for build_environment_config."""

    def _artifact(self, repo_with_config: Path) -> Path:
        return repo_with_config / ".fabric" / "artifacts" / "SalesModel.SemanticModel"

    def test_builds_fabric_cicd_config(self, repo_with_config: Path):
        """Config is structured for the real fabric-cicd API."""
        artifact = self._artifact(repo_with_config)
        full_config = load_environments_config(repo_with_config, terse=True)
        env_config = build_environment_config(
            full_config, "dev", "", artifact, terse=True
        )
        assert env_config["core"]["workspace_id"] == "ws-dev"
        assert env_config["core"]["repository_directory"] == str(artifact.parent)
        assert env_config["core"]["item_types_in_scope"] == ["SemanticModel"]
        assert env_config["publish"]["items_to_include"] == [
            "SalesModel.SemanticModel"
        ]
        assert env_config["publish"]["skip"] is False
        assert env_config["unpublish"]["skip"] is True

    def test_cli_workspace_id_override(self, repo_with_config: Path):
        """CLI workspace ID overrides configured value."""
        artifact = self._artifact(repo_with_config)
        full_config = load_environments_config(repo_with_config, terse=True)
        env_config = build_environment_config(
            full_config, "dev", "override-ws", artifact, terse=True
        )
        assert env_config["core"]["workspace_id"] == "override-ws"

    def test_empty_workspace_id_exits(self, repo_with_config: Path):
        """Empty workspace_id causes sys.exit(1)."""
        artifact = self._artifact(repo_with_config)
        full_config = load_environments_config(repo_with_config, terse=True)
        # Remove workspace_id from config to trigger the empty check.
        full_config["environments"]["dev"]["workspace_id"] = ""
        with pytest.raises(SystemExit) as exc_info:
            build_environment_config(
                full_config, "dev", "", artifact, terse=True
            )
        assert exc_info.value.code == 1

    def test_report_deploys_only_itself(self, repo_with_config: Path):
        """Per-artifact config deploys only the named Report.

        Dependencies are handled by phased deployment ordering, not by the
        per-artifact fabric-cicd invocation.
        """
        report = (
            repo_with_config / ".fabric" / "artifacts" / "SalesReport.Report"
        )
        report.mkdir(parents=True)
        model = (
            repo_with_config / ".fabric" / "artifacts" / "SalesModel.SemanticModel"
        )
        model.mkdir(parents=True, exist_ok=True)
        (report / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../SalesModel.SemanticModel"}}}'
        )

        full_config = load_environments_config(repo_with_config, terse=True)
        env_config = build_environment_config(
            full_config, "dev", "", report, terse=True
        )

        assert env_config["core"]["item_types_in_scope"] == ["Report"]
        assert env_config["publish"]["items_to_include"] == ["SalesReport.Report"]

    def test_semantic_model_deploys_only_itself(self, repo_with_config: Path):
        """Per-artifact config deploys only the named SemanticModel."""
        artifact = self._artifact(repo_with_config)
        full_config = load_environments_config(repo_with_config, terse=True)
        env_config = build_environment_config(
            full_config, "dev", "", artifact, terse=True
        )

        assert env_config["core"]["item_types_in_scope"] == ["SemanticModel"]
        assert env_config["publish"]["items_to_include"] == [
            "SalesModel.SemanticModel"
        ]


class TestDependencyGraph:
    """Tests for dependency-aware deployment planning."""

    def _make_repo(self, tmp_path: Path):
        artifacts = tmp_path / ".fabric" / "artifacts"
        artifacts.mkdir(parents=True)
        metadata = tmp_path / ".github" / "metadata"
        metadata.mkdir(parents=True)
        (metadata / "environments.yml").write_text(
            """
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
"""
        )
        return tmp_path

    def _artifact(self, tmp_path: Path, name: str, type_name: str) -> dict[str, str]:
        path = tmp_path / ".fabric" / "artifacts" / name
        path.mkdir(parents=True)
        return {"name": name, "type": type_name, "path": str(path)}

    def test_report_depends_on_semantic_model(self, tmp_path: Path):
        """A Report referencing a local SemanticModel creates an edge."""
        repo = self._make_repo(tmp_path)
        model = self._artifact(repo, "SalesModel.SemanticModel", "SemanticModel")
        report = self._artifact(repo, "SalesReport.Report", "Report")
        (Path(report["path"]) / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../SalesModel.SemanticModel"}}}'
        )

        graph = build_dependency_graph([model, report], repo)
        assert graph == {
            "SalesModel.SemanticModel": set(),
            "SalesReport.Report": {"SalesModel.SemanticModel"},
        }

    def test_compute_phases_orders_dependencies_first(self, tmp_path: Path):
        """SemanticModel is scheduled before dependent Report."""
        repo = self._make_repo(tmp_path)
        model = self._artifact(repo, "SalesModel.SemanticModel", "SemanticModel")
        report = self._artifact(repo, "SalesReport.Report", "Report")
        (Path(report["path"]) / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../SalesModel.SemanticModel"}}}'
        )

        phases = compute_deployment_phases([model, report], repo)
        assert phases == [[model], [report]]

    def test_missing_local_dependency_is_ignored(self, tmp_path: Path):
        """Reports referencing a SemanticModel not in the changed set are allowed."""
        repo = self._make_repo(tmp_path)
        report = self._artifact(repo, "SalesReport.Report", "Report")
        (Path(report["path"]) / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../MissingModel.SemanticModel"}}}'
        )

        phases = compute_deployment_phases([report], repo)
        assert phases == [[report]]

    def test_cycle_detection_fails(self, tmp_path: Path):
        """Circular local dependencies raise ValueError."""
        repo = self._make_repo(tmp_path)
        a = self._artifact(repo, "A.Report", "Report")
        b = self._artifact(repo, "B.Report", "Report")
        # The graph code only cares about byPath references, so two Reports
        # pointing at each other exercises the cycle detector.
        (Path(a["path"]) / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../B.Report"}}}'
        )
        (Path(b["path"]) / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../A.Report"}}}'
        )

        with pytest.raises(ValueError, match="Circular dependency"):
            build_dependency_graph([a, b], repo)

    def test_build_plan_is_json_serializable(self, tmp_path: Path):
        """build_plan produces a JSON-serializable phase structure."""
        repo = self._make_repo(tmp_path)
        model = self._artifact(repo, "SalesModel.SemanticModel", "SemanticModel")
        report = self._artifact(repo, "SalesReport.Report", "Report")
        (Path(report["path"]) / "definition.pbir").write_text(
            '{"datasetReference":{"byPath":{"path":"../SalesModel.SemanticModel"}}}'
        )

        plan = build_plan([model, report], repo)
        serialized = json.dumps(plan)
        parsed = json.loads(serialized)
        assert parsed == [
            {
                "phase": 0,
                "artifacts": [
                    {
                        "name": "SalesModel.SemanticModel",
                        "type": "SemanticModel",
                        "path": model["path"],
                    }
                ],
            },
            {
                "phase": 1,
                "artifacts": [
                    {
                        "name": "SalesReport.Report",
                        "type": "Report",
                        "path": report["path"],
                    }
                ],
            },
        ]


class TestMain:
    """Tests for the CLI entry point."""

    def _artifact(self, repo_with_config: Path) -> Path:
        return repo_with_config / ".fabric" / "artifacts" / "SalesModel.SemanticModel"

    def _set_argv(self, repo_with_config: Path, artifact_relative: str) -> None:
        sys.argv = [
            "deploy.py",
            "--artifact",
            artifact_relative,
            "--environment",
            "dev",
        ]

    def _set_credentials(self, monkeypatch) -> None:
        monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "client-1")
        monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "secret-1")

    def test_main_deploys_with_mocked_api(
        self, repo_with_config: Path, monkeypatch
    ):
        """Main generates a config and invokes fabric_cicd.deploy_with_config."""
        artifact = self._artifact(repo_with_config)
        monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_with_config))
        self._set_credentials(monkeypatch)
        self._set_argv(repo_with_config, str(artifact.relative_to(repo_with_config)))

        mock_result = mock.MagicMock()
        mock_result.status.value = "completed"

        with mock.patch("fabric_ci_cd_dataops.scripts.deploy.deploy_with_config") as mock_deploy:
            mock_deploy.return_value = mock_result
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        mock_deploy.assert_called_once()
        _, kwargs = mock_deploy.call_args
        assert kwargs["environment"] == "dev"
        assert "token_credential" in kwargs

    def test_main_missing_credentials_exits(
        self, repo_with_config: Path, monkeypatch
    ):
        """Missing service principal credentials cause sys.exit(1)."""
        artifact = self._artifact(repo_with_config)
        monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_with_config))
        monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
        monkeypatch.delenv("FABRIC_SERVICE_PRINCIPAL_ID", raising=False)
        monkeypatch.delenv("FABRIC_SERVICE_PRINCIPAL_SECRET", raising=False)
        self._set_argv(repo_with_config, str(artifact.relative_to(repo_with_config)))

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_missing_artifact_exits(self, repo_with_config: Path, monkeypatch):
        """Missing artifact path causes sys.exit(1)."""
        monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_with_config))
        self._set_credentials(monkeypatch)
        self._set_argv(repo_with_config, ".fabric/artifacts/Missing.SemanticModel")
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_propagates_fabric_cicd_failure(
        self, repo_with_config: Path, monkeypatch
    ):
        """A failed fabric-cicd deployment result is propagated as exit 1."""
        artifact = self._artifact(repo_with_config)
        monkeypatch.setenv("GITHUB_WORKSPACE", str(repo_with_config))
        self._set_credentials(monkeypatch)
        self._set_argv(repo_with_config, str(artifact.relative_to(repo_with_config)))

        mock_result = mock.MagicMock()
        mock_result.status.value = "failed"

        with mock.patch("fabric_ci_cd_dataops.scripts.deploy.deploy_with_config") as mock_deploy:
            mock_deploy.return_value = mock_result
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
