"""Apply config-driven overlays to a packaged BPA ruleset (Config Consolidation §6).

An overlay never forks the upstream rules file -- it applies deltas
(disable, severity override, extend) on top of it at run time, so tuning
one rule out of 72+ never means committing a forked copy that then drifts
from upstream forever.

Severity follows Tabular Editor's own scale: 1 = info, 2 = warning,
3 = error (a rule violation at severity 3+ fails a `-V` command-line run;
2 warns without failing; 1 is informational only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SEVERITY_LABELS: dict[str, int] = {"info": 1, "warning": 2, "error": 3}


class RuleOverlayError(Exception):
    """Raised when an overlay names a rule ID that doesn't exist upstream,
    or an unrecognized severity label.
    """


def _load_rules(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_overlay(upstream_path: Path, overlay: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply ``overlay`` to the ruleset at ``upstream_path``, returning the
    resolved rules. Never mutates or rewrites ``upstream_path``.

    ``overlay`` keys (all optional):
      - ``disable``: list of rule IDs to remove.
      - ``severity``: dict mapping rule ID to ``"info"``/``"warning"``/``"error"``.
      - ``extend``: path to a JSON file of additional rule objects to append.

    Raises RuleOverlayError listing every rule ID in ``disable``/``severity``
    that doesn't exist upstream, or naming an unrecognized severity label.
    """
    rules = _load_rules(upstream_path)
    known_ids = {rule["ID"] for rule in rules}

    disable_ids = set(overlay.get("disable", []))
    severity_map = overlay.get("severity", {})
    unmatched = sorted((disable_ids | severity_map.keys()) - known_ids)
    if unmatched:
        raise RuleOverlayError(
            f"overlay names rule ID(s) not found in {upstream_path.name}: "
            f"{', '.join(unmatched)}"
        )

    resolved = [dict(rule) for rule in rules if rule["ID"] not in disable_ids]
    for rule in resolved:
        label = severity_map.get(rule["ID"])
        if label is None:
            continue
        if label not in _SEVERITY_LABELS:
            raise RuleOverlayError(
                f"unknown severity label '{label}' for rule '{rule['ID']}' "
                f"(expected one of: {', '.join(_SEVERITY_LABELS)})"
            )
        rule["Severity"] = _SEVERITY_LABELS[label]

    extend_path = overlay.get("extend")
    if extend_path:
        resolved.extend(_load_rules(Path(extend_path)))

    return resolved
