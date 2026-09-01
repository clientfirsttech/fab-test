"""Apply config-driven overlays to a packaged BPA/PBIR ruleset (Config Consolidation §6-7).

An overlay never forks an upstream rules file -- it applies deltas
(disable, severity override, extend) on top of it at run time, so tuning
one rule out of dozens never means committing a forked copy that then
drifts from upstream forever.

BPA (`apply_overlay`) and PBIR Inspector (`apply_pbir_overlay`) use
genuinely different rule-file shapes, so each gets its own function
rather than forcing one shape-detecting function to do both:

- BPA: a bare JSON array of rule objects keyed by `"ID"`, numeric
  `"Severity"` (Tabular Editor's own scale: 1 = info, 2 = warning,
  3 = error -- a violation at 3+ fails a `-V` command-line run, 2 warns
  without failing, 1 is informational only). Disabling removes the rule.
- PBIR Inspector: `{"rules": [...]}`, each rule keyed by `"id"`, with its
  own `"disabled"` boolean and a `"logType"` string ("warning"/"error" --
  "info" is never observed in the packaged rules file, so it's rejected
  rather than passed through unverified). Disabling sets `"disabled": true`
  in place -- the format's own documented convention -- rather than
  removing the rule.
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


_PBIR_LOG_TYPES = {"warning", "error"}


def apply_pbir_overlay(upstream_path: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    """Apply ``overlay`` to the PBIR Inspector rules document at
    ``upstream_path`` (``{"rules": [...]}``), returning the resolved
    document. Never mutates or rewrites ``upstream_path``.

    Same ``overlay`` keys as ``apply_overlay``, but ``disable`` sets
    ``"disabled": true`` in place rather than removing the rule, and
    ``severity`` sets ``"logType"`` directly to ``"warning"``/``"error"``
    (PBIR already uses these labels; ``"info"`` is rejected).
    """
    data = json.loads(upstream_path.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    known_ids = {rule["id"] for rule in rules}

    disable_ids = set(overlay.get("disable", []))
    severity_map = overlay.get("severity", {})
    unmatched = sorted((disable_ids | severity_map.keys()) - known_ids)
    if unmatched:
        raise RuleOverlayError(
            f"overlay names rule ID(s) not found in {upstream_path.name}: "
            f"{', '.join(unmatched)}"
        )

    resolved_rules = []
    for original_rule in rules:
        rule = dict(original_rule)
        if rule["id"] in disable_ids:
            rule["disabled"] = True
        label = severity_map.get(rule["id"])
        if label is not None:
            if label not in _PBIR_LOG_TYPES:
                raise RuleOverlayError(
                    f"unknown severity label '{label}' for rule '{rule['id']}' "
                    f"(expected one of: {', '.join(sorted(_PBIR_LOG_TYPES))})"
                )
            rule["logType"] = label
        resolved_rules.append(rule)

    extend_path = overlay.get("extend")
    if extend_path:
        extra = json.loads(Path(extend_path).read_text(encoding="utf-8"))
        resolved_rules.extend(extra.get("rules", []) if isinstance(extra, dict) else extra)

    return {**data, "rules": resolved_rules}
