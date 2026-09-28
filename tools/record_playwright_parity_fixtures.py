#!/usr/bin/env python3
"""Record the discovery responses behind the Playwright test-generation parity fixtures.

For each golden in ``tests/fixtures/playwright-parity/`` -- an interactive
report's CSV or a paginated report's ``Paginated*.json`` -- asks the live
Fabric/Power BI APIs what discovery would see for it (pages, page-scoped
bookmarks, and roles; or a paginated report's datasets, deployed ``.rdl``,
and each parameter's valid values), and writes the answers to
``recorded/<report-id>.json`` beside the CSV. ``tests/test_playwright_generation_parity.py``
replays those files so the parity assertion runs with no network.

Re-record after any change to the dev environment (a new page, a renamed
bookmark, a role added to a model)::

    python tools/record_playwright_parity_fixtures.py

Credentials come from the same ``.fab-test/.env`` search order the CLI uses.
Nothing secret is written: only the page/bookmark/role names already present
in the committed CSVs.

Deliberately outside ``src/``: maintainer tooling for refreshing committed
fixtures, never invoked by fab-test itself and never packaged into the wheel.
If the parity fixtures are ever deleted, delete this script with them -- they
are its only caller.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fab_test.scripts.playwright_validation.config import (  # noqa: E402
    load_config,
)
from fab_test.scripts.playwright_validation.fabric_service_client import (  # noqa: E402
    build_fabric_service_client,
)
from fab_test.scripts.playwright_validation.rdl_datasource import (  # noqa: E402
    parse_rdl_report_parameters_text,
)
from fab_test.scripts.playwright_validation.service_client import (  # noqa: E402
    FabricRestClient,
    FabricToken,
    ServiceClientError,
)

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "playwright-parity"


def _targets_from_goldens(fixture_dir: Path) -> list[dict[str, str]]:
    """Read one target per golden CSV.

    The CSV is the statement of which report to record -- its first row
    carries the workspace, report, and dataset ids, and whether the report's
    model is RLS-secured is visible as a non-empty ``role`` column.
    """
    targets = []
    for csv_path in sorted(fixture_dir.glob("*.csv")):
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise SystemExit(f"{csv_path.name}: no rows to read a target from")
        first = rows[0]
        targets.append(
            {
                "golden_csv": csv_path.name,
                "workspace_id": first["workspace_id"],
                "report_id": first["report_id"],
                "report_name": first["report_name"],
                "dataset_id": first["dataset_id"],
                "use_rls": any(row.get("role") for row in rows),
            }
        )
    return targets


def _record_one(client: FabricRestClient, target: dict[str, Any]) -> dict[str, Any]:
    """Call the three discovery APIs for one report.

    A failure is recorded as an ``errors`` entry rather than aborting the
    whole run: one report missing a grant should not cost the other five
    their refresh.
    """
    workspace_id = target["workspace_id"]
    report_id = target["report_id"]
    recorded: dict[str, Any] = dict(target)
    errors: dict[str, str] = {}

    try:
        recorded["pages"] = client.get_report_pages(workspace_id, report_id)
    except ServiceClientError as exc:
        recorded["pages"] = []
        errors["pages"] = str(exc)

    try:
        recorded["bookmarks"] = client.get_report_bookmarks(workspace_id, report_id)
    except ServiceClientError as exc:
        recorded["bookmarks"] = []
        errors["bookmarks"] = str(exc)

    if target["use_rls"]:
        try:
            recorded["roles"] = client.get_semantic_model_roles(
                workspace_id, target["dataset_id"]
            )
        except ServiceClientError as exc:
            recorded["roles"] = []
            errors["roles"] = str(exc)
    else:
        recorded["roles"] = []

    if errors:
        recorded["errors"] = errors
    return recorded


def _paginated_targets(fixture_dir: Path) -> list[dict[str, str]]:
    """Read one target per paginated golden (``Paginated*.json``, a list of cases)."""
    targets = []
    for json_path in sorted(fixture_dir.glob("Paginated*.json")):
        with open(json_path, encoding="utf-8-sig") as fh:
            cases = json.load(fh)
        first = cases[0]
        targets.append(
            {
                "golden_json": json_path.name,
                "workspace_id": first["workspace_id"],
                "report_id": first["report_id"],
                "report_name": first["report_name"],
            }
        )
    return targets


def _record_paginated(client: FabricRestClient, target: dict[str, Any]) -> dict[str, Any]:
    """Call the paginated discovery APIs for one report.

    The deployed ``.rdl`` is recorded whole so the replay runs the real
    parameter parser; each parameter's valid-values query is recorded by its
    own text, against the dataset the report's datasources name.
    """
    workspace_id, report_id = target["workspace_id"], target["report_id"]
    recorded: dict[str, Any] = dict(target)
    errors: dict[str, str] = {}
    try:
        recorded["dataset_ids"] = client.get_report_dataset_ids(workspace_id, report_id)
    except ServiceClientError as exc:
        recorded["dataset_ids"] = []
        errors["dataset_ids"] = str(exc)
    try:
        recorded["definition"] = client.get_paginated_report_definition(workspace_id, report_id)
    except ServiceClientError as exc:
        recorded["definition"] = ""
        errors["definition"] = str(exc)

    recorded["query_rows"] = {}
    dataset_id = (recorded["dataset_ids"] or [""])[0]
    for parameter in parse_rdl_report_parameters_text(recorded["definition"]):
        if not parameter.values_query or not dataset_id:
            continue
        try:
            recorded["query_rows"][parameter.values_query] = client.execute_dax_query(
                workspace_id, dataset_id, parameter.values_query
            )
        except ServiceClientError as exc:
            errors[f"query:{parameter.name}"] = str(exc)
    if errors:
        recorded["errors"] = errors
    return recorded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-dir",
        default=str(FIXTURE_DIR),
        help="Directory holding the golden CSVs, and where fixtures are written.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to the .env holding the service principal (default: the CLI search order).",
    )
    args = parser.parse_args(argv)

    fixture_dir = Path(args.fixture_dir).resolve()
    targets = _targets_from_goldens(fixture_dir)
    if not targets:
        raise SystemExit(f"No golden CSVs found under {fixture_dir}")

    config = load_config(env_file=args.env_file, required=False)
    missing = [
        name
        for name, value in {
            "FABRIC_TENANT_ID": config.tenant_id,
            "FABRIC_CLIENT_ID": config.client_id,
            "FABRIC_CLIENT_SECRET": config.client_secret,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(
            "Recording needs a service principal; missing: " + ", ".join(missing)
        )

    service_client = build_fabric_service_client(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        cloud=config.cloud,
    )
    client = FabricRestClient(
        FabricToken(access_token=service_client.access_token, cloud=config.cloud)
    )

    failures = 0
    for target in targets:
        recorded = _record_one(client, target)
        out_path = fixture_dir / "recorded" / f"{target['report_id']}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(recorded, fh, indent=2, sort_keys=True)
            fh.write("\n")
        summary = (
            f"{len(recorded['pages'])} page(s), "
            f"{len(recorded['bookmarks'])} bookmark(s), "
            f"{len(recorded['roles'])} role(s)"
        )
        if "errors" in recorded:
            failures += 1
            summary += f" -- ERRORS: {recorded['errors']}"
        print(f"{target['report_name']}: {summary} -> {out_path.name}")

    for target in _paginated_targets(fixture_dir):
        recorded = _record_paginated(client, target)
        out_path = fixture_dir / "recorded" / f"{target['report_id']}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(recorded, fh, indent=2, sort_keys=True)
            fh.write("\n")
        summary = (
            f"{len(recorded['dataset_ids'])} dataset(s), "
            f"{len(recorded['query_rows'])} valid-values quer(ies)"
        )
        if "errors" in recorded:
            failures += 1
            summary += f" -- ERRORS: {recorded['errors']}"
        print(f"{target['report_name']}: {summary} -> {out_path.name}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
