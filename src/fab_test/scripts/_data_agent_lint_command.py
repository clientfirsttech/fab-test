"""Discover, pair and report offline Data Agent suite lint results."""

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

from ._analyzer_tool_bootstrap import resolve_executable
from ._authoring_output import level, next_command, print_payload
from ._data_agent_authoring_lint import suite_problems, suite_warnings, validate_promptfoo
from ._data_agent_suite import SuiteError, item_identity, load_suite, suite_files
from ._scan import ScanError, find_artifact_dirs
from ._tests_dir import search_roots
from .fab_test_registry import ANALYZERS_JSON, REPO_ROOT


class LintInputError(ValueError):
    """No requested item or suite can be checked."""


def _named_item(items: list[Path], target: str) -> Path:
    direct = Path(target)
    matches = ([direct] if direct.is_dir() else
               [item for item in items if item.name in (target, f"{target}.DataAgent")])
    if len(matches) != 1:
        raise LintInputError(f"{target}: expected one Data Agent item, found {len(matches)}; pass its folder path.")
    return matches[0]


def _identity(path: Path) -> str | None:
    try:
        value = load_suite(path).get("fabTestDataAgent")
    except SuiteError:
        return None
    return value if isinstance(value, str) else None


def _targets(args: argparse.Namespace) -> list[tuple[Path | None, Path]]:
    root = Path(args.artifact_dir)
    items = find_artifact_dirs(root, [".DataAgent"])
    named = args.target or args.artifact
    item = _named_item(items, named) if named else None
    suites = suite_files(search_roots(args, item))
    if args.tests:
        suite = Path(args.tests)
        if not suite.is_file():
            raise LintInputError(f"--tests {suite}: no such file.")
        suites = [suite]
    if item and not args.tests:
        logical_id, _ = item_identity(item)
        beside = item.parent / f"{item.name}.promptfoo.yaml"
        suites = [path for path in suites if _identity(path) == logical_id or
                  (path == beside and _identity(path) is None)]
    if not suites:
        raise LintInputError("No paired Data Agent suite found; run fab-test data-agent tests init TARGET.")
    if item:
        if len(suites) > 1:
            raise LintInputError(f"Multiple suites pair with {item}; keep one or pass --tests FILE.")
        return [(item, suites[0])]
    targets = []
    for suite in suites:
        identity = _identity(suite)
        matches = [candidate for candidate in items if identity and item_identity(candidate)[0] == identity]
        beside = [candidate for candidate in matches if suite == candidate.parent / f"{candidate.name}.promptfoo.yaml"]
        if not matches and identity is None:
            beside = [candidate for candidate in items
                      if suite == candidate.parent / f"{candidate.name}.promptfoo.yaml"]
        targets.append(((beside or matches)[0] if len(beside or matches) == 1 else None, suite))
    return targets


def _promptfoo() -> Path:
    """fab-test's pinned promptfoo, installed on first use exactly as the run installs it."""
    return resolve_executable("data_agent", ANALYZERS_JSON, REPO_ROOT)


def _result_line(result: dict) -> str:
    return (f"tests {'passed' if result['ok'] else 'failed'} e={len(result['problems'])} "
            f"w={len(result['warnings'])} {result['suite']}")


def _text(payload: dict) -> str:
    lines = []
    for result in payload["suites"]:
        lines.append(_result_line(result))
        lines.extend(f"  {problem}" for problem in result["problems"])
        lines.extend(f"  warning: {warning}" for warning in result["warnings"])
    if payload["next"]:
        lines.append(f"Next: {payload['next']}")
    return "\n".join(lines)


def _lines(payload: dict) -> str:
    return "\n".join(_result_line(result) for result in payload["suites"])


def _offline(targets: list[tuple[Path | None, Path]]) -> list[dict]:
    """Every check that needs neither promptfoo nor the service, one result per suite."""
    identities = Counter(identity for _, suite in targets if (identity := _identity(suite)))
    results = []
    for item, suite in targets:
        problems = suite_problems(item, suite) if item else ["Suite pairs with no unique Data Agent item."]
        identity = _identity(suite)
        if identity and identities[identity] > 1:
            problems.append(f"Duplicate suites claim Data Agent {identity}; keep one suite.")
        results.append({"item": str(item) if item else None, "suite": str(suite), "ok": not problems,
                        "problems": problems, "warnings": suite_warnings(suite)})
    return results


def _validate(results: list[dict]) -> None:
    """promptfoo's own check on each suite that passed the offline ones; RuntimeError when it can't be had."""
    clean = [result for result in results if not result["problems"]]
    tool = _promptfoo() if clean else None
    for result in clean:
        try:
            result["problems"] = validate_promptfoo(Path(result["suite"]), tool)
        except SuiteError as exc:
            result["problems"] = [str(exc)]
        result["ok"] = not result["problems"]


def lint_main(args: argparse.Namespace) -> int:
    """Validate all requested suites, leaving authored files and result folders untouched."""
    try:
        results = _offline(_targets(args))  # what needs no promptfoo goes first (Review 2)
        unavailable = None
        try:
            _validate(results)
        except RuntimeError as exc:
            unavailable = f"promptfoo is unavailable: {exc}"
        if unavailable and not any(result["problems"] for result in results):
            print(f"  ✗ fab-test data-agent tests lint: {unavailable}", file=sys.stderr)
            return 127
        ok = not unavailable and all(result["ok"] for result in results)
        payload = {"ok": ok, "suites": results,
                   "next": next_command(args, "fab-test data-agent") if ok else None}
        print_payload(args, payload, _text, as_line=_lines)
        if level(args) == "summary" and args.output_format != "json":
            for result in results:
                for problem in result["problems"]:
                    print(f"  {result['suite']}: {problem}", file=sys.stderr)
        if unavailable:  # the offline findings are shown; the rest could not be checked
            print(f"  ✗ fab-test data-agent tests lint: {unavailable}; suites without findings were not "
                  "validated", file=sys.stderr)
            return 127
    except (LintInputError, ScanError, SuiteError) as exc:
        print(f"  ✗ fab-test data-agent tests lint: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"  ✗ fab-test data-agent tests lint: {exc}", file=sys.stderr)
        return 127
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ✗ fab-test data-agent tests lint: {exc}", file=sys.stderr)
        return 1
    return 0 if ok else 1
