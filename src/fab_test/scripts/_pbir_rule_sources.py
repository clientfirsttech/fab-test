"""Telling a report's PBIR rules from its slicer contract's (PBIR Slicer Default State epic).

`fab-test pbir` checks two rule sets in one PBIR Inspector run: the PBIR rules
every report gets (packaged, or --rules) and the `CONTRACT.*` rules compiled
from the report's own slicer contract. These helpers let the run say which
contract paired, or why none did, split its counts by source, and tag every
envelope row with `source`: `rules` or `contract`.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from ._slicer_contract_run import report_logical_id
from ._slicer_rules import RULE_PREFIX

RULES, CONTRACT = "rules", "contract"


def source_of(rule_id: str) -> str:
    """`contract` for a rule compiled from a slicer contract, `rules` for everything else."""
    return CONTRACT if rule_id.startswith(RULE_PREFIX) else RULES


def tag_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each finding or test result with the rule set it came from; a contract row's message is what it found."""
    tagged = [{**row, "source": source_of(row.get("rule", ""))} for row in rows]
    return [{**row, "message": found(row.get("message", ""))} if row["source"] == CONTRACT else row for row in tagged]


def found(message: str) -> str:
    """What a rule found, without PBIR Inspector's `Rule "…" FAILED with result: [...], expected: []` wrapper."""
    start, end = message.find("FAILED with result: ["), message.rfind("], expected:")
    with contextlib.suppress(ValueError):
        result = json.loads(message[start + len("FAILED with result: "):end + 1]) if 0 <= start < end else None
        if isinstance(result, list) and result and all(isinstance(r, str) for r in result):
            return "; ".join(result)
    return message


def contract_line(report: Path, contract_summary: Path | None) -> str:
    """The run header's line: which contract paired with ``report``, or why none did."""
    if contract_summary is not None:
        name, checks = describe(json.loads(contract_summary.read_text(encoding="utf-8")))
        return f"📜 Slicer contract: {name} ({checks})"
    return f"📜 Slicer contract: none ({unpaired_reason(report)})"


def unpaired_reason(report: Path) -> str:
    """Why no contract paired with ``report``."""
    logical_id = report_logical_id(report)
    if not logical_id:
        return "the report has no .platform logicalId to pair on; pass --contract FILE"
    return f"no *.odcs.yaml under --artifact-dir has fabTestReport {logical_id}; only the PBIR rules run"


def describe(summary: dict) -> tuple[str, str]:
    """A paired contract's file, relative where it can be, and its checks: `2 slicer checks, 1 bookmark navigator`."""
    checks = _count(len(summary.get("rules", [])), "slicer check")
    if summary.get("navigators"):
        checks += f", {_count(len(summary['navigators']), 'bookmark navigator')}"
    return str(_relative(Path(summary["file"]))), checks


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _relative(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return path


_RANK = {"error": 0, "warning": 1, "pass": 2}


def contract_rows(summary: dict, results: list[dict[str, Any]]) -> list[tuple]:
    """(rule, severity, page, expects, found, status) per contract check: its worst result across the pages
    it ran on, what it found when that wasn't a pass, and the page-exists checks the contract adds."""
    worst: dict[str, tuple[str, str]] = {}
    for r in results:
        status = r.get("status", "pass")
        if r.get("source") == CONTRACT and _RANK.get(status, 3) < _RANK.get(worst.get(r["rule"], ("",))[0], 3):
            worst[r["rule"]] = (status, "" if status == "pass" else r.get("message", ""))
    rows = []
    checks = [(r["id"], r["severity"], r["page"], f"{r['field']} {expects(r['check'], r['expected'])}")
              for r in summary.get("rules", [])]
    checks += [(n["id"], n["severity"], n["page"], f"bookmark navigator opens with {n['expected'] or 'no bookmark'}")
               for n in summary.get("navigators", [])]
    for rule_id, severity, page, wanted in checks:
        status, found_text = worst.pop(RULE_PREFIX + rule_id, ("not run", ""))
        rows.append((RULE_PREFIX + rule_id, severity, page, wanted, found_text, status))
    rows += [(rule, "error", rule.removeprefix(f"{RULE_PREFIX}page."), "the page exists", found_text, status)
             for rule, (status, found_text) in worst.items()]
    return rows


def expects(check: str, expected: Any) -> str:
    """A check's expected opening state in words, as Desktop shows it."""
    if check == "selected":
        values = "Select all" if expected == "all" else ", ".join(map(str, expected)) or "nothing ticked"
        return f"opens with {values}"
    if check == "contains":
        return f"opens containing {', '.join(map(str, expected))}" if expected else "opens with nothing typed"
    if check == "relative":
        return f"opens with {expected['range']} {expected['duration']} {expected['period']}"
    start, end = expected.get("from"), expected.get("to")
    if start and end:
        return f"opens from {start} to {end}"
    return f"opens up to {end}" if end else f"opens from {start} on"


def count_line(findings: list[dict[str, Any]], paired: bool) -> str:
    """How many findings came from each rule set; the contract's count shows even at 0, so a pass is visible."""
    from_contract = sum(source_of(f.get("rule", "")) == CONTRACT for f in findings)
    line = f"{len(findings) - from_contract} from the PBIR rules"
    return f"{line}, {from_contract} from the slicer contract" if paired else line
