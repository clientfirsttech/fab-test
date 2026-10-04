"""Scaffolding for ``fab-test data-agent init``."""

from __future__ import annotations

import json
from pathlib import Path

_PROMPTFOO_TEMPLATE = """\
description: Starter Data Agent promptfoo suite
providers:
  - id: file://./fabric_data_agent_provider.py
tests:
  - description: Reject unrelated prompts
    vars:
      conversation: starter
      query: Tell me a joke
    assert:
      - type: regex
        value: "(?i)(cannot|can't|not able|not relevant|out of scope)"
  - description: Answer a domain question
    vars:
      conversation: starter
      query: Replace with a real question about your data
    assert:
      - type: not-empty
"""

_ENV_TEMPLATE = """\
# Copy to .env for local runs. Never commit the real file.
FABRIC_TENANT_ID=
FABRIC_CLIENT_ID=
FABRIC_CLIENT_SECRET=
FABRIC_WORKSPACE_ID=
"""


def data_agent_dir(name: str, cwd: Path) -> Path:
    """Return the scaffold directory for ``name``."""
    return cwd / f"{name}.DataAgent"


def scaffold_data_agent(name: str, cwd: Path, *, force: bool = False) -> tuple[bool, Path]:
    """Create or overwrite a starter ``.DataAgent`` test folder."""
    target = data_agent_dir(name, cwd)
    promptfoo = target / "promptfooconfig.yaml"
    env_example = target / ".env.example"
    if promptfoo.exists() and not force:
        return False, target
    target.mkdir(parents=True, exist_ok=True)
    promptfoo.write_text(_PROMPTFOO_TEMPLATE, encoding="utf-8")
    env_example.write_text(_ENV_TEMPLATE, encoding="utf-8")
    (target / "sample-context.json").write_text(
        json.dumps({"notes": ["Replace starter assertions with workspace-specific checks."]}, indent=2),
        encoding="utf-8",
    )
    return True, target
