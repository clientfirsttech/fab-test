"""Test-case generation for Playwright visual validation.

Transforms a single static report target into one row per
``report x page x bookmark`` combination. If no pages or bookmarks are provided,
the cartesian product still emits a single record with empty dimensions so the
runner can skip or warn as appropriate.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import PlaywrightValidationConfig


def sanitize_case_id(test_case: str | None) -> str:
    """Return a filesystem/pytest-node-safe id for one test case.

    Shared by the pytest spec (which names the case's evidence directory)
    and ``invoke_playwright.py`` (which has to find that same directory
    afterwards to read it back) -- the two must agree on the exact
    sanitization or the wrapper looks in a directory the spec never wrote.
    """
    return re.sub(r"[^\w\-]", "_", test_case or "unknown").strip("_")


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
    render_wait_seconds: int = 20
    report_parameters: str = "[]"


def _default_page() -> tuple[str, str]:
    """Return the default page id/name for reports with no explicit pages."""
    return "", ""


def _default_bookmark() -> tuple[str, str]:
    """Return the default bookmark id/name for reports with no explicit bookmarks."""
    return "", ""


@dataclass(frozen=True)
class DiscoveredBookmark:
    """One bookmark, already known to belong to a specific page."""

    bookmark_id: str
    bookmark_name: str


@dataclass(frozen=True)
class DiscoveredPage:
    """One report page plus the bookmarks discovered to target it."""

    page_id: str
    page_name: str
    bookmarks: list[DiscoveredBookmark] = field(default_factory=list)


def _case_id(report_name: str, page_id: str, bookmark_id: str, role: str) -> str:
    """Build a test-case id that cannot collide across page/bookmark/role.

    Shared by the legacy cartesian path and the discovered-matrix path so
    both id shapes stay compatible; the ``role`` segment is omitted when
    empty so single-role runs keep today's id exactly.
    """
    return "_".join(
        part
        for part in [
            report_name,
            page_id or "default-page",
            bookmark_id or "no-bookmark",
            f"role-{role}" if role else "",
        ]
        if part
    )


def _effective_user(config: PlaywrightValidationConfig, role: str) -> str:
    """Return the effective-identity user this case should embed with.

    Only a case that carries a role does. An embed token minted for a model
    with no RLS and a non-empty identity is rejected outright by the Power BI
    API ("shouldn't have effective identity"), so carrying the configured
    user onto every case would break the reports that need it least.
    """
    return config.user_name if role else ""


def _build_case(
    config: PlaywrightValidationConfig,
    *,
    page_id: str,
    page_name: str,
    bookmark_id: str,
    bookmark_name: str,
    role: str,
) -> TestCase:
    """Build one ``TestCase`` for a page/bookmark/role combination."""
    return TestCase(
        test_case=_case_id(config.report_name, page_id, bookmark_id, role),
        report_name=config.report_name,
        report_id=config.report_id,
        workspace_id=config.workspace_id,
        page_id=page_id,
        page_name=page_name,
        bookmark_id=bookmark_id,
        bookmark_name=bookmark_name,
        dataset_id=config.dataset_id,
        user_name=_effective_user(config, role),
        role=role,
        report_type=getattr(config, "report_type", "report"),
        render_wait_seconds=getattr(config, "render_wait_seconds", 20),
    )


def _build_paginated_case(
    config: PlaywrightValidationConfig,
    parameter_set: list[dict[str, str]] | None = None,
) -> TestCase:
    """Build one paginated case: the baseline, or one holding ``parameter_set``.

    A paginated (RDL) report has no page/bookmark dimension, so unlike
    ``_build_case`` this never encodes ``"default-page"``/``"no-bookmark"``
    placeholders that only make sense for that matrix. A parameterized
    case's id carries its values so it can never collide with the
    baseline's, and ``report_parameters`` holds the set in the embed SDK's
    own ``parameterValues`` shape.
    """
    role = config.role
    params = "-".join(
        f"{entry['name']}-{entry['value']}" for entry in parameter_set or []
    )
    test_case = "_".join(
        part
        for part in [
            config.report_name,
            f"role-{role}" if role else "",
            f"params-{params}" if params else "",
        ]
        if part
    )
    return TestCase(
        test_case=test_case,
        report_name=config.report_name,
        report_id=config.report_id,
        workspace_id=config.workspace_id,
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id=config.dataset_id,
        user_name=_effective_user(config, role),
        role=role,
        report_type="paginated",
        render_wait_seconds=getattr(config, "render_wait_seconds", 20),
        report_parameters=json.dumps(parameter_set or []),
    )


def _generate_cartesian_cases(config: PlaywrightValidationConfig) -> list[TestCase]:
    """Cross every page id with every bookmark id under the one configured role.

    This is the legacy shape, used whenever the caller has not supplied a
    discovered page/bookmark matrix -- an explicit ``--page-ids`` or
    ``--bookmark-ids`` override, or a run with discovery disabled. Pages and
    bookmarks without an explicit name use the id as the name.
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
            cases.append(
                _build_case(
                    config,
                    page_id=page_id,
                    page_name=page_name,
                    bookmark_id=bookmark_id,
                    bookmark_name=bookmark_name,
                    role=config.role,
                )
            )
    return cases


def _generate_discovered_cases(
    config: PlaywrightValidationConfig,
    pages: list[DiscoveredPage],
    roles: list[str],
) -> list[TestCase]:
    """Emit one baseline case per page plus one case per page's own bookmark,
    repeated for each role -- never a page paired with another page's
    bookmark, and never one token asked to cover two roles.
    """
    cases: list[TestCase] = []
    for role in roles or [""]:
        for page in pages:
            cases.append(
                _build_case(
                    config,
                    page_id=page.page_id,
                    page_name=page.page_name,
                    bookmark_id="",
                    bookmark_name="",
                    role=role,
                )
            )
            cases.extend(
                _build_case(
                    config,
                    page_id=page.page_id,
                    page_name=page.page_name,
                    bookmark_id=bookmark.bookmark_id,
                    bookmark_name=bookmark.bookmark_name,
                    role=role,
                )
                for bookmark in page.bookmarks
            )
    return cases


def generate_test_cases(
    config: PlaywrightValidationConfig,
    *,
    pages: list[DiscoveredPage] | None = None,
    roles: list[str] | None = None,
    parameter_sets: list[list[dict[str, str]]] | None = None,
) -> list[TestCase]:
    """Expand a config into a list of ``TestCase`` records.

    Without ``pages``, crosses ``config.page_ids`` with ``config.bookmark_ids``
    (or a single empty dimension for either that is unset) under the one
    configured role -- the legacy shape, still used for an explicit
    ``--page-ids``/``--bookmark-ids`` override. With ``pages`` (a discovered
    matrix), each page's own bookmarks are used instead of every bookmark in
    the report, and the whole matrix repeats once per entry in ``roles``. A
    paginated report ignores ``pages``/``roles`` -- RDL reports have no
    page/bookmark matrix to expand -- and emits one baseline case plus one
    case per entry in ``parameter_sets``.
    """
    if getattr(config, "report_type", "report") == "paginated":
        return [_build_paginated_case(config)] + [
            _build_paginated_case(config, parameter_set)
            for parameter_set in parameter_sets or []
        ]
    if pages is not None:
        return _generate_discovered_cases(config, pages, roles or [config.role])
    return _generate_cartesian_cases(config)


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
        "render_wait_seconds",
        "report_parameters",
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
