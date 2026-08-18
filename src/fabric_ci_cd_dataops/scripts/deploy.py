#!/usr/bin/env python3
"""
Fabric Artifact Deployment Script

Wrapper for the Microsoft Fabric CI/CD Python deployment engine. Ensures compliance
with Constraint C2: Fabric CI/CD Python is the only deployment provider.

Usage:
    python scripts/deploy.py \
        --artifact <artifact_path> \
        --environment <environment_name> \
        [--workspace-id <workspace_id>] \
        [--terse]

The script reads `.github/metadata/environments.yml` to resolve the
environment-specific workspace, generates a fabric-cicd YAML config, and
invokes `fabric_cicd.deploy_with_config` with a service-principal credential.

Exit codes:
    0  Deployment succeeded
    1  Deployment failed or configuration error
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "Error: PyYAML is required. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from azure.identity import ClientSecretCredential
    from fabric_cicd import append_feature_flag, deploy_with_config
    from fabric_cicd._common._exceptions import InputError
except ImportError as exc:
    print(
        f"Error: fabric-cicd and azure-identity are required: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

from ._cli_utils import terse_print


def load_environments_config(repo_root: Path, terse: bool = False) -> dict[str, Any]:
    """Load the unified environment configuration file."""
    config_path = repo_root / ".github" / "metadata" / "environments.yml"
    if not config_path.exists():
        msg = f"environments.yml not found at {config_path}"
        terse_print(terse, "ERROR", "config_load", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    # Basic schema validation
    required_keys = ["defaults", "environments"]
    for key in required_keys:
        if key not in config:
            msg = f"environments.yml is missing required key '{key}'"
            terse_print(terse, "ERROR", "config_schema", msg)
            if not terse:
                print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(config["environments"], dict) or not config["environments"]:
        msg = "environments.yml must contain a non-empty 'environments' mapping"
        terse_print(terse, "ERROR", "config_schema", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    return config


def _artifact_item_name(artifact_path: Path) -> str:
    """Return the fabric-cicd item name from an artifact directory path."""
    name = artifact_path.name
    # fabric-cicd expects names like "SalesModel.SemanticModel".
    if name.endswith(".SemanticModel") or name.endswith(".Report"):
        return name
    return f"{name}.Item"


def _artifact_item_type(artifact_path: Path) -> str:
    """Return the fabric-cicd item type for an artifact directory path."""
    name = artifact_path.name
    if name.endswith(".SemanticModel"):
        return "SemanticModel"
    if name.endswith(".Report"):
        return "Report"
    if name.endswith(".Notebook"):
        return "Notebook"
    if name.endswith(".DataPipeline"):
        return "DataPipeline"
    if name.endswith(".Dataflow"):
        return "Dataflow"
    if name.endswith(".Eventhouse"):
        return "Eventhouse"
    if name.endswith(".Warehouse"):
        return "Warehouse"
    if name.endswith(".Lakehouse"):
        return "Lakehouse"
    if name.endswith(".Environment"):
        return "Environment"
    if name.endswith(".DataAgent"):
        return "DataAgent"
    return ""


def _known_artifact_suffix(name: str) -> str:
    """Return the artifact type suffix if ``name`` ends with a known extension."""
    for suffix in (
        ".SemanticModel",
        ".Report",
        ".Notebook",
        ".DataPipeline",
        ".Dataflow",
        ".Eventhouse",
        ".Warehouse",
        ".Lakehouse",
        ".Environment",
        ".DataAgent",
    ):
        if name.endswith(suffix):
            return suffix
    return ""


def _resolve_local_dependency(
    artifact_path: Path, repo_root: Path
) -> Path | None:
    """Return the local artifact path referenced by a Report's PBIR file.

    Only returns paths that resolve to a directory inside ``repo_root`` and end
    with a known artifact extension. This is intentionally generic so the cycle
    detector can handle future artifact-reference types beyond SemanticModel.
    """
    pbir_path = artifact_path / "definition.pbir"
    if not pbir_path.is_file():
        return None

    try:
        with open(pbir_path, encoding="utf-8") as f:
            pbir = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    by_path = pbir.get("datasetReference", {}).get("byPath", {}).get("path", "")
    if not by_path:
        return None

    referenced = (artifact_path / by_path).resolve()
    if not referenced.is_dir() or not _known_artifact_suffix(referenced.name):
        return None

    try:
        referenced.relative_to(repo_root)
    except ValueError:
        return None

    return referenced


def _collect_dependencies(
    artifact_path: Path, repo_root: Path
) -> list[dict[str, Any]]:
    """Collect local artifact dependencies required for a consistent deploy.

    Currently supports Reports that reference a sibling/local artifact via
    ``definition.pbir`` ``byPath``. Dependencies are used by the phased
    deployment planner, not by the per-artifact fabric-cicd invocation.
    """
    dependencies: list[dict[str, Any]] = []
    item_type = _artifact_item_type(artifact_path)
    if item_type != "Report":
        return dependencies

    referenced = _resolve_local_dependency(artifact_path, repo_root)
    if referenced is None:
        return dependencies

    dependencies.append(
        {
            "path": referenced,
            "name": referenced.name,
            "type": _artifact_item_type(referenced),
        }
    )
    return dependencies


def build_dependency_graph(
    changed_artifacts: list[dict[str, Any]], repo_root: Path
) -> dict[str, set[str]]:
    """Build a dependency graph mapping artifact name -> dependency names.

    The graph is used to compute deployment phases so dependencies are deployed
    before dependents. Cycles raise ``ValueError``.
    """
    name_to_path = {a["name"]: Path(a["path"]) for a in changed_artifacts}
    graph: dict[str, set[str]] = {name: set() for name in name_to_path}

    for name, path in name_to_path.items():
        for dep in _collect_dependencies(path, repo_root):
            dep_name = dep["name"]
            if dep_name in name_to_path:
                graph[name].add(dep_name)
            # If the dependency is not in the changed set, assume it is already
            # deployed in the workspace. Do not add it to the graph.

    # Detect cycles.
    visited: set[str] = set()
    stack: set[str] = set()

    def _visit(node: str) -> None:
        if node in stack:
            raise ValueError(f"Circular dependency detected involving {node}")
        if node in visited:
            return
        stack.add(node)
        for dep in graph.get(node, set()):
            _visit(dep)
        stack.remove(node)
        visited.add(node)

    for node in graph:
        _visit(node)

    return graph


def compute_deployment_phases(
    changed_artifacts: list[dict[str, Any]], repo_root: Path
) -> list[list[dict[str, Any]]]:
    """Group changed artifacts into deployment phases.

    Each phase contains artifacts whose dependencies are all in earlier phases.
    """
    graph = build_dependency_graph(changed_artifacts, repo_root)
    name_to_artifact = {a["name"]: a for a in changed_artifacts}

    in_degree = {name: len(deps) for name, deps in graph.items()}
    remaining = dict(in_degree)
    phases: list[list[dict[str, Any]]] = []

    while remaining:
        phase_names = [name for name, degree in remaining.items() if degree == 0]
        if not phase_names:
            # Should be unreachable because cycles are caught in build_dependency_graph.
            raise ValueError("Unable to resolve deployment phases")

        phase_names.sort()
        phases.append([name_to_artifact[name] for name in phase_names])

        for name in phase_names:
            del remaining[name]
            for dependent, deps in graph.items():
                if name in deps and dependent in remaining:
                    remaining[dependent] -= 1

    return phases


def build_environment_config(
    config: dict[str, Any],
    environment: str,
    workspace_id: str,
    artifact_path: Path,
    repo_root: Path,
    terse: bool = False,
) -> dict[str, Any]:
    """Build a fabric-cicd YAML config for the target artifact and environment.

    The per-artifact config deploys only the named artifact. Dependencies are
    guaranteed to be deployed in earlier phases by the orchestrator.
    """
    defaults = config.get("defaults", {})
    env_block = config.get("environments", {}).get(environment)

    if not env_block:
        msg = f"Environment '{environment}' not found in environments.yml"
        terse_print(terse, "ERROR", "config_environment", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    merged = dict(defaults)
    merged.update(env_block)

    # Allow CLI / environment override of workspace_id
    effective_workspace_id = workspace_id or merged.get("workspace_id", "")

    if not effective_workspace_id:
        msg = f"workspace_id is empty for environment '{environment}'"
        terse_print(terse, "ERROR", "config_workspace", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
            print(
                "Set it in environments.yml or pass --workspace-id / "
                "FABRIC_WORKSPACE_ID.",
                file=sys.stderr,
            )
        sys.exit(1)

    repository_directory = str(artifact_path.parent)
    item_type = _artifact_item_type(artifact_path)
    item_name = _artifact_item_name(artifact_path)

    item_types_in_scope = [item_type] if item_type else ["*"]

    fabric_cicd_config: dict[str, Any] = {
        "core": {
            "workspace_id": effective_workspace_id,
            "repository_directory": repository_directory,
            "item_types_in_scope": item_types_in_scope,
        },
        "publish": {
            "skip": False,
            "items_to_include": [item_name],
        },
        "unpublish": {
            "skip": True,
        },
    }

    return fabric_cicd_config


def _service_principal_credential() -> ClientSecretCredential | None:
    """Build a ClientSecretCredential from Fabric service principal env vars."""
    tenant_id = os.getenv("FABRIC_TENANT_ID")
    client_id = os.getenv("FABRIC_SERVICE_PRINCIPAL_ID")
    client_secret = os.getenv("FABRIC_SERVICE_PRINCIPAL_SECRET")

    if not tenant_id or not client_id or not client_secret:
        return None

    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def deploy_artifact(
    artifact_path: Path,
    environment: str,
    environment_config: dict[str, Any],
    repo_root: Path,
    terse: bool = False,
) -> int:
    """Deploy the artifact using the real Fabric CI/CD Python API."""
    workspace_id = environment_config["core"]["workspace_id"]

    if not terse:
        print("\n" + "=" * 80)
        print("FABRIC CI/CD PYTHON DEPLOYMENT")
        print("=" * 80)
        print(f"\n📦 Artifact:     {artifact_path}")
        print(f"🏢 Workspace ID: {workspace_id}")
        print(f"🌍 Environment:  {environment}")
        print("\n" + "-" * 80)
        print("CONSTRAINT C2: Fabric CI/CD Python is the only deployment provider")
        print("-" * 80)

    credential = _service_principal_credential()
    if credential is None:
        msg = (
            "Fabric service principal credentials are missing. Set "
            "FABRIC_TENANT_ID, FABRIC_SERVICE_PRINCIPAL_ID, and "
            "FABRIC_SERVICE_PRINCIPAL_SECRET."
        )
        terse_print(terse, "ERROR", "deploy_credentials", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yml",
        prefix="fabric-cicd-",
        dir=str(repo_root),
        delete=False,
    ) as tmp_config:
        yaml.safe_dump(
            environment_config,
            tmp_config,
            default_flow_style=False,
            sort_keys=False,
        )
        tmp_config_path = Path(tmp_config.name)

    try:
        if not terse:
            print(
                f"\n🔧 Deploying via fabric-cicd API with config: {tmp_config_path}\n"
            )

        append_feature_flag("enable_experimental_features")
        append_feature_flag("enable_items_to_include")
        result = deploy_with_config(
            config_file_path=str(tmp_config_path),
            token_credential=credential,
            environment=environment,
        )
        return 0 if result.status.value == "completed" else 1
    except InputError as exc:
        msg = f"Deployment configuration error: {exc}"
        terse_print(terse, "ERROR", "deploy_config", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - catch all Fabric API failures
        deployment_result = getattr(exc, "deployment_result", None)
        if deployment_result is not None:
            msg = f"Deployment failed: {deployment_result.message}"
        else:
            msg = f"Deployment failed: {exc}"
        terse_print(terse, "ERROR", "deploy", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        return 1
    finally:
        tmp_config_path.unlink(missing_ok=True)


def _print_plan(phases: list[list[dict[str, Any]]]) -> None:
    """Print deployment phases in a human-readable table."""
    print("\n" + "=" * 80)
    print("DEPLOYMENT PLAN")
    print("=" * 80)
    for idx, phase in enumerate(phases):
        print(f"\nPhase {idx}:")
        for artifact in phase:
            print(f"  - {artifact['name']} ({artifact['type']})")
    print("\n" + "=" * 80 + "\n")


def build_plan(
    changed_artifacts: list[dict[str, Any]], repo_root: Path
) -> list[dict[str, Any]]:
    """Build a JSON-serializable plan with phases and matrix metadata."""
    phases = compute_deployment_phases(changed_artifacts, repo_root)
    plan: list[dict[str, Any]] = []
    for idx, phase in enumerate(phases):
        plan.append(
            {
                "phase": idx,
                "artifacts": [
                    {
                        "name": a["name"],
                        "type": a["type"],
                        "path": a["path"],
                    }
                    for a in phase
                ],
            }
        )
    return plan


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Fabric artifact using Fabric CI/CD Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--artifact",
        help=(
            "Path to artifact directory "
            "(e.g., .fabric/artifacts/SalesModel.SemanticModel)"
        ),
    )
    parser.add_argument(
        "--environment",
        help="Target environment name (testbed, dev, test, prod)",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("FABRIC_WORKSPACE_ID", ""),
        help="Fabric workspace ID (optional if configured in environments.yml)",
    )
    parser.add_argument(
        "--workspace",
        default="",
        help="Deprecated alias for --workspace-id",
    )
    parser.add_argument(
        "--terse",
        action="store_true",
        help=(
            "Emit machine-readable one-line summaries (OK/FAIL prefix). "
            "Suppresses decorative output; retains actionable context for agents."
        ),
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help=(
            "Instead of deploying, read changed artifacts from stdin as JSON "
            "and emit a JSON deployment plan with ordered phases."
        ),
    )

    args = parser.parse_args()
    terse = args.terse
    repo_root = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()

    if args.plan:
        if args.environment is None:
            print("Error: --plan requires --environment", file=sys.stderr)
            sys.exit(1)
        try:
            changed_artifacts = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
            sys.exit(1)

        is_valid_input = (
            isinstance(changed_artifacts, dict)
            and "changed_artifacts" in changed_artifacts
        )
        if not is_valid_input:
            print(
                "Error: stdin JSON must be an object with a 'changed_artifacts' list",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            plan = build_plan(changed_artifacts["changed_artifacts"], repo_root)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        if terse:
            print(json.dumps(plan))
        else:
            phases = [
                [
                    {"name": a["name"], "type": a["type"], "path": a["path"]}
                    for a in p["artifacts"]
                ]
                for p in plan
            ]
            _print_plan(phases)
            print(json.dumps(plan, indent=2))
        sys.exit(0)

    if not args.artifact or not args.environment:
        parser.error("--artifact and --environment are required unless using --plan")

    artifact_path = (repo_root / args.artifact).resolve()

    if not artifact_path.exists():
        msg = f"Artifact path does not exist: {artifact_path}"
        terse_print(terse, "ERROR", "artifact_path", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    if not artifact_path.is_dir():
        msg = f"Artifact path must be a directory: {artifact_path}"
        terse_print(terse, "ERROR", "artifact_path", msg)
        if not terse:
            print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    workspace_id = args.workspace_id or args.workspace

    if not terse:
        print(f"Repository root: {repo_root}")
        print(f"Target artifact: {artifact_path}")

    config = load_environments_config(repo_root, terse)
    env_config = build_environment_config(
        config, args.environment, workspace_id, artifact_path, repo_root, terse
    )

    exit_code = deploy_artifact(
        artifact_path, args.environment, env_config, repo_root, terse
    )

    if terse:
        artifact_name = artifact_path.name
        if exit_code == 0:
            terse_print(
                terse, "OK", "deploy", f"{artifact_name} deployed to {args.environment}"
            )
        else:
            terse_print(
                terse,
                "FAIL",
                "deploy",
                f"{artifact_name} deployment failed (exit {exit_code})",
            )
    else:
        print("\n" + "=" * 80)
        if exit_code == 0:
            print("✅ DEPLOYMENT COMPLETED")
        else:
            print(f"❌ DEPLOYMENT FAILED (exit code {exit_code})")
        print("=" * 80 + "\n")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
