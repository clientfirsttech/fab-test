"""Argument-parser wiring for ``fab-test data-agent``."""

from __future__ import annotations

import argparse


def add_data_agent_subparser(
    subs: argparse._SubParsersAction,
    add_common_flags,
    add_workspace_flag,
) -> None:
    """Register the ``data-agent`` analyzer and its nested ``init`` command."""
    data_agent_p = subs.add_parser(
        "data-agent",
        aliases=["agent", "data_agent"],
        help="Promptfoo evaluation of deployed Fabric Data Agents (.DataAgent artifacts)",
    )
    data_agent_subs = data_agent_p.add_subparsers(dest="data_agent_command", metavar="COMMAND")
    init_p = data_agent_subs.add_parser("init", help="Scaffold a starter .DataAgent folder")
    init_p.add_argument("name", metavar="NAME", help="Artifact stem (creates NAME.DataAgent)")
    init_p.add_argument("--force", action="store_true", help="Overwrite an existing promptfooconfig.yaml")
    add_common_flags(data_agent_p, track_artifact_dir_explicit=True)
    add_workspace_flag(data_agent_p)
    data_agent_p.add_argument(
        "--all",
        action="store_true",
        dest="all_items",
        help="Proceed when a workspace enumeration matches more than 5 deployed Data Agents",
    )
    data_agent_p.add_argument(
        "--promptfoo-path",
        default=None,
        dest="promptfoo_path",
        metavar="PATH",
        help="Path to the promptfoo CLI entry point [env: PROMPTFOO_PATH]",
    )
    data_agent_p.add_argument(
        "--env-file",
        default=None,
        dest="data_agent_env_file",
        metavar="PATH",
        help="Path to a .env file containing FABRIC_* values for Data Agent runs",
    )
