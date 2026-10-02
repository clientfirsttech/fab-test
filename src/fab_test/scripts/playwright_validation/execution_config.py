"""Optional, data-only browser execution settings for generated report tests."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .._config import ConfigError


@dataclass(frozen=True)
class ExecutionConfig:
    """Validated non-secret settings; absent selection retains local defaults."""

    path: Path | None = None
    origin: str = "default"
    backend: str = "local"
    workers: int | None = None
    launch: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    connection: dict[str, Any] = field(default_factory=dict)


def _refuse(path: Path, detail: str) -> None:
    raise ConfigError(f"--playwright-config {path}: {detail}")


def _mapping(value: Any, allowed: set[str], path: Path, section: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(key not in allowed for key in value):
        _refuse(path, (
            f"{section} must be a mapping containing only {', '.join(sorted(allowed))}; "
            "put credentials in PLAYWRIGHT_SERVICE_ACCESS_TOKEN / FABRIC_CLIENT_SECRET environment or .env, not YAML"
        ))
    return value


def _positive_integer(value: Any) -> bool:
    return type(value) is int and value > 0


def _validate_launch(value: Any, path: Path) -> dict[str, Any]:
    launch = _mapping(value, {"headless", "args", "slow_mo"}, path, "launch")
    if "headless" in launch and type(launch["headless"]) is not bool:
        _refuse(path, "launch.headless must be boolean")
    if "args" in launch and (
        not isinstance(launch["args"], list) or not all(isinstance(item, str) for item in launch["args"])
    ):
        _refuse(path, "launch.args must be a list of strings")
    if "slow_mo" in launch and (type(launch["slow_mo"]) not in (int, float) or launch["slow_mo"] < 0):
        _refuse(path, "launch.slow_mo must be a nonnegative number")
    return launch


def _validate_context(value: Any, path: Path) -> dict[str, Any]:
    context = _mapping(
        value, {"viewport", "locale", "timezone_id", "color_scheme", "ignore_https_errors"}, path, "context"
    )
    for key in ("locale", "timezone_id"):
        if key in context and not isinstance(context[key], str):
            _refuse(path, f"context.{key} must be a string")
    if "color_scheme" in context and context["color_scheme"] not in ("light", "dark", "no-preference"):
        _refuse(path, "context.color_scheme must be light, dark, or no-preference")
    if "ignore_https_errors" in context and type(context["ignore_https_errors"]) is not bool:
        _refuse(path, "context.ignore_https_errors must be boolean")
    if "viewport" in context:
        viewport = _mapping(context["viewport"], {"width", "height"}, path, "context.viewport")
        if set(viewport) != {"width", "height"} or not all(_positive_integer(item) for item in viewport.values()):
            _refuse(path, "context.viewport requires positive integer width and height")
    return context


def _validate_connection(value: Any, path: Path, backend: str) -> dict[str, Any]:
    connection = _mapping(value, {"os", "timeout_ms", "expose_network"}, path, "connection")
    if connection and backend != "azure":
        _refuse(path, "connection settings require backend: azure")
    if "os" in connection and connection["os"] not in ("linux", "windows"):
        _refuse(path, "connection.os must be linux or windows")
    if "timeout_ms" in connection and not _positive_integer(connection["timeout_ms"]):
        _refuse(path, "connection.timeout_ms must be a positive integer")
    if "expose_network" in connection and not isinstance(connection["expose_network"], str):
        _refuse(path, "connection.expose_network must be a string")
    return connection


def _load_execution_config(path: Path, origin: str) -> ExecutionConfig:
    if path.suffix.lower() not in (".yml", ".yaml"):
        _refuse(path, "expected YAML (.yml or .yaml), not an executable Playwright config")
    if not path.exists():
        _refuse(path, "file not found; correct the path or unset PLAYWRIGHT_CONFIG_PATH")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        _refuse(path, "cannot read valid UTF-8 YAML; file contents withheld")
    data = _mapping(
        {} if data is None else data, {"backend", "workers", "launch", "context", "connection"}, path, "config"
    )
    backend = data.get("backend", "local")
    if backend not in ("local", "azure"):
        _refuse(path, "backend must be local or azure")
    workers = data.get("workers")
    if "workers" in data and not _positive_integer(workers):
        _refuse(path, "workers must be a positive integer")
    return ExecutionConfig(
        path=path, origin=origin, backend=backend, workers=workers,
        launch=_validate_launch(data.get("launch", {}), path),
        context=_validate_context(data.get("context", {}), path),
        connection=_validate_connection(data.get("connection", {}), path, backend),
    )


def resolve_execution_config(
    explicit: str | None = None,
    file_config: dict[str, Any] | None = None,
    repo_root: Path | None = None,
) -> ExecutionConfig:
    """Resolve flag > environment > fab-test config > unchanged local default."""
    environment = os.environ.get("PLAYWRIGHT_CONFIG_PATH")
    configured = (file_config or {}).get("playwright_config")
    if explicit or environment:
        selected = explicit or environment
        origin = "flag" if explicit else "env:PLAYWRIGHT_CONFIG_PATH"
        path = Path(selected).resolve()
    elif configured:
        path = ((repo_root or Path.cwd()) / configured).resolve()
        origin = "config:playwright_config"
    else:
        return ExecutionConfig()
    return _load_execution_config(path, origin)


def add_execution_flags(parser: argparse.ArgumentParser) -> None:
    """Share execution selectors between the facade and standalone wrapper."""
    parser.add_argument(
        "--playwright-config", default=None, metavar="PATH",
        help="Browser execution YAML [env: PLAYWRIGHT_CONFIG_PATH]; default: local pytest",
    )
    parser.add_argument(
        "--workers", type=int, default=None, metavar="N",
        help="Max generated-case pytest workers [env: PLAYWRIGHT_XDIST_WORKERS, default: 4]",
    )


def forward_execution_flags(command: list[str], args: argparse.Namespace) -> None:
    """Forward the selected execution config and existing worker override."""
    for name in ("playwright_config", "workers"):
        value = getattr(args, name, None)
        if value is not None:
            command.extend(["--" + name.replace("_", "-"), str(value)])


def prepare_execution(args: argparse.Namespace, repo_root: Path) -> int | None:
    """Validate execution selection before artifact or Fabric resolution."""
    if args.analyzer not in ("playwright", "all", "doctor", "config"):
        return None
    try:
        args.execution_config = resolve_execution_config(
            getattr(args, "playwright_config", None), getattr(args, "file_config", {}), repo_root
        )
    except ConfigError as error:
        print(f"fab-test: {error}", file=sys.stderr)
        return 2
    if args.execution_config.path:
        args.playwright_config = str(args.execution_config.path)
    return None

