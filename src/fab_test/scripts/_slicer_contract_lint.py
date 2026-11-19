"""`fab-test pbir contract lint`: check slicer contracts without running them (Authoring Command Grammar epic).

Takes TARGET as `fab-test pbir` takes it. Given a report (a path, or a name
under --artifact-dir), it finds the contract that pairs with it by the report's
logicalId, or --contract FILE; given none, it checks every contract under
--artifact-dir, as the run checks every report. Each contract gets two checks:

- fab-test reads it as `fab-test pbir` will, calendar included, as of --as-of,
  and it pairs with a report
- pql-test, which ships with fab-test, validates it against ODCS and resolves
  its table and column names in the report's semantic model, when the model is
  in the folder (`definition.pbir`'s byPath)

A problem in a file, unreadable YAML included, is a finding: exit 1. Exit 2
means lint couldn't check (no report, no contract, a flag that belongs to the
run); 127, pql-test is missing. Lint writes nothing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, entry_points, version
from pathlib import Path
from typing import Any

import yaml

from ._scan import find_artifact_dirs, find_files_by_suffix
from ._slicer_calendar import CalendarError, resolve_contract, today
from ._slicer_contract import ContractError, load_contract
from ._slicer_contract_run import CONTRACT_SUFFIX, report_logical_id
from ._slicer_init_output import (
    InitError,
    add_input_flags,
    add_output_flags,
    find_report,
    level,
    pbir_refusal,
    print_payload,
)

_PQL_TEST = "pql-test"  # its console script, run with this interpreter so the version is the one fab-test pins
_PREFIX = "  ✗ fab-test pbir contract:"
_REPORT_PROPERTY = "fabTestReport"


def add_lint_parser(subs: argparse._SubParsersAction) -> None:
    lint = subs.add_parser("lint", help="Check contracts: each reads as `fab-test pbir` reads it, is valid ODCS, "
                                        "and names what the report's semantic model has")
    add_input_flags(lint)
    lint.add_argument("--contract", default=None, metavar="FILE",
                      help=f"Contract to check, instead of the *{CONTRACT_SUFFIX} that pairs with the report "
                           "by its logicalId")
    lint.add_argument("--as-of", default=None, dest="as_of", type=datetime.date.fromisoformat, metavar="YYYY-MM-DD",
                      help="Date calendar-driven slicer defaults resolve against [default: today]")
    add_output_flags(lint, refused=("--output-dir",), verbose="Also name the model and what each check covered",
                     quiet="Print one result line per contract: passed or failed, the problem count, the file")


def lint_main(args: argparse.Namespace) -> int:
    try:
        pairs = _targets(args)
    except InitError as exc:
        print(f"{_PREFIX} {exc}", file=sys.stderr)
        return 2
    pql_test = _pql_command()
    if pql_test is None:
        print(f"{_PREFIX} pql-test isn't installed, and lint needs it to check ODCS and names; it ships with "
              "fab-test: pip install cft-fab-test", file=sys.stderr)
        return 127
    root, as_of = Path(args.artifact_dir), args.as_of or today()
    results = [_lint(report, contract, as_of, pql_test, root) for report, contract in pairs]
    document: dict[str, Any] = {"ok": all(r["ok"] for r in results), "contracts": results}
    if document["ok"]:
        named = (args.target or args.artifact) and pairs[0][0]
        document["next"] = "fab-test pbir" + (f" {named.name.removesuffix('.Report')}" if named else "")
    verbose = level(args) == "verbose"
    print_payload(args, document, lambda d: _text(d, verbose), as_line=_lines)
    if level(args) == "summary" and args.output_format != "json":
        for problem in (p for r in results for p in r["problems"]):
            print(f"  {problem['source']}: {problem['message']}", file=sys.stderr)
    return 0 if document["ok"] else 1


def _targets(args: argparse.Namespace) -> list[tuple[Path | None, Path]]:
    """(report, contract) pairs to check; the report is None when no report under --artifact-dir pairs."""
    root, named = Path(args.artifact_dir), args.target or args.artifact
    refusal = pbir_refusal(args, Path(named).name if named else "REPORT", "lint")
    if refusal:
        raise InitError(refusal)
    if args.contract:
        contract = Path(args.contract)
        if not contract.is_file():
            raise InitError(f"--contract {contract}: no such file")
        return [(find_report(args) if named else _reports(root).get(_names(contract)), contract)]
    if named:
        report = find_report(args)
        return [(report, _paired(report, root))]
    contracts = sorted(path for path in find_files_by_suffix(root, CONTRACT_SUFFIX) if _ours(path))
    if not contracts:
        raise InitError(f"no slicer contract under {root}; build one with fab-test pbir contract init REPORT")
    reports = _reports(root)
    return [(reports.get(_names(path)), path) for path in contracts]


def _paired(report: Path, root: Path) -> Path:
    """The one contract under ``root`` naming ``report``'s logicalId; init's file name if it can't be read."""
    logical_id = report_logical_id(report)
    if not logical_id:
        raise InitError(f"{report}/.platform has no logicalId, so no contract can pair with it")
    beside = (report.parent / f"{report.name}{CONTRACT_SUFFIX}").resolve()
    found = sorted({path.resolve() for path in find_files_by_suffix(root, CONTRACT_SUFFIX)
                    if _names(path) == logical_id or (path.resolve() == beside and _names(path) is None)})
    if len(found) > 1:
        raise InitError(f"{len(found)} contracts pair with {report.name}: " + ", ".join(map(str, found))
                        + "; keep one, or pass --contract FILE")
    if not found:
        name = report.name.removesuffix(".Report")
        raise InitError(f"no contract pairs with {report.name} under {root}; build one with "
                        f"fab-test pbir contract init {name}, or pass --contract FILE")
    return found[0]


def _reports(root: Path) -> dict[str, Path]:
    return {report_logical_id(report): report for report in find_artifact_dirs(root, [".Report"])}


def _ours(path: Path) -> bool:
    """A contract fab-test reads: one naming a report, or one that can't be read but mentions fabTestReport."""
    try:
        return _names(path) is not None or _REPORT_PROPERTY in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _names(path: Path) -> str | None:
    """The report logicalId a contract names, or None when it can't be read."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    properties = document.get("customProperties") if isinstance(document, dict) else None
    for item in properties if isinstance(properties, list) else []:
        if isinstance(item, dict) and item.get("property") == _REPORT_PROPERTY:
            return item.get("value")
    return None


def _lint(report: Path | None, contract: Path, as_of: datetime.date, pql_test: list[str],
          root: Path) -> dict[str, Any]:
    model = _model(report) if report else None
    result: dict[str, Any] = {"report": str(report) if report else None, "contract": str(contract),
                              "model": str(model) if model else None, "as_of": as_of.isoformat()}
    try:
        yaml.safe_load(contract.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:  # one problem, not one per checker
        return {**result, "ok": False, "apiVersion": None, "rules": 0,
                "problems": [{"source": "fab-test", "message": f"not valid YAML: {exc}"}]}
    upstream = _pql_lint(pql_test, contract, model)
    unpaired = [] if report else [{"source": "fab-test", "message": f"pairs with no report under {root} "
                                                                    f"({_REPORT_PROPERTY}: {_names(contract)})"}]
    problems = [*unpaired, *_read_as_run(report, contract, as_of),
                *({"source": "pql-test", "message": m} for m in upstream.get("problems", []))]
    return {**result, "ok": not problems, "apiVersion": upstream.get("apiVersion"),
            "rules": upstream.get("rules", 0), "problems": problems}


def _read_as_run(report: Path | None, contract: Path, as_of: datetime.date) -> list[dict[str, str]]:
    try:
        parsed = load_contract(contract)
        resolve_contract(parsed, as_of)
    except (ContractError, CalendarError) as exc:
        lines = [line.strip() for line in str(exc).splitlines()[1:] or str(exc).splitlines()]
        return [{"source": "fab-test", "message": line} for line in lines if line]
    if report and parsed.report_logical_id != report_logical_id(report):
        return [{"source": "fab-test", "message": f"pairs with report {parsed.report_logical_id}, "
                                                  f"not {report.name} ({report_logical_id(report)})"}]
    return []


def _model(report: Path) -> Path | None:
    """The semantic model folder `definition.pbir` points at by path, when it is there."""
    try:
        reference = json.loads((report / "definition.pbir").read_text(encoding="utf-8-sig"))["datasetReference"]
        model = (report / reference["byPath"]["path"]).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return model if model.is_dir() else None


def _pql_command() -> list[str] | None:
    """pql-test's entry point, run by this interpreter; None when it isn't installed."""
    found = [e for e in entry_points(group="console_scripts") if e.name == _PQL_TEST]
    if not found:
        return None
    module, _, attr = found[0].value.partition(":")
    return [sys.executable, "-c", f"import sys; from {module} import {attr}; sys.exit({attr}())"]


def _pql_lint(pql_test: list[str], contract: Path, model: Path | None) -> dict[str, Any]:
    command = [*pql_test, "contract", "lint", str(contract), *([str(model)] if model else []), "--format", "json"]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    try:
        return json.loads(done.stdout)
    except ValueError:
        message = (done.stderr or done.stdout).strip() or f"exited {done.returncode} with no output"
        return {"problems": [f"couldn't lint: {message}"]}


def _names_checked(result: dict[str, Any]) -> str:
    if result["model"]:
        return f"names resolve in {Path(result['model']).name}"
    if result["report"]:
        return "names not checked: the report's semantic model isn't in this folder"
    return "names not checked: no report pairs with it"


def _block(result: dict[str, Any], verbose: bool) -> list[str]:
    if result["ok"]:
        valid = f"valid ODCS v{result['apiVersion']}, {result['rules']} rules"
        lines = [f"  ✓ {result['contract']}: {valid}, {_names_checked(result)}"]
    else:
        lines = [f"  ✗ {result['contract']}: {len(result['problems'])} problem(s)",
                 *(f"    {p['source']}: {p['message']}" for p in result["problems"])]
    if verbose:
        lines[1:1] = [f"    model: {result['model'] or 'not in this folder'}",
                      f"    fab-test: reads as fab-test pbir reads it, as of {result['as_of']}",
                      f"    pql-test {_pql_version()}: ODCS schema{', names' if result['model'] else ''}"]
    return lines


def _text(document: dict[str, Any], verbose: bool) -> str:
    lines = [line for result in document["contracts"] for line in _block(result, verbose)]
    return "\n".join([*lines, *([f"  Next: {document['next']}"] if document.get("next") else [])])


def _lines(document: dict[str, Any]) -> str:
    """-q's one line per contract, shaped like `fab-test pbir -q`'s `pbir passed e=0 w=0 PATH`."""
    return "\n".join(_line(result) for result in document["contracts"])


def _line(result: dict[str, Any]) -> str:
    outcome = "passed" if result["ok"] else "failed"
    return f"contract lint {outcome} problems={len(result['problems'])} {result['contract']}"


def _pql_version() -> str:
    try:
        return version(_PQL_TEST)
    except PackageNotFoundError:
        return "(version unknown)"
