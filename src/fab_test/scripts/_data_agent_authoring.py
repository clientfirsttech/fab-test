"""Offline authoring commands for paired Data Agent promptfoo suites."""

import argparse
import sys

from ._authoring_output import add_input_flags, resolve_inputs
from ._config import ConfigError
from ._data_agent_init import init_main
from ._data_agent_lint_command import lint_main
from ._service_flags import add_workspace_flag
from ._tests_dir import add_tests_dir_flag


def add_data_agent_parser(subs: argparse._SubParsersAction, add_common_flags) -> None:
    """Register the Data Agent run and its authoring verbs."""
    from ._authoring_parser import add_authoring_noun

    agent = subs.add_parser("data-agent", aliases=["agent", "data_agent"],
                            help="Regression-test deployed Fabric Data Agents (promptfoo)")
    add_common_flags(agent, track_artifact_dir_explicit=True)
    add_workspace_flag(agent)
    agent.add_argument("--tests", default=None, metavar="FILE",
                       help="Promptfoo suite overriding logicalId pairing with a .DataAgent item")
    add_tests_dir_flag(agent)
    agent.add_argument("--env-file", default=None, dest="playwright_env_file", metavar="PATH",
                       help="Path to .env file with service principal credentials")
    agent.add_argument("--all", action="store_true", dest="all_items",
                       help="Allow live workspace enumeration over 5 Data Agents")
    add_authoring_noun(agent, "tests", authoring_parser())


def authoring_parser() -> argparse.ArgumentParser:
    """Build the tests noun and its verbs."""
    parser = argparse.ArgumentParser(prog="fab-test data-agent tests")
    verbs = parser.add_subparsers(dest="action", required=True, metavar="{init,lint}")
    init = verbs.add_parser("init", help="Create or extend a paired promptfoo suite")
    add_input_flags(init, "Data Agent item to create tests for")
    init.add_argument("--tests", default=None, metavar="FILE", help="Suite overriding logicalId pairing")
    init.add_argument("--questions", action="store_true", help="Print questions without writing a suite")
    init.add_argument("--answers", default=None, metavar="FILE", help="JSON expected answers by question id")
    init.add_argument("--force", action="store_true", help="Replace existing tests and rewrite comments")
    init.add_argument("--dry-run", action="store_true", help="Show the suite without writing it")
    init_verbosity = init.add_mutually_exclusive_group()
    init_verbosity.add_argument("-q", "--quiet", action="store_true", help="Print one result line")
    init_verbosity.add_argument("-v", "--verbose", action="count", default=0, help="Show generated details")
    lint = verbs.add_parser("lint", help="Check paired suites without contacting Fabric")
    add_input_flags(lint, "Data Agent item to check; omit to check every suite")
    lint.add_argument("--tests", default=None, metavar="FILE", help="Suite overriding logicalId pairing")
    verbosity = lint.add_mutually_exclusive_group()
    verbosity.add_argument("-q", "--quiet", action="store_true", help="Print one result line per suite")
    verbosity.add_argument("-v", "--verbose", action="count", default=0, help="Show each validation finding")
    return parser


def tests_main(args: argparse.Namespace, unknown: list[str], parser: argparse.ArgumentParser) -> int:
    """Dispatch an authoring verb after refusing flags reserved for the run."""
    from .fab_test_parser import build_parser

    choices = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)).choices
    run_options = choices["data-agent"]._option_string_actions
    flags = [value.split("=")[0] for value in unknown if value.startswith("-")]
    if flags and flags[0] in run_options:
        print(f"  ✗ fab-test data-agent tests {args.action}: {flags[0]} belongs to "
              "the run: fab-test data-agent", file=sys.stderr)
        return 2
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    try:
        resolve_inputs(args)
        return init_main(args) if args.action == "init" else lint_main(args)
    except ConfigError as exc:
        print(f"  ✗ fab-test data-agent tests: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n  ✗ fab-test data-agent tests: interrupted; nothing was written", file=sys.stderr)
        return 130
