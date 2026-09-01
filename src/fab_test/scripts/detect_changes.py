#!/usr/bin/env python3
"""
Fabric Artifact Change Detection

Detects changed artifacts by analyzing git diff output against
.fabric/artifacts directory and artifact-map.json metadata.

Outputs changed-artifacts.json containing:
- List of changed artifact paths
- Artifact types from metadata
- Changed files per artifact

Usage:
    python scripts/detect_changes.py [--terse]

Exit codes:
    0  Detection completed (whether or not changes were found)
    1  Error during detection
"""

import argparse
import json
import os
import sys
from pathlib import Path

from ._artifact_types import load_artifact_map as _load_artifact_map
from ._cli_utils import terse_print


def load_artifact_map(repo_root: Path) -> dict[str, str]:
    """Load artifact type mappings from metadata.

    Delegates to `_artifact_types`, which searches the metadata layers and
    falls back to the packaged copy. This module held its own loader that
    read `.github/metadata/` directly and exited 1 when the file was absent
    -- a fourth copy of a mapping Discover From CWD had already
    centralized, and the only one that could not answer outside a checkout.
    """
    return _load_artifact_map(repo_root)


def get_changed_files(repo_root: Path) -> list[str]:
    """Get list of changed files from git diff."""
    import subprocess

    try:
        # Try to get changes from last commit
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True
        )

        changed_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]

        # If no changes in last commit, try comparing with main/master
        if not changed_files:
            for branch in ["origin/main", "origin/master"]:
                try:
                    result = subprocess.run(
                        ["git", "diff", "--name-only", branch, "HEAD"],
                        cwd=repo_root,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    changed_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
                    if changed_files:
                        break
                except subprocess.CalledProcessError:
                    continue

    except subprocess.CalledProcessError as e:
        print(f"Error running git diff: {e}", file=sys.stderr)
        return []
    else:
        return changed_files


def detect_artifact_type(artifact_path: str, artifact_map: dict[str, str]) -> str:
    """Determine artifact type from path using artifact-map.json."""
    for extension, artifact_type in artifact_map.items():
        if artifact_path.endswith(extension):
            return artifact_type
    return "Unknown"


def group_changes_by_artifact(changed_files: list[str], artifact_map: dict[str, str]) -> dict:
    """Group changed files by their parent artifact."""
    artifacts_dir = Path(".fabric/artifacts")
    changed_artifacts = {}

    for file_path in changed_files:
        # Check if file is under .fabric/artifacts
        posix_path = file_path.replace("\\", "/")
        if not posix_path.startswith(str(artifacts_dir).replace("\\", "/")):
            continue

        # Extract artifact root path
        # Example: .fabric/artifacts/SalesModel.SemanticModel/definition/model.tmdl
        # -> .fabric/artifacts/SalesModel.SemanticModel
        parts = tuple(posix_path.split("/"))
        if len(parts) < 3:
            continue

        artifact_path = "/".join(parts[:3])
        artifact_name = parts[2]

        if artifact_path not in changed_artifacts:
            artifact_type = detect_artifact_type(artifact_name, artifact_map)
            changed_artifacts[artifact_path] = {
                "path": artifact_path,
                "name": artifact_name,
                "type": artifact_type,
                "changed_files": []
            }

        changed_artifacts[artifact_path]["changed_files"].append(file_path)

    return changed_artifacts


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Detect changed Fabric artifacts from git diff",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--terse",
        action="store_true",
        help=(
            "Emit machine-readable one-line summaries (OK/WARN prefix). "
            "Suppresses decorative output; retains actionable context for agents."
        ),
    )
    args = parser.parse_args()
    terse = args.terse

    repo_root = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()

    if not terse:
        print(f"Repository root: {repo_root}")
        print("Loading artifact map...")
    artifact_map = load_artifact_map(repo_root)

    if not terse:
        print("Detecting changed files...")
    changed_files = get_changed_files(repo_root)
    if not terse:
        print(f"Found {len(changed_files)} changed files")

    if not terse:
        print("Grouping changes by artifact...")
    changed_artifacts = group_changes_by_artifact(changed_files, artifact_map)

    # Build output structure
    output = {
        "changed_artifacts": list(changed_artifacts.values()),
        "total_artifacts": len(changed_artifacts),
        "total_files": len(changed_files)
    }

    # Write to changed-artifacts.json
    output_file = repo_root / "changed-artifacts.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    if terse:
        if changed_artifacts:
            names = ", ".join(a["name"] for a in changed_artifacts.values())
            terse_print(terse, "OK", "detect_changes", f"{len(changed_artifacts)} artifact(s) changed: {names}")
        else:
            terse_print(terse, "OK", "detect_changes", "no artifact changes detected")
    else:
        print(f"\n✅ Detected {len(changed_artifacts)} changed artifacts:")
        for artifact in changed_artifacts.values():
            print(f"  - {artifact['name']} ({artifact['type']}): {len(artifact['changed_files'])} files")

        print(f"\nOutput written to: {output_file}")

    # Set GitHub Actions output if running in CI
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.getenv("GITHUB_OUTPUT"), 'a') as f:
            # Output full JSON (compact single-line) so downstream workflows can parse it
            f.write(f"artifacts_changed={json.dumps(output, separators=(',', ':'))}\n")
            f.write(f"has_changes={'true' if changed_artifacts else 'false'}\n")


if __name__ == "__main__":
    main()
