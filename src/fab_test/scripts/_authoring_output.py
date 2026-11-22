"""Shared input, terminal and output helpers for artifact authoring commands."""

import argparse
import json
import os
import sys
from typing import Any

from ._cli_utils import ARTIFACT_DIR_HELP, ARTIFACT_HELP, FORMAT_HELP
from ._config import VERBOSITY_LEVELS, merged_file_config, resolve_setting, validate_config, verbosity_level
from ._metadata import default_repo_root

FORMATS = ("text", "json")


def file_config(explicit_path: str | None = None) -> dict:
    """Resolve the same discovered file configuration as the analyzer."""
    root = default_repo_root()
    config = merged_file_config(root, root / "pyproject.toml", explicit_path)[0]
    validate_config(config)
    return config


def add_input_flags(parser: argparse.ArgumentParser, target_help: str) -> None:
    """Add the analyzer's common artifact and format inputs."""
    parser.add_argument("target", nargs="?", default=None, metavar="TARGET", help=target_help)
    parser.add_argument("--artifact", default=None, metavar="STEM", help=ARTIFACT_HELP)
    parser.add_argument("--artifact-dir", default=None, metavar="DIR", help=ARTIFACT_DIR_HELP)
    parser.add_argument("--format", choices=list(FORMATS), default=None, dest="output_format", help=FORMAT_HELP)


def resolve_inputs(args: argparse.Namespace) -> None:
    """Resolve artifact and output defaults after parsing."""
    config = file_config(getattr(args, "config", None))
    args.file_config = config
    args.artifact_dir_given = args.artifact_dir is not None
    args.artifact_dir = args.artifact_dir or str(config.get("artifact_dir", default_repo_root()))
    if args.output_format is None:
        args.output_format = config.get("format") if config.get("format") in FORMATS else "text"


def console(stream: Any) -> bool:
    """On Windows, distinguish an actual console from the null device."""
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(wintypes.DWORD())))
    except (AttributeError, ImportError, OSError, ValueError):
        return False


def can_ask(console_check=console) -> bool:
    """Ask only when both the input and prompt streams are real terminals."""
    streams = (sys.stdin, sys.stderr)
    if not all(stream.isatty() for stream in streams):
        return False
    return os.name != "nt" or all(console_check(stream) for stream in streams)


def level(args: argparse.Namespace) -> str:
    """Resolve the same verbosity precedence as analyzer runs."""
    if args.quiet:
        return "summary"
    if args.verbose:
        return "verbose"
    value, _origin = resolve_setting("verbosity", cli_value=None, env_var="ANALYZER_VERBOSITY",
                                     file_config=args.file_config, packaged_default="default", cast=verbosity_level)
    value = str(value).strip().lower()
    return {"debug": "verbose"}.get(value, value) if value in VERBOSITY_LEVELS else "default"


def next_command(args: argparse.Namespace, command: str) -> str:
    """Carry the typed target and artifact directory into the next command."""
    target = args.target or args.artifact
    words = [*([target] if target else []),
             *(["--artifact-dir", args.artifact_dir] if getattr(args, "artifact_dir_given", False) else [])]
    return " ".join([command, *(f'"{word}"' if " " in word else word for word in words)])


def print_payload(args: argparse.Namespace, payload: dict, as_text, asked_for: bool = False, as_line=None) -> None:
    """Print JSON, detailed text, or the quiet result line as requested."""
    if args.output_format == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif asked_for or level(args) != "summary":
        print(as_text(payload))
    elif as_line:
        print(as_line(payload))
