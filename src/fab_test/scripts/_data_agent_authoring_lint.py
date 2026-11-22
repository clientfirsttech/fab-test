"""Offline checks for authored Data Agent suites."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ._data_agent_suite import SuiteError, effective_config, item_identity, load_suite
from .invoke_data_agent import _absolute_references, promptfoo_command, redact

_CREDENTIAL_KEYS = frozenset({
    "access_token", "api_key", "apikey", "authorization", "client_secret",
    "clientsecret", "password", "token",
})
_URL_KEYS = frozenset({"base_url", "fabric_urls"})


def _unsafe_fields(value: Any, path: str = "suite") -> list[str]:
    problems = []
    if isinstance(value, dict):
        for key, child in value.items():
            field = f"{path}.{key}"
            normalized = str(key).lower().replace("-", "_")
            if normalized in _CREDENTIAL_KEYS:
                problems.append(f"{field}: remove credentials from the suite; use the environment or --env-file.")
            elif normalized in _URL_KEYS:
                problems.append(f"{field}: remove hand-built agent URLs; fab-test resolves the agent.")
            else:
                problems.extend(_unsafe_fields(child, field))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(_unsafe_fields(child, f"{path}[{index}]"))
    elif isinstance(value, str) and "/dataagents/" in value.lower() and value.lower().startswith("https://"):
        problems.append(f"{path}: remove the hand-built Data Agent URL; fab-test resolves the agent.")
    return problems


def suite_problems(item: Path, suite: Path) -> list[str]:
    """Check pairing, stable test IDs, and sensitive or manually resolved settings."""
    try:
        logical_id, _ = item_identity(item)
    except SuiteError as exc:
        return [str(exc)]
    try:
        document = load_suite(suite)
    except SuiteError:
        return [f"Cannot read Data Agent suite {suite}; check that it is a UTF-8 YAML mapping."]
    problems = _unsafe_fields(document)
    if document.get("fabTestDataAgent") != logical_id:
        problems.append("fabTestDataAgent must match the item's .platform logicalId.")
    tests = document.get("tests")
    if not isinstance(tests, list) or not tests:
        problems.append("tests must be a non-empty list of inline test mappings.")
        return problems
    seen: set[str] = set()
    for index, test in enumerate(tests, 1):
        metadata = test.get("metadata") if isinstance(test, dict) else None
        test_id = metadata.get("id") if isinstance(metadata, dict) else None
        if not isinstance(test_id, str) or not test_id.strip():
            problems.append(f"Test {index} needs a non-empty metadata.id.")
        elif test_id in seen:
            problems.append(f"Test {index} has duplicate metadata.id {test_id!r}.")
        else:
            seen.add(test_id)
    return problems


def validate_promptfoo(suite: Path, tool: Path) -> list[str]:
    """Run the pinned upstream validator on the same effective config as a run."""
    try:
        document = load_suite(suite)
    except SuiteError:
        return [f"Cannot read Data Agent suite {suite}; check that it is a UTF-8 YAML mapping."]
    problems = _unsafe_fields(document)
    if problems:
        return problems
    config = _absolute_references(
        effective_config(document, "https://example.invalid/data-agent"),
        suite.resolve().parent,
    )
    with tempfile.TemporaryDirectory(prefix="fab-test-data-agent-lint-") as directory:
        root = Path(directory)
        path = root / "effective.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        env = {**os.environ, "PROMPTFOO_CONFIG_DIR": str(root), "PROMPTFOO_DISABLE_TELEMETRY": "1",
               "PROMPTFOO_DISABLE_UPDATE_CHECK": "1"}
        proc = subprocess.run(
            [*promptfoo_command(tool), "validate", "config", "--config", str(path)],
            cwd=suite.resolve().parent, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, check=False,
        )
    if proc.returncode:
        detail = redact((proc.stderr or proc.stdout).strip())
        return [f"promptfoo validate config exited {proc.returncode}: {detail or 'no diagnostic output'}"]
    return []
