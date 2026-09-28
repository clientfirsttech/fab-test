"""Parity between the matrix fab-test generates and the dev environment's golden CSVs.

The six CSVs under ``tests/fixtures/playwright-parity/`` were captured from the
registered dev workspace and state, per report, exactly which
``page x bookmark x role`` combinations `fab-test playwright` is expected to
test. Each has a ``recorded/<report-id>.json`` recorded by
``tools/record_playwright_parity_fixtures.py`` holding what the three discovery
APIs returned for it, so this runs with no network.

Comparison is on the unordered set of semantic keys -- the ``test_case`` id,
the columns fab-test emits beyond the golden set, and row order are all
ignored. Page and bookmark ids repeat across these reports (page
``5da315eb042003e41290`` is three different pages in three reports), so every
key is scoped by ``report_id``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.discovery import resolve_discovery
from fab_test.scripts.playwright_validation.test_cases import generate_test_cases

pytestmark = pytest.mark.playwright

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "playwright-parity"
#: Recorded API responses live apart from the goldens, so a ``*.json`` in
#: FIXTURE_DIR itself is always a golden (the paginated ones), never a recording.
RECORDED_DIR = FIXTURE_DIR / "recorded"

#: The fields a generated case and a golden row must agree on. Everything
#: else fab-test emits (the ``test_case`` id, ``report_type``,
#: ``render_wait_seconds``, ``report_parameters``) is outside the contract
#: these CSVs state.
PARITY_FIELDS = (
    "workspace_id",
    "report_id",
    "report_name",
    "page_id",
    "page_name",
    "dataset_id",
    "bookmark_id",
    "bookmark_name",
    "role",
    "user_name",
)

GOLDEN_CSVS = sorted(FIXTURE_DIR.glob("*.csv"))


class _ReplayClient:
    """Answers the three discovery calls from a recorded fixture.

    Stands in for ``FabricRestClient`` so ``resolve_discovery``'s own
    page/bookmark pairing runs for real -- a fake that returned
    ``DiscoveredPage`` objects directly would skip the mapping most likely
    to break.
    """

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._fixture = fixture

    def get_report_pages(self, workspace_id: str, report_id: str) -> list[dict[str, str]]:
        return list(self._fixture["pages"])

    def get_report_bookmarks(
        self, workspace_id: str, report_id: str
    ) -> list[dict[str, str]]:
        return list(self._fixture["bookmarks"])

    def get_semantic_model_roles(
        self, workspace_id: str, semantic_model_id: str
    ) -> list[str]:
        return list(self._fixture["roles"])


def _golden_keys(csv_path: Path) -> set[tuple[str, ...]]:
    """Read one golden CSV as a set of parity keys.

    A column the CSV omits entirely (``role`` and ``user_name`` are absent
    from the four non-RLS files) reads as empty for every row rather than
    dropping out of the comparison -- "fab-test must emit nothing here" is
    exactly what their absence asserts.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return {tuple((row.get(field) or "") for field in PARITY_FIELDS) for row in rows}


def _config_for(fixture: dict[str, Any]) -> PlaywrightValidationConfig:
    """Build the config the CLI would hold for this report."""
    return PlaywrightValidationConfig(
        workspace_id=fixture["workspace_id"],
        report_id=fixture["report_id"],
        report_name=fixture["report_name"],
        dataset_id=fixture["dataset_id"],
        page_ids=[],
        bookmark_ids=[],
        # Always configured, even for the four reports whose golden CSV has
        # no user_name column: those CSVs assert the generator blanks it on a
        # role-less case, which only means something when one was available
        # to emit.
        user_name=fixture["user_name"] or "configured@example.com",
        role="",
        use_rls=fixture["use_rls"],
        cloud="public",
        client_id="client-id",
        client_secret="client-secret",
        tenant_id="tenant-id",
        timeout_seconds=180,
        headless=True,
        report_type="report",
    )


def _generated_keys(fixture: dict[str, Any]) -> set[tuple[str, ...]]:
    """Run discovery and generation against the recorded responses."""
    config = _config_for(fixture)
    args = type("Args", (), {"pages": "auto", "roles": "auto"})()

    with (
        patch(
            "fab_test.scripts.playwright_validation.discovery.build_fabric_service_client"
        ) as build_client,
        patch(
            "fab_test.scripts.playwright_validation.discovery.FabricRestClient",
            return_value=_ReplayClient(fixture),
        ),
    ):
        build_client.return_value.access_token = "token"
        pages, roles = resolve_discovery(config, args)

    cases = generate_test_cases(config, pages=pages, roles=roles)
    return {
        tuple(getattr(case, field) for field in PARITY_FIELDS) for case in cases
    }


def _describe(keys: set[tuple[str, ...]]) -> str:
    """Render parity keys as readable ``page/bookmark/role`` lines."""
    return "\n".join(
        sorted(
            f"    page={key[4] or '-'} bookmark={key[7] or '-'} role={key[8] or '-'} "
            f"user={key[9] or '-'}"
            for key in keys
        )
    )


def _fixture_for(csv_path: Path) -> dict[str, Any]:
    """Load the recorded discovery responses for a golden CSV's report."""
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    report_id = rows[0]["report_id"]
    fixture_path = RECORDED_DIR / f"{report_id}.json"
    assert fixture_path.exists(), (
        f"{csv_path.name} has no recorded fixture at {fixture_path.name}; "
        "run tools/record_playwright_parity_fixtures.py"
    )
    with open(fixture_path, encoding="utf-8") as fh:
        fixture = json.load(fh)
    fixture["user_name"] = next(
        (row["user_name"] for row in rows if row.get("user_name")), ""
    )
    return fixture


def test_every_golden_csv_has_a_recorded_fixture() -> None:
    """Given a golden CSV added with no recorded discovery responses,
    should fail rather than quietly testing one report fewer."""
    assert GOLDEN_CSVS, f"No golden CSVs found under {FIXTURE_DIR}"
    for csv_path in GOLDEN_CSVS:
        _fixture_for(csv_path)


@pytest.mark.parametrize("csv_path", GOLDEN_CSVS, ids=lambda p: p.stem)
def test_generated_matrix_matches_the_golden_csv(csv_path: Path) -> None:
    """Given a report in the dev environment, should generate exactly the
    page/bookmark/role combinations its golden CSV lists -- no more, no
    fewer, whatever order they come out in."""
    fixture = _fixture_for(csv_path)
    expected = _golden_keys(csv_path)
    actual = _generated_keys(fixture)

    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"{csv_path.stem}: generated matrix differs from the golden CSV\n"
        f"  missing ({len(missing)}):\n{_describe(missing)}\n"
        f"  unexpected ({len(extra)}):\n{_describe(extra)}"
    )


# --- Paginated (RDL) reports --------------------------------------------------

PAGINATED_GOLDENS = sorted(FIXTURE_DIR.glob("Paginated*.json"))


class _PaginatedReplayClient:
    """Answers the paginated discovery calls from a recorded fixture, so the
    real ``.rdl`` parser and value-picking in ``resolve_paginated_plan`` run."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._fixture = fixture

    def get_report_dataset_ids(self, workspace_id: str, report_id: str) -> list[str]:
        return list(self._fixture["dataset_ids"])

    def get_paginated_report_definition(self, workspace_id: str, report_id: str) -> str:
        return self._fixture["definition"]

    def execute_dax_query(
        self, workspace_id: str, dataset_id: str, query: str
    ) -> list[dict[str, Any]]:
        return list(self._fixture["query_rows"].get(query, []))


def _paginated_key(
    workspace_id: str,
    report_id: str,
    report_name: str,
    dataset_ids: list[str],
    parameters: list[dict[str, str]],
) -> tuple:
    """One paginated case's identity: its report, datasets, and parameter
    multiset. ``test_case``, ``xmlaPermissions`` and ``wait_seconds`` are
    outside the contract."""
    return (
        workspace_id,
        report_id,
        report_name,
        tuple(sorted(dataset_ids)),
        tuple(sorted((entry["name"], str(entry["value"])) for entry in parameters)),
    )


def _paginated_golden_keys(json_path: Path) -> set[tuple]:
    with open(json_path, encoding="utf-8-sig") as fh:
        cases = json.load(fh)
    return {
        _paginated_key(
            case["workspace_id"],
            case["report_id"],
            case["report_name"],
            [dataset["id"] for dataset in case["dataset_ids"]],
            case.get("report_parameters") or [],
        )
        for case in cases
    }


def _paginated_generated_keys(fixture: dict[str, Any]) -> set[tuple]:
    """Plan and generate a paginated report as a remote-only run would: no
    local .rdl, so the dataset and parameters come from the service."""
    from fab_test.scripts.playwright_validation.discovery import resolve_paginated_plan

    config = _config_for(
        {**fixture, "dataset_id": "", "use_rls": False, "user_name": ""}
    )
    config = type(config)(**{**config.__dict__, "report_type": "paginated"})

    with (
        patch(
            "fab_test.scripts.playwright_validation.discovery.build_fabric_service_client"
        ) as build_client,
        patch(
            "fab_test.scripts.playwright_validation.discovery.FabricRestClient",
            return_value=_PaginatedReplayClient(fixture),
        ),
    ):
        build_client.return_value.access_token = "token"
        plan = resolve_paginated_plan(config)

    config = type(config)(**{**config.__dict__, "dataset_id": plan.dataset_id})
    cases = generate_test_cases(config, parameter_sets=plan.parameter_sets)
    return {
        _paginated_key(
            case.workspace_id,
            case.report_id,
            case.report_name,
            [case.dataset_id] if case.dataset_id else [],
            json.loads(case.report_parameters),
        )
        for case in cases
    }


def _paginated_fixture_for(json_path: Path) -> dict[str, Any]:
    with open(json_path, encoding="utf-8-sig") as fh:
        report_id = json.load(fh)[0]["report_id"]
    fixture_path = RECORDED_DIR / f"{report_id}.json"
    assert fixture_path.exists(), (
        f"{json_path.name} has no recorded fixture at recorded/{fixture_path.name}; "
        "run tools/record_playwright_parity_fixtures.py"
    )
    with open(fixture_path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("json_path", PAGINATED_GOLDENS, ids=lambda p: p.stem)
def test_generated_paginated_cases_match_the_golden(json_path: Path) -> None:
    """Given a paginated report in the dev environment, should generate its
    baseline case plus one case per parameter set the golden lists -- with
    the dataset GenerateToken needs, found without a local .rdl."""
    expected = _paginated_golden_keys(json_path)
    actual = _paginated_generated_keys(_paginated_fixture_for(json_path))

    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"{json_path.stem}: generated paginated cases differ from the golden\n"
        f"  missing: {sorted(missing)}\n  unexpected: {sorted(extra)}"
    )
