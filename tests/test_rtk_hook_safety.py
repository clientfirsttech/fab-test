"""Policy tests for the Copilot rtk PreToolUse hook (RTK Cloud Agent Blocking epic).

Scope
-----
`.github/hooks/rtk-rewrite.json` used to call `rtk hook copilot` directly,
with no fallback when `rtk` was not on `PATH`. A GitHub Copilot coding agent
session confirmed the failure directly: every tool call was denied -- file
reads, Bash, sub-agent delegation -- because the hook's own runner treats a
failing hook command as a hard block. `copilot-setup-steps.yml` now installs
rtk before the agent's session starts, but a bootstrap step can still be
skipped or fail, so the hook's own command must never depend on that having
worked. These tests exercise the actual shell one-liner, not just its text,
so a future edit that reintroduces a bare `rtk hook copilot` call is caught
here rather than in a live Copilot session.

    pytest -m fab_test tests/test_rtk_hook_safety.py
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HOOK_FILE = _ROOT / ".github" / "hooks" / "rtk-rewrite.json"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell available")


def _hook_command() -> str:
    config = json.loads(_HOOK_FILE.read_text(encoding="utf-8"))
    (hook,) = config["hooks"]["PreToolUse"]
    (command_entry,) = hook.get("hooks", [hook])
    return command_entry["command"]


@pytest.mark.fab_test
def test_the_hook_file_exists():
    """Deleted once already to stop the bleeding; must come back with a guard, not stay gone."""
    assert _HOOK_FILE.exists()


@pytest.mark.fab_test
def test_the_hook_command_checks_for_rtk_before_calling_it():
    """A bare `rtk hook copilot` is exactly the regression this epic exists to prevent."""
    command = _hook_command()

    assert "command -v rtk" in command, command


@pytest.mark.fab_test
def test_the_hook_exits_clean_when_rtk_is_not_on_path():
    """The behavioral guarantee, not just the text: run it for real with rtk hidden."""
    command = _hook_command()
    stripped_env = {"PATH": str(Path(shutil.which("sh")).parent)}

    result = subprocess.run(
        ["sh", "-c", command],
        env=stripped_env,
        input="",
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result
    assert result.stdout == "", result.stdout
