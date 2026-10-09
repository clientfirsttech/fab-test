"""Build an impacted-report manifest from changed artifacts.

Consumes the ``changed-artifacts.json`` produced by ``scripts/detect_changes.py``
and resolves each changed SemanticModel/Report into the set of deployed reports
that must be visually validated.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .resolver import (
    ItemNotFoundError,
    ResolvedReport,
    ServiceClient,
    resolve_environment,
    resolve_report,
    resolve_semantic_model_dependents,
)


@dataclass(frozen=True)
class ImpactEntry:
    """One report to validate plus the reasons it was impacted."""

    workspace_id: str
    report_id: str
    report_name: str
    semantic_model_id: str
    environment: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {**asdict(self)}


class ImpactManifest:
    """Collection of unique impacted reports with deduplicated reasons."""

    def __init__(self) -> None:
        self._reports: dict[tuple[str, str], ImpactEntry] = {}
        self._skipped: list[str] = []

    def add_report(
        self,
        report: ResolvedReport,
        reason: str,
    ) -> None:
        """Add or merge a report into the manifest."""
        key = (report.workspace_id, report.report_id)
        if key in self._reports:
            existing = self._reports[key]
            if reason not in existing.reasons:
                self._reports[key] = ImpactEntry(
                    workspace_id=existing.workspace_id,
                    report_id=existing.report_id,
                    report_name=existing.report_name,
                    semantic_model_id=existing.semantic_model_id,
                    environment=existing.environment,
                    reasons=[*existing.reasons, reason],
                )
        else:
            self._reports[key] = ImpactEntry(
                workspace_id=report.workspace_id,
                report_id=report.report_id,
                report_name=report.report_name,
                semantic_model_id=report.semantic_model_id,
                environment=report.environment,
                reasons=[reason],
            )

    def skip_artifact(self, name: str, artifact_type: str, reason: str = "no Playwright impact") -> None:
        """Record an artifact that adds no report to validate, and why."""
        self._skipped.append(f"{name} ({artifact_type}): {reason}")

    @property
    def reports(self) -> list[ImpactEntry]:
        """Return impacted reports in stable order."""
        return [entry for _, entry in sorted(self._reports.items())]

    @property
    def skipped(self) -> list[str]:
        """Return skipped artifact descriptions."""
        return self._skipped

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest as a JSON-serializable dictionary."""
        return {
            "total": len(self._reports),
            "skipped": self._skipped,
            "reports": [report.to_dict() for report in self.reports],
        }

    def write(self, path: Path) -> None:
        """Write the manifest to ``path`` as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)


def load_changed_artifacts(path: Path) -> list[dict[str, Any]]:
    """Load changed artifacts from the detect_changes JSON output."""
    if not path.exists():
        raise FileNotFoundError(f"Changed-artifacts file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    artifacts = data.get("changed_artifacts", data if isinstance(data, list) else [])
    if not isinstance(artifacts, list):
        raise TypeError("changed-artifacts data must contain a list of artifacts")
    return artifacts


def build_impact_manifest(
    artifacts: list[dict[str, Any]],
    environment: str,
    client: ServiceClient,
    *,
    env_path: Path | None = None,
    workspace_id_override: str = "",
    allowed_workspace_ids: set[str] | None = None,
) -> ImpactManifest:
    """Build an impacted-report manifest from changed artifacts.

    Args:
        artifacts: Changed artifacts, each with a ``name`` and ``type``
            (``detect_changes.changed_artifacts_since`` or ``load_changed_artifacts``).
        environment: Target environment label.
        client: Service client for item/dependency lookups.
        env_path: Optional path to environments.yml.
        workspace_id_override: Optional explicit workspace ID override.
        allowed_workspace_ids: Optional set of workspace IDs to include
            cross-workspace dependencies.

    Returns:
        ``ImpactManifest`` containing deduplicated impacted reports.
    """
    resolved_env = resolve_environment(
        environment,
        env_path=env_path,
        workspace_id_override=workspace_id_override,
    )
    scope = allowed_workspace_ids or {resolved_env.workspace_id}

    manifest = ImpactManifest()

    for artifact in artifacts:
        name = artifact.get("name", "")
        artifact_type = artifact.get("type", "")

        # A changed artifact with no deployed item is usually new and not yet
        # published: nothing deployed to validate, so note it and go on.
        try:
            if artifact_type == "SemanticModel":
                for report in resolve_semantic_model_dependents(
                    name,
                    resolved_env,
                    client,
                    allowed_workspace_ids=scope,
                ):
                    manifest.add_report(report, f"depends on {name}")
            elif artifact_type == "Report":
                report = resolve_report(name, resolved_env, client)
                manifest.add_report(report, f"changed report {name}")
            else:
                manifest.skip_artifact(name, artifact_type)
        except ItemNotFoundError:
            manifest.skip_artifact(name, artifact_type, "not deployed in the workspace")

    return manifest
