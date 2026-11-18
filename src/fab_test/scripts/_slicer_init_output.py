"""`contract init`'s output flags and printing (PBIR Slicer Default State epic).

`init` takes the output flags every fab-test command takes, with the same
meaning: -q prints nothing on success (the exit code is the result), -v lists
every rule the contract holds, and ANALYZER_VERBOSITY and fab-test.yml's
`verbosity:` work too. `init` writes a contract, not a report, so --report /
--no-report / --open-report, and `fab-test pbir`'s --contract and --output-dir,
name the command they belong to instead of failing as unrecognised. Errors,
--questions and --format json always print: they are what was asked for.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ._config import VERBOSITY_LEVELS, ConfigError, merged_file_config, resolve_setting, verbosity_level
from ._pbir_rule_sources import expects
from ._slicer_init_calendar import describe_calendar


def can_ask() -> bool:
    """Whether a person is there to answer: prompts go to stderr and answers come from stdin, so both must be
    a terminal. Windows reports the null device as one (NUL is a character device), which is how coding
    agents run commands; there, only a real console has a console mode."""
    streams = (sys.stdin, sys.stderr)
    if not all(stream.isatty() for stream in streams):
        return False
    return os.name != "nt" or all(_console(stream) for stream in streams)


def _console(stream: Any) -> bool:
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(wintypes.DWORD())))
    except (AttributeError, ImportError, OSError, ValueError):  # no file handle, or not Windows
        return False


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="count", default=0,
                           help="Also list every rule in the contract and what happened to it")
    verbosity.add_argument("-q", "--quiet", action="store_true",
                           help="Print nothing on success; the exit code is the result")
    for flag in ("--report", "--no-report", "--open-report"):
        parser.add_argument(flag, action="append_const", const=flag, dest="pbir_flags", help=argparse.SUPPRESS)
    for flag in ("--contract", "--output-dir"):  # take a value, so a person's whole command parses
        parser.add_argument(flag, action=_Named, nargs="?", dest="pbir_flags", help=argparse.SUPPRESS)


class _Named(argparse.Action):
    """Record which of `fab-test pbir`'s flags was given, whatever its value."""

    def __call__(self, _parser, namespace, _values, option_string=None):
        setattr(namespace, self.dest, [*(getattr(namespace, self.dest, None) or []), option_string])


def level(args: argparse.Namespace) -> str:
    """summary, default or verbose: the flags, then ANALYZER_VERBOSITY, then fab-test.yml, as for every command."""
    if args.quiet:
        return "summary"
    if args.verbose:
        return "verbose"
    try:
        file_config, _warnings = merged_file_config(Path.cwd(), Path.cwd() / "pyproject.toml")
    except ConfigError:  # `fab-test pbir` reports a broken config; init only needs a verbosity
        file_config = {}
    value, _origin = resolve_setting("verbosity", cli_value=None, env_var="ANALYZER_VERBOSITY",
                                     file_config=file_config, packaged_default="default", cast=verbosity_level)
    value = str(value).strip().lower()
    return {"debug": "verbose"}.get(value, value) if value in VERBOSITY_LEVELS else "default"


def pbir_refusal(args: argparse.Namespace, report_name: str) -> str | None:
    """Why one of `fab-test pbir`'s flags doesn't apply to init, naming the command it belongs to."""
    if not getattr(args, "pbir_flags", None):
        return None
    flag, name = args.pbir_flags[0], report_name.removesuffix(".Report")
    if flag in ("--contract", "--output-dir"):
        return (f"{flag}: contract init writes <Report>.Report.odcs.yaml beside the report; {flag} is for "
                f"checking it: fab-test pbir --artifact {name} {flag} ...")
    return (f"{flag}: contract init writes a contract, not a report; see it checked with "
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
        suggested = "no default" if q["suggested"] is None else f"suggested: {q['suggested']}{hint}"
        lines.append(f"  {q['id']}: {q['prompt']} [{suggested}]")
    return "\n".join(lines)


def summary_text(summary: dict, contract: Any = None, calendar: dict | None = None) -> str:
    """What was written, and the fiscal year when it changed; with ``contract`` (verbose), every rule in it,
    what it expects, and what happened to it."""
    lines = [f"  ✓ {summary['contract']}"]
    lines += [f"    {key}: {', '.join(ids)}" for key, ids in summary.items() if isinstance(ids, list) and ids]
    if summary["kept"]:
        lines.append("    kept: their checks differ from the report today; --force replaces them")
    if summary["calendar"] in ("added", "replaced") and calendar:
        lines.append(f"    fabTestCalendar: {summary['calendar']} ({describe_calendar(calendar)})")
    if summary["calendar"] == "kept":
        lines.append("    the contract's fabTestCalendar differs from your answers and was kept; --force replaces it")
    if contract is not None:
        what = {i: key for key in ("added", "kept", "replaced", "unchanged") for i in summary[key]}
        lines += [f"    {e.rule_id}  {e.page}  '{e.table}'[{e.column}] {expects(e.check, e.expected)}  "
                  f"{what.get(e.rule_id, 'already in the contract')}" for e in contract.expectations]
        lines += [f"    {n.rule_id}  {n.page}  bookmark navigator opens with {n.selected or 'no bookmark'}  "
                  f"{what.get(n.rule_id, 'already in the contract')}" for n in contract.navigators]
    return "\n".join(lines)
