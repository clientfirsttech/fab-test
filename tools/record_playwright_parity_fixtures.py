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
from fab_test.scripts.playwright_validation.resolver import (  # noqa: E402
    resolve_workspace_id,
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


def _item_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("displayName") == name]
    if len(matches) != 1:
        visible = ", ".join(str(item.get("displayName", "")) for item in items)
        raise ValueError(
            f"Expected one deployed item named {name!r}, found {len(matches)}. "
            f"Visible: {visible or 'none'}"
        )
    return matches[0]


def rewrite_interactive_golden(
    rows: list[dict[str, str]], recorded: dict[str, Any]
) -> list[dict[str, str]]:
    """Rebind a golden's service-issued IDs while preserving its semantic cases."""
    page_ids = {page["page_name"]: page["page_id"] for page in recorded["pages"]}
    bookmark_ids = {
        bookmark["bookmark_name"]: bookmark["bookmark_id"]
        for bookmark in recorded["bookmarks"]
    }
    migrated = []
    for source in rows:
        row = dict(source)
        row["workspace_id"] = recorded["workspace_id"]
        row["report_id"] = recorded["report_id"]
        row["dataset_id"] = recorded["dataset_id"]
        page_name = row.get("page_name", "")
        if page_name not in page_ids:
            raise ValueError(f"Page {page_name!r} is missing from the new workspace report")
        row["page_id"] = page_ids[page_name]
        bookmark_name = row.get("bookmark_name", "")
        if bookmark_name:
            if bookmark_name not in bookmark_ids:
                raise ValueError(
                    f"Bookmark {bookmark_name!r} is missing from the new workspace report"
                )
            row["bookmark_id"] = bookmark_ids[bookmark_name]
        elif "bookmark_id" in row:
            row["bookmark_id"] = ""
        migrated.append(row)
    return migrated


def rewrite_paginated_golden(
    cases: list[dict[str, Any]], recorded: dict[str, Any]
) -> list[dict[str, Any]]:
    """Rebind a paginated golden to the new workspace and datasource IDs."""
    migrated = []
    for source in cases:
        case = dict(source)
        case["workspace_id"] = recorded["workspace_id"]
        case["report_id"] = recorded["report_id"]
        permissions = [
            dataset.get("xmlaPermissions", "ReadOnly")
            for dataset in case.get("dataset_ids", [])
        ]
        case["dataset_ids"] = [
            {
                "id": dataset_id,
                "xmlaPermissions": (
                    permissions[index] if index < len(permissions) else "ReadOnly"
                ),
            }
            for index, dataset_id in enumerate(recorded["dataset_ids"])
        ]
        migrated.append(case)
    return migrated


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
    parser.add_argument(
        "--workspace",
        help=(
            "Rebind every golden by report name to this workspace and rewrite its "
            "workspace/report/dataset/page/bookmark IDs."
        ),
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
    workspace_id = (
        resolve_workspace_id(service_client, args.workspace) if args.workspace else ""
    )
    reports = service_client.list_items(workspace_id, "Report") if workspace_id else []
    paginated = (
        service_client.list_items(workspace_id, "PaginatedReport") if workspace_id else []
    )

    failures = 0
    for target in targets:
        old_report_id = target["report_id"]
        if workspace_id:
            item = _item_by_name(reports, target["report_name"])
            target["workspace_id"] = workspace_id
            target["report_id"] = item["id"]
            target["dataset_id"] = service_client.get_report_dataset_id(
                workspace_id, item["id"]
            )
        recorded = _record_one(client, target)
        if workspace_id:
            golden_path = fixture_dir / target["golden_csv"]
            fieldnames, rows = _read_csv(golden_path)
            _write_csv(
                golden_path,
                fieldnames,
                rewrite_interactive_golden(rows, recorded),
            )
        out_path = fixture_dir / "recorded" / f"{target['report_id']}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(recorded, fh, indent=2, sort_keys=True)
            fh.write("\n")
        old_path = fixture_dir / "recorded" / f"{old_report_id}.json"
        if old_path != out_path and old_path.exists():
            old_path.unlink()
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
        old_report_id = target["report_id"]
        if workspace_id:
            item = _item_by_name(paginated, target["report_name"])
            target["workspace_id"] = workspace_id
            target["report_id"] = item["id"]
        recorded = _record_paginated(client, target)
        if workspace_id:
            golden_path = fixture_dir / target["golden_json"]
            cases = json.loads(golden_path.read_text(encoding="utf-8-sig"))
            golden_path.write_text(
                json.dumps(rewrite_paginated_golden(cases, recorded), indent=4) + "\n",
                encoding="utf-8",
            )
        out_path = fixture_dir / "recorded" / f"{target['report_id']}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(recorded, fh, indent=2, sort_keys=True)
            fh.write("\n")
        old_path = fixture_dir / "recorded" / f"{old_report_id}.json"
        if old_path != out_path and old_path.exists():
            old_path.unlink()
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
