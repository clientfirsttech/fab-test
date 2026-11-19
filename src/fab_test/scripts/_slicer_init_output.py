"""`contract init`'s flags and printing (PBIR Slicer Default State; Authoring Command Grammar).

`init` takes the inputs `fab-test pbir` takes, the same way: TARGET is the
report, a path or a name found under --artifact-dir, and --artifact-dir and
--format default from fab-test.yml as the run's do. It takes the output flags
every fab-test command takes, with the same meaning: -q prints one result line
shaped like the run's, -v lists every rule the contract holds, and
ANALYZER_VERBOSITY and fab-test.yml's `verbosity:` work too. `init` writes a contract, not a report, so --report /
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
from ._metadata import default_repo_root
from ._pbir_rule_sources import expects
from ._slicer_init_calendar import describe_calendar

FORMATS = ("text", "json")


def file_config() -> dict:
    """fab-test.yml over pyproject.toml's [tool.fab-test], read from where `fab-test pbir` reads it.
    Empty when it can't be read: the run is what reports a broken config."""
    root = default_repo_root()
    try:
        return merged_file_config(root, root / "pyproject.toml")[0]
    except ConfigError:
        return {}


def add_input_flags(parser: argparse.ArgumentParser) -> None:
    """The report and output format, named, described and defaulted as `fab-test pbir` does."""
    parser.add_argument("target", nargs="?", default=None, metavar="TARGET",
                        help="Report to build the contract for: a path (./Sales.Report) or a name "
                             "(Sales or Sales.Report) found under --artifact-dir")
    parser.add_argument("--artifact", default=None, metavar="STEM", help="Deprecated alias for the TARGET argument")
    parser.add_argument("--artifact-dir", default=None, metavar="DIR",
                        help="Root to discover artifacts under, recursively (default: artifact_dir in "
                             "fab-test.yml, else the working directory)")
    parser.add_argument("--format", choices=list(FORMATS), default=None, dest="output_format",
                        help="text for people, json for agents and scripts (default: format in fab-test.yml, "
                             "else text)")


def resolve_inputs(args: argparse.Namespace) -> None:
    """Fill the defaults the flags left open: the flag, then fab-test.yml, then the packaged default."""
    config = file_config()
    args.artifact_dir = args.artifact_dir or str(config.get("artifact_dir", default_repo_root()))
    if args.output_format is None:
        args.output_format = config.get("format") if config.get("format") in FORMATS else "text"


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
                           help="Print one result line: what was written, and where")
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
    value, _origin = resolve_setting("verbosity", cli_value=None, env_var="ANALYZER_VERBOSITY",
                                     file_config=file_config(), packaged_default="default", cast=verbosity_level)
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


def print_payload(args: argparse.Namespace, payload: dict, as_text, asked_for: bool = False, as_line=None) -> None:
    """JSON always; text unless quiet, or always when it is what was asked for (--questions, --dry-run);
    quiet prints ``as_line``, the one result line, when there is one."""
    if args.output_format == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif asked_for or level(args) != "summary":
        print(as_text(payload))
    elif as_line:
        print(as_line(payload))


def result_line(summary: dict) -> str:
    """-q's one line, shaped like `fab-test pbir -q`'s `pbir passed e=0 w=0 PATH`."""
    counts = " ".join(f"{key}={len(summary[key])}" for key in ("added", "replaced", "kept", "unchanged"))
    return f"contract written {counts} {summary['contract']}"


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
