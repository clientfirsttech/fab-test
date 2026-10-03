"""CLI flags for service mode (Service Targeting epic).

Kept out of `fab_test_parser.py`, which is already over its module budget:
the flags are declared once here and attached to each service-capable
subcommand with one call.
"""

from __future__ import annotations

import argparse


def add_workspace_flag(parser: argparse.ArgumentParser) -> None:
    """``--workspace``: with no TARGET, pure service mode over the workspace."""
    parser.add_argument(
        "--workspace",
        "--workspace-id",
        "--from-workspace",
        default="",
        dest="workspace_id",
        metavar="NAME_OR_ID",
        help=(
            "Workspace name or GUID. With no TARGET, tests every deployed item of this "
            "analyzer's type in the workspace (service mode); local folders are ignored "
            "unless --artifact-dir is passed. --workspace-id/--from-workspace are aliases"
        ),
    )


def add_service_flags(parser: argparse.ArgumentParser) -> None:
    """``--keep-export``, ``--all`` and ``--interactive`` for service mode."""
    parser.add_argument(
        "--keep-export",
        action="store_true",
        dest="keep_export",
        help="Keep exported deployed definitions under the output dir (default: delete after the run)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_items",
        help="Proceed when a workspace enumeration matches more than 50 items",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        dest="interactive",
        help=(
            "Sign in through the browser for service mode (in memory only, never in CI) "
            "[feature flag: interactive_auth in fab-test.yml, FAB_TEST_INTERACTIVE_AUTH=0 disables]"
        ),
    )
