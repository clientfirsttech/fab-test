"""Telling a report's PBIR rules from its slicer contract's (PBIR Slicer Default State epic).

`fab-test pbir` checks two rule sets in one PBIR Inspector run: the PBIR rules
every report gets (packaged, or --rules) and the `CONTRACT.*` rules compiled
from the report's own slicer contract. These helpers let the run say which
contract paired, or why none did, split its counts by source, and tag every
envelope row with `source`: `rules` or `contract`.
"""

from __future__ import annotations

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
    """Each finding or test result with the rule set it came from."""
    return [{**row, "source": source_of(row.get("rule", ""))} for row in rows]


def contract_line(report: Path, contract_summary: Path | None) -> str:
    """The run header's line: which contract paired with ``report``, or why none did."""
    if contract_summary is not None:
        summary = json.loads(contract_summary.read_text(encoding="utf-8"))
        checks = _count(len(summary.get("rules", [])), "slicer check")
        if summary.get("navigators"):
            checks += f", {_count(len(summary['navigators']), 'bookmark navigator')}"
        return f"📜 Slicer contract: {_relative(Path(summary['file']))} ({checks})"
    logical_id = report_logical_id(report)
    if not logical_id:
        return "📜 Slicer contract: none (the report has no .platform logicalId to pair on; pass --contract FILE)"
    return (f"📜 Slicer contract: none (no *.odcs.yaml under --artifact-dir has fabTestReport {logical_id}; "
            "only the PBIR rules run)")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _relative(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return path


def count_line(findings: list[dict[str, Any]], paired: bool) -> str:
    """How many findings came from each rule set; the contract's count shows even at 0, so a pass is visible."""
    from_contract = sum(source_of(f.get("rule", "")) == CONTRACT for f in findings)
    line = f"{len(findings) - from_contract} from the PBIR rules"
    return f"{line}, {from_contract} from the slicer contract" if paired else line
