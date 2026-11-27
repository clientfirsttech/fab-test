"""Tests for migrating Playwright parity goldens between live workspaces."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.playwright

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "tools" / "record_playwright_parity_fixtures.py"
_SPEC = importlib.util.spec_from_file_location("record_playwright_parity_fixtures", _SCRIPT)
assert _SPEC and _SPEC.loader
recorder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(recorder)


def test_rewrites_interactive_golden_ids_by_display_name():
    rows = [
        {
            "workspace_id": "old-workspace",
            "report_id": "old-report",
            "report_name": "Sales",
            "page_id": "old-page",
            "page_name": "Overview",
            "dataset_id": "old-dataset",
            "bookmark_id": "old-bookmark",
            "bookmark_name": "West",
            "expected_status": "pass",
        }
    ]
    recorded = {
        "workspace_id": "new-workspace",
        "report_id": "new-report",
        "dataset_id": "new-dataset",
        "pages": [{"page_id": "new-page", "page_name": "Overview"}],
        "bookmarks": [
            {"bookmark_id": "new-bookmark", "bookmark_name": "West", "page_id": "new-page"}
        ],
    }

    migrated = recorder.rewrite_interactive_golden(rows, recorded)

    assert migrated == [
        {
            **rows[0],
            "workspace_id": "new-workspace",
            "report_id": "new-report",
            "dataset_id": "new-dataset",
            "page_id": "new-page",
            "bookmark_id": "new-bookmark",
        }
    ]


def test_rewrites_paginated_golden_workspace_report_and_dataset_ids():
    cases = [
        {
            "workspace_id": "old-workspace",
            "report_id": "old-report",
            "report_name": "Paged",
            "dataset_ids": [{"id": "old-dataset", "xmlaPermissions": "ReadOnly"}],
        }
    ]
    recorded = {
        "workspace_id": "new-workspace",
        "report_id": "new-report",
        "dataset_ids": ["new-dataset"],
    }

    migrated = recorder.rewrite_paginated_golden(cases, recorded)

    assert migrated[0]["workspace_id"] == "new-workspace"
    assert migrated[0]["report_id"] == "new-report"
    assert migrated[0]["dataset_ids"] == [
        {"id": "new-dataset", "xmlaPermissions": "ReadOnly"}
    ]


def test_refuses_a_page_name_missing_from_the_new_workspace():
    rows = [{"page_name": "Missing", "bookmark_name": "", "expected_status": "pass"}]

    with pytest.raises(ValueError, match="Missing"):
        recorder.rewrite_interactive_golden(rows, {
            "workspace_id": "new-workspace",
            "report_id": "new-report",
            "dataset_id": "new-dataset",
            "pages": [],
            "bookmarks": [],
        })
