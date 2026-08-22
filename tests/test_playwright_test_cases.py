"""Contract tests for Playwright test-case generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.config import PlaywrightValidationConfig
from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import (
    TestCase as PlaywrightTestCase,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import (
    generate_test_cases,
    write_test_cases,
)


@pytest.fixture
def base_config() -> PlaywrightValidationConfig:
    """Return a minimal config for test-case generation."""
    return PlaywrightValidationConfig(
        workspace_id="ws-1",
        report_id="rpt-1",
        report_name="SalesReport",
        dataset_id="ds-1",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
    )


def test_generate_single_case_when_no_pages_or_bookmarks(
    base_config: PlaywrightValidationConfig,
) -> None:
    """A config with no pages/bookmarks still emits one default case."""
    cases = generate_test_cases(base_config)

    assert len(cases) == 1
    assert cases[0] == PlaywrightTestCase(
        test_case="SalesReport_default-page_no-bookmark",
        report_name="SalesReport",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
    )


def test_generate_cartesian_product(base_config: PlaywrightValidationConfig) -> None:
    """Pages and bookmarks expand into a cartesian product."""
    config = PlaywrightValidationConfig(
        workspace_id=base_config.workspace_id,
        report_id=base_config.report_id,
        report_name=base_config.report_name,
        dataset_id=base_config.dataset_id,
        page_ids=["p1", "p2"],
        bookmark_ids=["b1"],
        user_name=base_config.user_name,
        role=base_config.role,
        use_rls=base_config.use_rls,
        cloud=base_config.cloud,
        client_id=base_config.client_id,
        client_secret=base_config.client_secret,
        tenant_id=base_config.tenant_id,
        timeout_seconds=base_config.timeout_seconds,
        headless=base_config.headless,
    )

    cases = generate_test_cases(config)

    assert len(cases) == 2
    assert cases[0].test_case == "SalesReport_p1_b1"
    assert cases[0].page_id == "p1"
    assert cases[0].page_name == "p1"
    assert cases[0].bookmark_id == "b1"
    assert cases[1].test_case == "SalesReport_p2_b1"


def test_write_test_cases_creates_csv_and_json(
    base_config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """write_test_cases emits both CSV and JSON artifacts."""
    cases = generate_test_cases(base_config)

    csv_path, json_path = write_test_cases(cases, tmp_path)

    assert csv_path.exists()
    assert json_path.exists()
    assert csv_path.read_text(encoding="utf-8").startswith("test_case,")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total"] == 1
    assert data["test_cases"][0]["report_name"] == "SalesReport"
