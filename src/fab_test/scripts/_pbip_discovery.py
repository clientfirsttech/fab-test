"""Discover .pbip projects wherever they live (Local Desktop First Run §1).

A .pbip project is a Power BI project file paired with a `.Report` folder
and a `.SemanticModel` folder. Unlike `fabric-artifacts` discovery, this
walks an arbitrary root recursively so a developer's `.pbip` is found no
matter where it lives in the repository.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ._scan import find_files_by_suffix


@dataclass
class PbipProject:
    """One discovered .pbip project and its resolved paired folders."""

    name: str
    pbip_path: Path
    report_path: Path | None
    semantic_model_path: Path | None

    @property
    def is_complete(self) -> bool:
        """Whether both paired folders were found."""
        return self.report_path is not None and self.semantic_model_path is not None


def discover_pbip_projects(root: Path) -> list[PbipProject]:
    """Find every *.pbip file under root and resolve its paired folders.

    Prunes the same directories `_scan.scan` prunes (`.venv`,
    `node_modules`, nested git checkouts, ...) instead of walking
    everything and filtering afterward -- a `.pbip` deserves the same
    "do not descend" treatment as a folder-suffix artifact.
    """
    return [_resolve_project(pbip_path) for pbip_path in find_files_by_suffix(root, ".pbip")]


def _resolve_project(pbip_path: Path) -> PbipProject:
    name = pbip_path.stem
    project_dir = pbip_path.parent
    report_path = _find_report_path(pbip_path, project_dir)
    semantic_model_path = _find_semantic_model_path(report_path, project_dir, name)
    return PbipProject(
        name=name,
        pbip_path=pbip_path,
        report_path=report_path,
        semantic_model_path=semantic_model_path,
    )


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _find_report_path(pbip_path: Path, project_dir: Path) -> Path | None:
    for artifact in _read_json(pbip_path).get("artifacts", []):
        report = artifact.get("report") or {}
        relpath = report.get("path")
        if relpath:
            candidate = (project_dir / relpath).resolve()
            if candidate.is_dir():
                return candidate
    fallback = project_dir / f"{pbip_path.stem}.Report"
    return fallback if fallback.is_dir() else None


def _find_semantic_model_path(
    report_path: Path | None, project_dir: Path, name: str
) -> Path | None:
    if report_path is not None:
        dataset_ref = _read_json(report_path / "definition.pbir").get("datasetReference", {})
        relpath = dataset_ref.get("byPath", {}).get("path")
        if relpath:
            candidate = (report_path / relpath).resolve()
            if candidate.is_dir():
                return candidate
    fallback = project_dir / f"{name}.SemanticModel"
    return fallback if fallback.is_dir() else None
