"""`contract init`'s output flags and printing (PBIR Slicer Default State epic).

`init` takes the output flags every fab-test command takes, with the same
meaning: -q prints nothing on success (the exit code is the result), -v lists
every rule the contract holds, and ANALYZER_VERBOSITY works too. `init`
writes a contract, not a report, so --report / --no-report / --open-report
name the command that does instead of failing as unrecognised. Errors,
--questions and --format json always print: they are what was asked for.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

_LEVELS = ("summary", "default", "verbose", "debug")  # as ANALYZER_VERBOSITY names them


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="count", default=0,
                           help="Also list every rule in the contract and what happened to it")
    verbosity.add_argument("-q", "--quiet", action="store_true",
                           help="Print nothing on success; the exit code is the result")
    for flag in ("--report", "--no-report", "--open-report"):
        parser.add_argument(flag, action="append_const", const=flag, dest="report_flags", help=argparse.SUPPRESS)


def level(args: argparse.Namespace) -> str:
    """summary, default or verbose: the flags first, then ANALYZER_VERBOSITY, as for every command."""
    if args.quiet:
        return "summary"
    if args.verbose:
        return "verbose"
    env = os.environ.get("ANALYZER_VERBOSITY", "").lower().strip()
    return {"debug": "verbose"}.get(env, env) if env in _LEVELS else "default"


def report_refusal(args: argparse.Namespace, report_name: str) -> str | None:
    """Why a report flag doesn't apply, naming the command that makes the report."""
    if not getattr(args, "report_flags", None):
        return None
    name = report_name.removesuffix(".Report")
    return (f"{args.report_flags[0]}: contract init writes a contract, not a report; see it checked with "
            f"fab-test pbir --artifact {name} --open-report")


def print_payload(args: argparse.Namespace, payload: dict, as_text, asked_for: bool = False) -> None:
    """JSON always; text unless quiet, or always when it is what was asked for (--questions, --dry-run)."""
    if args.output_format == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif asked_for or level(args) != "summary":
        print(as_text(payload))


def questions_text(questions: dict) -> str:
    lines = [f"Contract: {questions['contract']} (as of {questions['as_of']})"]
    for q in questions["questions"]:
        hint = f" -> {q['calendar_format']}" if q.get("calendar_format") else ""
        lines.append(f"  {q['id']}: {q['prompt']} [suggested: {q['suggested']}{hint}]")
    return "\n".join(lines)


def summary_text(summary: dict, contract: Any = None) -> str:
    """What was written; with ``contract`` (verbose), every rule in it, its check, and what happened to it."""
    lines = [f"  ✓ {summary['contract']}"]
    lines += [f"    {key}: {', '.join(ids)}" for key, ids in summary.items() if isinstance(ids, list) and ids]
    if summary["kept"]:
        lines.append("    kept: their checks differ from the report today; --force replaces them")
    if summary["calendar"] == "kept":
        lines.append("    the contract's fabTestCalendar differs from your answers and was kept; --force replaces it")
    if contract is not None:
        what = {i: key for key in ("added", "kept", "replaced", "unchanged") for i in summary[key]}
        lines += [f"    {e.rule_id}  {e.page}  '{e.table}'[{e.column}]  {e.check}: {e.expected!r}  "
                  f"{what.get(e.rule_id, 'already in the contract')}" for e in contract.expectations]
        lines += [f"    {n.rule_id}  {n.page}  bookmark navigator  selected: {n.selected or 'no bookmark'}  "
                  f"{what.get(n.rule_id, 'already in the contract')}" for n in contract.navigators]
    return "\n".join(lines)
