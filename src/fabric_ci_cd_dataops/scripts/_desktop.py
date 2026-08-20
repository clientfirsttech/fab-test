"""Detect running Power BI Desktop instances (Local Desktop First Run §3).

Power BI Desktop opens a local Analysis Services instance on a random port
for every open file, recorded in a `msmdsrv.port.txt` file under
`%LOCALAPPDATA%\\Microsoft\\Power BI Desktop\\AnalysisServicesWorkspaces`.

Single-instance support only: correlating a specific port to a specific
open file when several Desktop windows are open at once needs a reliable
per-window signal (e.g. the Power BI Desktop Bridge), which isn't wired in
yet. When more than one instance is running, every port is still reported
but `open_file_path` is left unresolved rather than guessed.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_FILE_ARG_PATTERN = re.compile(r'"([^"]+\.pbi[xp])"|(\S+\.pbi[xp])', re.IGNORECASE)


@dataclass
class DesktopInstance:
    """One running Power BI Desktop instance."""

    port: int
    open_file_path: Path | None


class DesktopMatchError(RuntimeError):
    """Raised when a running Desktop instance can't be unambiguously matched
    to an artifact: none has the file open, or more than one does.
    """


def _default_workspaces_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    return Path(local_app_data) / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces"


def _read_port(port_file: Path) -> int | None:
    try:
        text = port_file.read_text(encoding="utf-16").strip()
        return int(text)
    except (OSError, ValueError, UnicodeError):
        return None


def _discover_ports(workspaces_root: Path) -> list[int]:
    if not workspaces_root.exists():
        return []
    ports = (_read_port(p) for p in sorted(workspaces_root.glob("*/Data/msmdsrv.port.txt")))
    return [port for port in ports if port is not None]


def desktop_ports(workspaces_root: Path | None = None) -> list[int]:
    """Return the ports of running Power BI Desktop instances, presence only.

    The cheap half of `detect_desktop_instances`: it answers "is anything
    running?" with a directory scan and never resolves which file each
    instance has open, which costs a PowerShell call. `check_readiness`
    needs exactly this much and is contractually forbidden from spawning a
    subprocess. Returns an empty list off Windows, as `_discover_ports`
    would find no workspaces root there anyway.
    """
    if platform.system() != "Windows":
        return []
    root = workspaces_root if workspaces_root is not None else _default_workspaces_root()
    return _discover_ports(root)


def _extract_file_arg(command_line: str) -> Path | None:
    """Pull the .pbix/.pbip argument off a PBIDesktop.exe command line, if present."""
    match = _FILE_ARG_PATTERN.search(command_line)
    if not match:
        return None
    return Path(match.group(1) or match.group(2))


def _running_desktop_file_path() -> Path | None:
    """Return the open file path when exactly one PBIDesktop.exe process is running.

    A file opened by double-click is passed to PBIDesktop.exe as a command-line
    argument, so its path can be read back from the process list. Returns
    ``None`` on any failure so detection degrades gracefully instead of raising.
    """
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='PBIDesktop.exe'\" "
                "| Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    return _extract_file_arg(lines[0])


def bridge_cli_path() -> str | None:
    """Return the resolved path of the Power BI Desktop Bridge CLI (``powerbi-desktop``)
    if it's on PATH, else ``None``.

    Presence only -- deliberately never invokes the CLI. Its actual command
    output schema (``status``, ``screenshot``, ...) isn't verified in this
    codebase yet; see the epic file for the task 6-8 follow-up.
    """
    return shutil.which("powerbi-desktop")


def detect_desktop_instances(workspaces_root: Path | None = None) -> list[DesktopInstance]:
    """Return every running Power BI Desktop instance's port and open file.

    Returns an empty list on a non-Windows platform or when nothing is
    running, without raising.
    """
    if platform.system() != "Windows":
        return []
    root = workspaces_root if workspaces_root is not None else _default_workspaces_root()
    ports = _discover_ports(root)
    if not ports:
        return []
    file_path = _running_desktop_file_path() if len(ports) == 1 else None
    return [DesktopInstance(port=port, open_file_path=file_path) for port in ports]


def match_instance_to_artifact(
    instances: list[DesktopInstance], target_file: Path
) -> DesktopInstance:
    """Return the one running instance with ``target_file`` open.

    Never guesses: raises ``DesktopMatchError`` naming ``target_file`` when no
    instance has it open, or naming every matching port when more than one
    does.
    """
    target = target_file.resolve()
    matches = [
        instance
        for instance in instances
        if instance.open_file_path is not None and instance.open_file_path.resolve() == target
    ]
    if not matches:
        raise DesktopMatchError(
            f"No running Power BI Desktop instance has {target} open. "
            "Open it in Desktop and try again."
        )
    if len(matches) > 1:
        ports = ", ".join(str(instance.port) for instance in matches)
        raise DesktopMatchError(
            f"Multiple running Desktop instances have {target} open (ports: {ports}). "
            "Close all but one and try again."
        )
    return matches[0]
