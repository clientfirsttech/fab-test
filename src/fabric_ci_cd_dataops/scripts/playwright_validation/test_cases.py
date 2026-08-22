"""Test-case generation for Playwright visual validation.

Transforms a single static report target into one row per
``report x page x bookmark`` combination. If no pages or bookmarks are provided,
the cartesian product still emits a single record with empty dimensions so the
runner can skip or warn as appropriate.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import PlaywrightValidationConfig


@dataclass(frozen=True)
class TestCase:
    """One browser validation target."""

    test_case: str
    report_name: str
    report_id: str
    workspace_id: str
    page_id: str
    page_name: str
    bookmark_id: str
    bookmark_name: str
    dataset_id: str
    user_name: str
    role: str
    report_type: str = "report"


def _default_page() -> tuple[str, str]:
    """Return the default page id/name for reports with no explicit pages."""
    return "", ""


def _default_bookmark() -> tuple[str, str]:
    """Return the default bookmark id/name for reports with no explicit bookmarks."""
    return "", ""


def generate_test_cases(config: PlaywrightValidationConfig) -> list[TestCase]:
    """Expand a config into a list of ``TestCase`` records.

    Pages without an explicit name use the id as the name. Bookmarks without an
    explicit name use the id as the name. If ``page_ids`` is empty, a single empty
    page dimension is emitted. If ``bookmark_ids`` is empty, a single empty
    bookmark dimension is emitted.
    """
    pages = config.page_ids or [""]
    bookmarks = config.bookmark_ids or [""]

    cases: list[TestCase] = []
    for page in pages:
        page_id, page_name = (page, page) if page else _default_page()
        for bookmark in bookmarks:
            bookmark_id, bookmark_name = (
                (bookmark, bookmark) if bookmark else _default_bookmark()
            )
            case_id = "_".join(
                part
                for part in [
                    config.report_name,
                    page_id or "default-page",
                    bookmark_id or "no-bookmark",
                ]
                if part
            )
            cases.append(
                TestCase(
                    test_case=case_id,
                    report_name=config.report_name,
                    report_id=config.report_id,
                    workspace_id=config.workspace_id,
                    page_id=page_id,
                    page_name=page_name,
                    bookmark_id=bookmark_id,
                    bookmark_name=bookmark_name,
                    dataset_id=config.dataset_id,
                    user_name=config.user_name,
                    role=config.role,
                    report_type=getattr(config, "report_type", "report"),
                )
            )

    return cases


def _test_case_to_dict(case: TestCase) -> dict[str, Any]:
    """Convert a ``TestCase`` to a plain dictionary."""
    return asdict(case)


def write_test_cases(
    cases: list[TestCase],
    output_dir: Path,
    *,
    base_name: str = "test-cases",
) -> tuple[Path, Path]:
    """Write test cases as both CSV and JSON to ``output_dir``.

    Returns the paths ``(csv_path, json_path)``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{base_name}.csv"
    json_path = output_dir / f"{base_name}.json"

    fieldnames = [
        "test_case",
        "report_name",
        "report_id",
        "workspace_id",
        "page_id",
        "page_name",
        "bookmark_id",
        "bookmark_name",
        "dataset_id",
        "user_name",
        "role",
        "report_type",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            writer.writerow(_test_case_to_dict(case))

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "total": len(cases),
                "test_cases": [_test_case_to_dict(case) for case in cases],
            },
            fh,
            indent=2,
        )

    return csv_path, json_path
