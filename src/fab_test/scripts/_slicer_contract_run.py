"""Pair slicer contracts with reports for `fab-test pbir` (PBIR Slicer Default State epic).

Before any analyzer starts, every `*.odcs.yaml` under the artifact root that
carries `engine: fab-test` rules (and any `--contract FILE`) is read and its
calendar values resolved for `--as-of` (default: today), so a bad contract is
one exit-2 message rather than a failure mid-run. A report pairs with the
contract whose `fabTestReport` equals its `.platform` logicalId; an explicit
`--contract` applies to every report in the run, which is meant for a single
report target (a deployed report exported for `--workspace` has no logicalId
to pair on). The paired rules are appended to that report's own copy of the
PBIR ruleset, and a summary goes into its envelope.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ._results_stem import results_stem
from ._scan import find_files_by_suffix
from ._slicer_calendar import CalendarError, resolve_contract
from ._slicer_contract import ENGINE, ContractError, SlicerExpectation, load_contract
from ._slicer_rules import compile_rules

_ANALYZERS = ("pbir", "all", "local")
CONTRACT_SUFFIX = ".odcs.yaml"


@dataclass(frozen=True)
class ResolvedContract:
    path: Path
    report_logical_id: str
    as_of: datetime.date
    expectations: list[SlicerExpectation]


def add_contract_flags(parser: argparse.ArgumentParser) -> None:
    parser.epilog = ("Slicer defaults: a report pairs with the *.odcs.yaml beside it. "
                     "Build one with `fab-test pbir contract init REPORT` (see its --help).")
    parser.add_argument("--contract", default=None, metavar="FILE",
                        help="Slicer contract to check every report in the run against, "
                             f"instead of pairing each report with a *{CONTRACT_SUFFIX} by its logicalId")
    parser.add_argument("--as-of", default=None, dest="as_of", metavar="YYYY-MM-DD",
                        type=datetime.date.fromisoformat,
                        help="Date calendar-driven slicer defaults resolve against [default: today]")


def prepare_contracts(args: argparse.Namespace) -> int | None:
    """Read and resolve every contract the run will use, or return exit code 2."""
    args.slicer_contracts, args.explicit_contract = {}, None
    explaining = args.analyzer == "explain" and getattr(args, "analyzer_name", None) == "pbir"
    if args.analyzer not in _ANALYZERS and not explaining:
        return None
    as_of = getattr(args, "as_of", None) or datetime.datetime.now(datetime.UTC).astimezone().date()
    try:
        if getattr(args, "contract", None):
            args.explicit_contract = _resolve(Path(args.contract), as_of)
        for path in _contract_files(args):
            _pair(args.slicer_contracts, _resolve(path, as_of))
    except (ContractError, CalendarError) as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2
    return None


def _pair(paired: dict[str, ResolvedContract], contract: ResolvedContract) -> None:
    other = paired.get(contract.report_logical_id)
    if other:
        raise ContractError(f"{other.path} and {contract.path} both pair with report {contract.report_logical_id}")
    paired[contract.report_logical_id] = contract


def _contract_files(args: argparse.Namespace) -> list[Path]:
    root = Path(args.artifact_dir)
    excluded = [Path(args.output_dir)] if getattr(args, "output_dir", None) else []
    return [p for p in find_files_by_suffix(root, CONTRACT_SUFFIX, excluded_paths=excluded) if _has_slicer_rules(p)]


def _has_slicer_rules(path: Path) -> bool:
    """True for a contract fab-test should read: one carrying an engine: fab-test rule."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return True  # let load_contract report it
    tables = document.get("schema") if isinstance(document, dict) else None
    return any(
        isinstance(rule, dict) and str(rule.get("engine", "")).lower() == ENGINE
        for table in tables or [] if isinstance(table, dict)
        for column in table.get("properties") or [] if isinstance(column, dict)
        for rule in column.get("quality") or []
    )


def _resolve(path: Path, as_of: datetime.date) -> ResolvedContract:
    contract = load_contract(path)
    return ResolvedContract(path, contract.report_logical_id, as_of, resolve_contract(contract, as_of))


def report_logical_id(report: Path) -> str | None:
    try:
        return json.loads((report / ".platform").read_text(encoding="utf-8-sig"))["config"]["logicalId"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def apply_slicer_contract(report: Path, args: argparse.Namespace, output_dir: Path,
                          rules_path: Path) -> tuple[Path, Path | None]:
    """(rules file, contract summary file) for ``report``: unchanged when no contract pairs with it."""
    contract = getattr(args, "explicit_contract", None) or getattr(args, "slicer_contracts", {}).get(
        report_logical_id(report))
    if contract is None:
        return rules_path, None
    folder = output_dir / "pbir" / results_stem(report)
    folder.mkdir(parents=True, exist_ok=True)
    ruleset = json.loads(rules_path.read_text(encoding="utf-8-sig"))
    ruleset = {**ruleset, "rules": [*ruleset.get("rules", []), *compile_rules(contract.expectations)]}
    resolved = folder / "_resolved-rules.json"
    resolved.write_text(json.dumps(ruleset, indent=2), encoding="utf-8")
    summary = folder / "_contract.json"
    summary.write_text(json.dumps(_summary(contract), indent=2, default=str), encoding="utf-8")
    return resolved, summary


def _summary(contract: ResolvedContract) -> dict[str, Any]:
    return {
        "file": str(contract.path),
        "as_of": contract.as_of.isoformat(),
        "report_logical_id": contract.report_logical_id,
        "rules": [{"id": e.rule_id, "page": e.page, "field": f"'{e.table}'[{e.column}]", "check": e.check,
                   "expected": e.expected, "severity": e.severity} for e in contract.expectations],
    }

