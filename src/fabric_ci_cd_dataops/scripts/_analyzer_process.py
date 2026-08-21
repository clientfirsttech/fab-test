"""Run an analyzer's external tool and classify how it went.

Every wrapper had the same three exception handlers in the same order —
timeout, executable missing, anything else — each building a message,
writing a failure envelope, printing `::error::`, and returning 1. The
only real differences were the wording.

Collapsing the structure here means a new wrapper cannot accidentally
handle two of the three, and a change to how a failure is classified
happens once. Wording stays with each caller, because the messages are
part of each analyzer's contract with its user and are asserted by tests.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessOutcome:
    """The result of trying to run an analyzer's tool.

    ``status`` is empty when the process ran to completion — whatever its
    exit code, which is the wrapper's to interpret. A non-empty status
    means the process produced no usable output at all, and carries the
    envelope status to record: ``"timeout"`` or ``"error"``.
    """

    proc: subprocess.CompletedProcess | None
    status: str
    message: str

    @property
    def failed(self) -> bool:
        """Whether the tool failed to run, as opposed to running and finding things."""
        return bool(self.status)


def run_tool(
    command: list[str],
    *,
    timeout: int,
    label: str,
    missing_message: str,
    timeout_message: str = "",
    env: dict[str, str] | None = None,
) -> ProcessOutcome:
    """Run ``command``, mapping the three ways it can fail to a status.

    ``stdin`` is closed rather than inherited: an analyzer that decides to
    prompt would otherwise hang a CI job until the timeout, turning a
    misconfiguration into a slow failure instead of an immediate one.

    Output is decoded as UTF-8 with ``errors="replace"`` rather than the
    locale default. On Windows that default is cp1252, and a tool emitting
    anything outside it crashes `subprocess`'s reader thread with a
    `UnicodeDecodeError` that no caller can catch — the traceback surfaces
    from a background thread with the run already ruined. Replacing an
    undecodable byte loses a character; not replacing it loses the run.

    Never raises, and deliberately catches everything. A wrapper's job is
    to produce an envelope describing what happened; an exception escaping
    here would leave no envelope at all, which is the one outcome a caller
    cannot interpret.
    """
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        minutes = timeout // 60
        spent = f"{minutes} minutes" if minutes else f"{timeout} seconds"
        return ProcessOutcome(
            None, "timeout", timeout_message or f"{label} timed out after {spent}"
        )
    except FileNotFoundError:
        return ProcessOutcome(None, "error", missing_message)
    except Exception as exc:  # noqa: BLE001 - wrapper boundary; failures become an envelope
        return ProcessOutcome(None, "error", f"Unexpected error running {label}: {exc}")
    return ProcessOutcome(proc, "", "")
