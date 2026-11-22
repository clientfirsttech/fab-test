"""`fab-test pbir contract lint`: check slicer contracts without running them (Authoring Command Grammar epic).

Takes TARGET as `fab-test pbir` takes it. Given a report (a path, or a name
under --artifact-dir), it finds the contract that pairs with it by the report's
logicalId, or --contract FILE; given none, it checks every contract under
--artifact-dir, as the run checks every report. It finds contracts the way the
run does (`contract_files`), plus init's own file beside a named report even
when that file can't be read. Each contract gets two checks:

- fab-test reads it as `fab-test pbir` will, calendar included, as of --as-of,
  and it pairs with exactly one report (the one beside it when several share
  a logicalId)
- pql-test, which ships with fab-test, validates it against ODCS and resolves
  its table and column names in the report's semantic model, when the model is
  in the folder (`definition.pbir`'s byPath)

A problem in a file, unreadable YAML included, is a finding: exit 1. Exit 2
means lint couldn't check (no report, no contract, a flag that belongs to the
run); 127, pql-test is missing; 130, interrupted. Lint writes nothing.
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

from ._authoring_output import add_input_flags, level, next_command, print_payload
from ._scan import find_artifact_dirs
from ._slicer_calendar import CalendarError, resolve_contract, today
from ._slicer_contract import ContractError, load_contract
from ._slicer_contract_run import AS_OF_HELP, CONTRACT_FILE_HELP, CONTRACT_SUFFIX, contract_files, report_logical_id
from ._slicer_init_output import (
    TARGET_HELP,
    InitError,
    add_output_flags,
    find_report,
    pbir_refusal,
)
from ._tests_dir import search_roots

_PQL_TEST = "pql-test"  # its console script, run with this interpreter so the version is the one fab-test pins
_PREFIX = "  ✗ fab-test pbir contract:"
_REPORT_PROPERTY = "fabTestReport"

Target = tuple[Path | None, Path, str | None]  # (report, contract, why no report pairs)


def add_lint_parser(subs: Any) -> None:
    lint = subs.add_parser("lint", help="Check contracts: each reads as `fab-test pbir` reads it, is valid ODCS, "
                                        "and names what the report's semantic model has")
    add_input_flags(lint, f"Report whose contract to check: {TARGET_HELP}; none checks every contract there")
    lint.add_argument("--contract", default=None, metavar="FILE", help=CONTRACT_FILE_HELP)
    lint.add_argument("--as-of", default=None, dest="as_of", type=datetime.date.fromisoformat, metavar="YYYY-MM-DD",
                      help=AS_OF_HELP)
    add_output_flags(lint, refused=("--output-dir",), verbose="Also name the model and what each check covered",
                     quiet="Print one result line per contract: passed or failed, the problem count, the file")


def lint_main(args: argparse.Namespace) -> int:
    try:
        return _lint_all(args)
    except InitError as exc:
        print(f"{_PREFIX} {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"\n{_PREFIX} interrupted; lint writes nothing, so nothing was left half done", file=sys.stderr)
        return 130


def _lint_all(args: argparse.Namespace) -> int:
    targets = _targets(args)
    pql_test = _pql_command()
    if pql_test is None:
        print(f"{_PREFIX} pql-test isn't installed, and lint needs it to check ODCS and names; it ships with "
              "fab-test: pip install cft-fab-test", file=sys.stderr)
        return 127
    as_of = args.as_of or today()
    results = [_lint(report, contract, as_of, pql_test, unpaired) for report, contract, unpaired in targets]
    ok = all(r["ok"] for r in results)
    document = {"ok": ok, "contracts": results, "next": next_command(args, "fab-test pbir") if ok else None}
    verbose = level(args) == "verbose"
    print_payload(args, document, lambda d: _text(d, verbose), as_line=_lines)
    if level(args) == "summary" and args.output_format != "json":
        for result in results:
            for problem in result["problems"]:
                print(f"  {result['contract']}: {problem['source']}: {problem['message']}", file=sys.stderr)
    return 0 if ok else 1


def _targets(args: argparse.Namespace) -> list[Target]:
    root, named = Path(args.artifact_dir), args.target or args.artifact
    refusal = pbir_refusal(args, Path(named).name if named else "REPORT", "lint")
    if refusal:
        raise InitError(refusal)
    if args.contract:
        contract = Path(args.contract)
        if not contract.is_file():
            raise InitError(f"--contract {contract}: no such file")
        return [(find_report(args), contract, None) if named else _pair(contract, root)]
    roots = search_roots(args)
    if named:
        report = find_report(args)
        return [(report, paired_contract(report, search_roots(args, report)), None)]
    contracts = contract_files(roots)
    if not contracts:
        raise InitError(f"no slicer contract under --artifact-dir {root} or fab-tests/; build one with "
                        "fab-test pbir contract init REPORT")
    return [_pair(contract, root) for contract in contracts]


def paired_contract(report: Path, roots: list[Path], *, required: bool = True) -> Path | None:
    """The one contract under ``roots`` naming ``report``'s logicalId; init's file beside it if it can't be read.

    ``required=False`` (contract init) returns None when none pairs yet, instead of refusing.
    """
    logical_id = report_logical_id(report)
    if not logical_id:
        raise InitError(f"{report}/.platform has no logicalId, so no contract can pair with it")
    beside = report.parent / f"{report.name}{CONTRACT_SUFFIX}"
    candidates = {path.resolve() for path in contract_files(roots) if _names(path) == logical_id}
    if not candidates and beside.is_file() and _names(beside) is None:
        candidates = {beside.resolve()}  # init's own file, unreadable: lint says why
    if len(candidates) > 1:
        raise InitError(f"{len(candidates)} contracts pair with {report.name}: "
                        + ", ".join(map(str, sorted(candidates))) + "; keep one, or pass --contract FILE")
    if not candidates and not required:
        return None
    if not candidates:
        raise InitError(f"no contract under {', '.join(map(str, roots))} pairs with {report.name}; pass --artifact-dir "
                        f"or --contract FILE, or build one with fab-test pbir contract init "
                        f"{report.name.removesuffix('.Report')}")
    return candidates.pop()


def _pair(contract: Path, root: Path) -> Target:
    """``contract`` with the report it names: the one beside it when several reports share the logicalId."""
    logical_id = _names(contract)
    reports = [r for r in find_artifact_dirs(root, [".Report"]) if logical_id and report_logical_id(r) == logical_id]
    beside = [r for r in reports if contract.resolve() == (r.parent / f"{r.name}{CONTRACT_SUFFIX}").resolve()]
    if beside or len(reports) == 1:
        return (beside or reports)[0], contract, None
    if reports:
        return None, contract, (f"{len(reports)} reports share {_REPORT_PROPERTY} {logical_id}: "
                                + ", ".join(map(str, reports)) + "; pass the one you mean as TARGET")
    return None, contract, f"pairs with no report under {root} ({_REPORT_PROPERTY}: {logical_id})"


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
          unpaired: str | None) -> dict[str, Any]:
    model = _model(report) if report else None
    result: dict[str, Any] = {"report": str(report) if report else None, "contract": str(contract),
                              "model": str(model) if model else None, "as_of": as_of.isoformat()}
    try:
        yaml.safe_load(contract.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:  # one problem, not one per checker
        return {**result, "ok": False, "apiVersion": None, "rules": 0,
                "problems": [{"source": "fab-test", "message": f"not valid YAML: {_where(exc)}"}]}
    upstream = _pql_lint(pql_test, contract, model)
    problems = [*([{"source": "fab-test", "message": unpaired}] if unpaired else []),
                *_read_as_run(report, contract, as_of),
                *({"source": "pql-test", "message": m} for m in upstream.get("problems", []))]
    return {**result, "ok": not problems, "apiVersion": upstream.get("apiVersion"),
            "rules": upstream.get("rules", 0), "problems": problems}


def _where(exc: Exception) -> str:
    """A YAML error on one line: where, and what."""
    mark, problem = getattr(exc, "problem_mark", None), getattr(exc, "problem", None)
    if mark is not None and problem:
        return f"line {mark.line + 1}, column {mark.column + 1}: {problem}"
    return " ".join(str(exc).split())


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
    return "\n".join([*lines, *([f"  Next: {document['next']}"] if document["next"] else [])])


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
