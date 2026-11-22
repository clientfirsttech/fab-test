"""Pair Data Agent suites by logical identity and generate promptfoo's effective config."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

from ._scan import find_files_by_suffix

SUITE_SUFFIX = ".DataAgent.promptfoo.yaml"


class SuiteError(ValueError):
    """A suite or item identity that the caller must fix before running."""


def load_suite(path: Path) -> dict[str, Any]:
    """Read an authored promptfoo YAML mapping, naming unreadable files."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SuiteError(f"Cannot read Data Agent suite {path}; check that it is UTF-8 YAML.") from exc
    if not isinstance(document, dict):
        raise SuiteError(f"Data Agent suite {path} must be a YAML mapping.")
    return document


def item_identity(item: Path) -> tuple[str, str]:
    """The item's stable logicalId and deployed displayName from .platform."""
    platform = item / ".platform"
    try:
        document = json.loads(platform.read_text(encoding="utf-8-sig"))
        logical_id = document["config"]["logicalId"]
        display_name = document["metadata"]["displayName"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise SuiteError(f"Cannot read logicalId and displayName from {platform}: {exc}") from exc
    if (not isinstance(logical_id, str) or not logical_id.strip()
            or not isinstance(display_name, str) or not display_name):
        raise SuiteError(f"{platform} needs non-empty config.logicalId and metadata.displayName.")
    return logical_id, display_name


def suite_files(roots: Path | list[Path], excluded: list[Path] | None = None) -> list[Path]:
    """Every suite under ``roots``: --artifact-dir and fab-tests/ (decision 22)."""
    roots = [roots] if isinstance(roots, Path) else roots
    return sorted({path.resolve() for root in roots
                   for path in find_files_by_suffix(root, SUITE_SUFFIX, excluded_paths=excluded or [])})


def suite_index(roots: Path | list[Path], excluded: list[Path] | None = None) -> dict[str, Path]:
    """Index suites by fabTestDataAgent, refusing ambiguous claims before any eval."""
    paired: dict[str, Path] = {}
    for path in suite_files(roots, excluded):
        identity = load_suite(path).get("fabTestDataAgent")
        if not isinstance(identity, str) or not identity.strip():
            raise SuiteError(f"{path} needs fabTestDataAgent: <the item's .platform logicalId>.")
        if identity in paired:
            raise SuiteError(f"{paired[identity]} and {path} both pair with Data Agent {identity}. Keep one suite.")
        paired[identity] = path
    return paired


def pair_suite(item: Path, paired: dict[str, Path], explicit: Path | None = None) -> Path | None:
    """The explicit --tests file, or the suite claiming this item's logicalId."""
    if explicit is not None:
        load_suite(explicit)
        return explicit
    logical_id, _name = item_identity(item)
    return paired.get(logical_id)


_RESERVED_ENV_PREFIXES = ("FAB_TEST_", "FABRIC_", "AZURE_", "PROMPTFOO_", "PLAYWRIGHT_ENV_FILE")


def _refuse_reserved_env(env: Any, where: str) -> None:
    """A suite's ``env`` must not set what decides where the token goes or which interpreter runs (decision 17)."""
    if env is None:
        return
    if not isinstance(env, dict):
        raise SuiteError(f"promptfoo {where} must be a mapping.")
    reserved = sorted(str(key) for key in env if str(key).upper().startswith(_RESERVED_ENV_PREFIXES))
    if reserved:
        raise SuiteError(
            f"{where} sets {', '.join(reserved)}; fab-test reads these only from the caller's environment "
            "or --env-file, never from a suite. Remove them from the suite."
        )


def _effective_provider(provider: Any, base_url: str, conversation: bool) -> dict[str, Any]:
    """One provider entry pointed at the packaged provider, with the resolved URL unless the suite names one."""
    if not isinstance(provider, (str, dict)):
        raise SuiteError("promptfoo providers[] entries must be strings or mappings.")
    authored = provider if isinstance(provider, dict) else {}
    _refuse_reserved_env(authored.get("env"), "providers[].env")
    options = authored.get("config", {})
    if not isinstance(options, dict):
        raise SuiteError("promptfoo providers[].config must be a mapping.")
    effective_options = {**options}
    if not options.get("base_url") and not options.get("fabric_urls"):
        effective_options["base_url"] = base_url
    if conversation:
        effective_options["workers"] = 1
    return {
        **authored,
        "id": f"file://{(Path(__file__).parent.parent / 'fabric_data_agent_provider.py').resolve().as_posix()}",
        "config": effective_options,
    }


def effective_config(document: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Inject the packaged provider and resolved URL, preserving native assertions."""
    config = copy.deepcopy(document)
    config.pop("fabTestDataAgent", None)
    _refuse_reserved_env(config.get("env"), "env")
    tests = config.get("tests", [])
    if not isinstance(tests, list) or any(not isinstance(test, dict) for test in tests):
        raise SuiteError("Data Agent tests must be inline YAML test mappings so conversation ordering can be checked.")
    defaults = config.get("defaultTest")
    defaults = {} if defaults is None else defaults
    if not isinstance(defaults, dict):
        raise SuiteError("promptfoo defaultTest must be a mapping.")
    conversation = any(
        isinstance(test.get("vars"), dict)
        and bool(test["vars"].get("conversation") or test["vars"].get("conversation_id"))
        for test in [defaults, *tests]
    )
    providers = config.get("providers")
    if providers is None or providers == []:
        providers = [{}]
    if isinstance(providers, (str, dict)):
        providers = [providers]
    if not isinstance(providers, list):
        raise SuiteError("promptfoo providers must be a provider or a list of providers.")
    config["providers"] = [_effective_provider(provider, base_url, conversation) for provider in providers]
    if conversation:
        evaluate = config.get("evaluateOptions")
        evaluate = {} if evaluate is None else evaluate
        if not isinstance(evaluate, dict):
            raise SuiteError("promptfoo evaluateOptions must be a mapping.")
        config["evaluateOptions"] = {**evaluate, "maxConcurrency": 1}
    return config
