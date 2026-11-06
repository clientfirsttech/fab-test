"""Printers for the administrative commands: ``list``, ``auth status``, ``doctor``,
``doctor --local`` and ``config --show``.

They share nothing with the per-run summary beyond colour helpers, and each is
a pure ``rows -> stdout -> exit code`` function, so they live apart from the
summary tables that every analyzer run goes through.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tabulate import tabulate

from ._cli_utils import CHECKOUT_REMEDIATION, skipped_checkout_lines
from ._table_style import TABLE_FORMAT
from .fab_test_summary import _paint, color_enabled

# A `local/NAME` target selects the `desktop` scope, a name kept in run.json
# and `--format json`; the table uses the prefix a person types.
_SCOPE_LABELS = {"desktop": "local"}


def _print_list(
    rows: list[dict[str, Any]],
    output_format: str = "text",
    *,
    skipped_checkouts: Sequence[Path] = (),
) -> int:
    """Print the `fab-test list` capability report. Always exits 0.

    ``skipped_checkouts`` is populated only when every discovering
    analyzer matched nothing *and* the scan pruned repositories. A column
    of zeroes otherwise reads as "there is nothing here", which is the
    one thing it does not mean.
    """
    if output_format == "json":
        payload: dict[str, Any] = {
            "analyzers": rows,
            "skipped_checkouts": [str(path) for path in skipped_checkouts],
        }
        if skipped_checkouts:
            payload["remediation"] = CHECKOUT_REMEDIATION
        print(json.dumps(payload, indent=2))
        return 0

    display_rows = [
        (
            r["analyzer"],
            ", ".join(r.get("aliases", ())) or "-",
            r["glob"] or "(repository)",
            str(r["matched_artifacts"]),
            r["required_tool"] or "(none)",
            ", ".join(sorted(_SCOPE_LABELS.get(s, s) for s in r.get("scopes", ()))) or "-",
        )
        for r in rows
    ]
    table = tabulate(
        display_rows,
        headers=("Analyzer", "Aliases", "Glob", "Matched", "Required Tool", "Scopes"),
        tablefmt=TABLE_FORMAT,
        stralign="left",
    )
    print(table)
    for line in skipped_checkout_lines(skipped_checkouts):
        print(line)
    return 0


def _print_auth_status(
    payload: dict[str, Any], output_format: str = "text", *, exit_code: int = 0
) -> int:
    """Print the `fab-test auth status` report and return ``exit_code``.

    Never prints a secret: the payload carries a source name, a tenant,
    and a workspace ID, none of which grant access to anything.
    """
    from ._credentials import redact_secrets

    # Defense in depth: the probe is tested never to put a secret in these
    # fields, but this output is the one place a live credential value
    # could reach a terminal or a CI log, so scrub it on the way out.
    for key in ("detail", "remediation"):
        if payload.get(key):
            payload[key] = redact_secrets(payload[key])

    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    identity = payload["identity"]
    rows = [
        ("identity", identity["source"] or "(none resolved)"),
    ]
    if identity.get("account"):
        rows.append(("account", identity["account"]))
    rows += [
        ("tenant", identity["tenant_id"] or "-"),
        ("verified", "yes" if identity["verified"] else "no"),
    ]
    workspace = payload.get("workspace")
    if workspace:
        rows.append(("workspace", workspace["id"]))
        rows.append(("reachable", "yes" if workspace["reachable"] else "no"))
    print(tabulate(rows, headers=("Check", "Value"), tablefmt=TABLE_FORMAT, stralign="left"))
    if payload.get("detail"):
        print(f"\n  {payload['detail']}")
    if payload.get("remediation"):
        print(f"  → {payload['remediation']}")
    return exit_code


def _print_doctor(rows: list[dict[str, Any]], output_format: str = "text", strict: bool = False) -> int:
    """Print the `fab-test doctor` readiness report.

    Returns 1 on any ``error`` row (with ``strict``, a ``warning`` too). A row
    without ``status`` (telemetry's) derives it from ``ready``, None being
    ``info``: an unconfigured optional feature is not a broken install.
    """
    for r in rows:
        r.setdefault("status", {True: "ready", None: "info"}.get(r["ready"], "error"))
    failing = {"error", "warning"} if strict else {"error"}
    exit_code = 1 if any(r["status"] in failing for r in rows) else 0

    if output_format == "json":
        print(json.dumps({"analyzers": rows}, indent=2))
        return exit_code

    paint = color_enabled()
    for r in rows:
        icon, colour = _DOCTOR_MARKS[r["status"]]
        location = f" — {r['resolved_path']}" if r["resolved_path"] else ""
        reason = _paint(r["reason"], colour, enabled=paint)
        print(f"{icon} {r['analyzer']}: {reason}{location}")
        if r.get("service"):
            print(f"   {r['service']}")
        if r["status"] != "ready" and r["remediation"]:
            # Yellow, not red: this is the actionable half, and colouring it
            # the same as the failure would flatten the distinction.
            print(_paint(f"   → {r['remediation']}", "yellow", enabled=paint))
    return exit_code


_DOCTOR_MARKS = {"ready": ("✅", "green"), "warning": ("⚠", "yellow"), "info": ("ℹ", "yellow"), "error": ("❌", "red")}


def _print_config_show(rows: list[dict[str, Any]], output_format: str = "text") -> int:
    """Print `fab-test config --show`'s effective settings and their origin.

    Always returns 0 -- this is a reporting command, never a failure.
    """
    if output_format == "json":
        print(json.dumps({"settings": rows}, indent=2))
        return 0

    width = max((len(r["key"]) for r in rows), default=0)
    for r in rows:
        print(f"{r['key']:<{width}} = {r['value']!r}  ({r['origin']})")
    return 0


def _print_local_doctor(
    rows: list[dict[str, Any]], would_run: list[str], output_format: str = "text"
) -> int:
    """Print the `fab-test doctor --local` readiness report.

    Returns 0 if at least one local analyzer would run, else 1.
    """
    if output_format == "json":
        print(json.dumps({"checks": rows, "would_run": would_run}, indent=2))
        return 0 if would_run else 1

    for r in rows:
        icon = "✅" if r["ready"] else "❌"
        location = f" — {r['resolved_path']}" if r.get("resolved_path") else ""
        print(f"{icon} {r['check']}: {r['reason']}{location}")
        if not r["ready"] and r.get("remediation"):
            print(f"   → {r['remediation']}")
    if would_run:
        print(f"\nfab-test local would run: {', '.join(would_run)}")
    else:
        print("\nfab-test local: nothing would run -- resolve at least one prerequisite above")
    return 0 if would_run else 1
