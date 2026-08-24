"""Contract tests for build_playwright_command's --pages/--roles passthrough.

Playwright Test Matrix Discovery epic: `fab-test playwright` discovers pages,
bookmarks, and roles by default, and the top-level `--pages none`/`--roles
none` overrides must reach the `invoke_playwright` subprocess command line.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fabric_ci_cd_dataops.scripts.fab_test_registry import build_playwright_command


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "playwright_env_file": None,
        "environment": "",
        "workspace_id": "",
        "impact_manifest": None,
        "dataset_id": "",
        "pages": "auto",
        "roles": "auto",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_default_pages_and_roles_are_not_passed_through(tmp_path: Path) -> None:
    """The 'auto' default is invoke_playwright's own default, so it is left
    off the command line rather than repeated on every invocation."""
    cmd = build_playwright_command(Path("ThinReport"), _args(), tmp_path)

    assert "--pages" not in cmd
    assert "--roles" not in cmd


def test_pages_none_is_forwarded_to_invoke_playwright(tmp_path: Path) -> None:
    """--pages none reaches the wrapper so discovery can be turned off."""
    cmd = build_playwright_command(Path("ThinReport"), _args(pages="none"), tmp_path)

    assert "--pages" in cmd
    assert cmd[cmd.index("--pages") + 1] == "none"


def test_roles_none_is_forwarded_to_invoke_playwright(tmp_path: Path) -> None:
    """--roles none reaches the wrapper so role discovery can be turned off."""
    cmd = build_playwright_command(Path("ThinReport"), _args(roles="none"), tmp_path)

    assert "--roles" in cmd
    assert cmd[cmd.index("--roles") + 1] == "none"
