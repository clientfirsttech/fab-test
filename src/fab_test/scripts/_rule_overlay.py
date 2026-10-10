"""Apply config-driven overlays to a packaged BPA/PBIR ruleset (Config Consolidation §6-7).

An overlay never forks an upstream rules file -- it applies deltas
(disable, severity override, extend) on top of it at run time, so tuning
one rule out of dozens never means committing a forked copy that then
drifts from upstream forever.

BPA (`apply_overlay`), PBIR Inspector (`apply_pbir_overlay`), and RDL
(`apply_rdl_overlay`) use genuinely different rule-file shapes, so each
gets its own function rather than forcing one shape-detecting function to
do all three:

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
- RDL (fab-test's own in-house catalog): `{"rules": [...]}`, each rule
  keyed by `"id"`, with its own `"disabled"` boolean and a `"severity"`
  string already using the envelope's own vocabulary
  (`"error"`/`"warning"`/`"info"`) -- unlike PBIR's `logType`, all three
  labels are accepted since nothing about the catalog rules them out.
  Disabling sets `"disabled": true` in place, same as PBIR.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

_SEVERITY_LABELS: dict[str, int] = {"info": 1, "warning": 2, "error": 3}


class RuleOverlayError(Exception):
    """Raised when an overlay names a rule ID that doesn't exist upstream,
    an unrecognized severity label, or a setting that isn't a declared,
    in-range number.
    """


def _quote(value: Any) -> str:
    """A config value as repr(), cut short: safe to echo to a terminal,
    since repr escapes control characters."""
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _validated_setting(label: str, value: Any, spec: dict[str, Any]) -> int | float:
    """Return ``value`` if it is a finite number of the declared type inside
    the declared range. Never coerces: "80" and True are refused, not read
    as 80 and 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuleOverlayError(f"rules.rdl.settings.{label} must be a finite number, got {_quote(value)}")
    if spec["type"] == "integer" and not isinstance(value, int):
        raise RuleOverlayError(f"rules.rdl.settings.{label} must be a whole number, got {_quote(value)}")
    if not spec["min"] <= value <= spec["max"]:
        raise RuleOverlayError(
            f"rules.rdl.settings.{label} must be between {spec['min']} and {spec['max']}, got {_quote(value)}"
        )
    return value


_MAX_REASON_LENGTH = 200


def _validated_reasons(disable: Any) -> dict[str, str]:
    """``{rule ID: reason}`` from a disable map; {} for the plain list form.
    A reason is shown in reports and telemetry, so it must be one short line
    of printable text."""
    if not isinstance(disable, dict):
        return {}
    for rule_id, reason in disable.items():
        if not isinstance(reason, str) or not reason.strip():
            raise RuleOverlayError(f"rules.rdl.disable.{rule_id}: the reason must be text, got {_quote(reason)}")
        if len(reason) > _MAX_REASON_LENGTH or not reason.isprintable():
            raise RuleOverlayError(
                f"rules.rdl.disable.{rule_id}: the reason must be one line of at most "
                f"{_MAX_REASON_LENGTH} printable characters, got {_quote(reason)}"
            )
    return {rule_id: reason.strip() for rule_id, reason in disable.items()}


def _apply_rdl_settings(rules: list[dict[str, Any]], settings: Any) -> None:
    """Set each overridden parameter on its (already copied) rule, in place."""
    if not isinstance(settings, dict) or not all(isinstance(v, dict) for v in settings.values()):
        raise RuleOverlayError(
            "rules.rdl.settings must map a rule ID to {setting: number}, e.g. {QRY-07: {max_lines: 80}}"
        )
    tunable = {rule["id"]: rule for rule in rules if rule.get("settings")}
    for rule_id, values in settings.items():
        rule = tunable.get(rule_id)
        if rule is None:
            raise RuleOverlayError(
                f"rules.rdl.settings: {_quote(rule_id)} has nothing to tune; "
                f"tunable rules: {', '.join(sorted(tunable))}"
            )
        for name, value in values.items():
            spec = rule["settings"].get(name)
            if spec is None:
                raise RuleOverlayError(
                    f"rules.rdl.settings.{rule_id}: unknown setting {_quote(name)}; "
                    f"valid settings: {', '.join(sorted(rule['settings']))}"
                )
            rule[name] = _validated_setting(f"{rule_id}.{name}", value, spec)


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


def apply_rdl_overlay(upstream_path: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    """Apply ``overlay`` to the RDL rules document at ``upstream_path``
    (``{"rules": [...]}``), returning the resolved document. Never mutates
    or rewrites ``upstream_path``.

    Same ``overlay`` keys and disable convention as ``apply_pbir_overlay``,
    but ``severity`` sets the catalog's own ``"severity"`` field directly,
    and accepts any of the envelope's three labels
    (``"error"``/``"warning"``/``"info"``) -- the RDL catalog has no
    PBIR-style restriction to rule out ``"info"``.
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
    reasons = _validated_reasons(overlay.get("disable"))

    resolved_rules = []
    for original_rule in rules:
        rule = dict(original_rule)
        if rule["id"] in disable_ids:
            rule["disabled"] = True
            if rule["id"] in reasons:
                rule["disabled_reason"] = reasons[rule["id"]]
        label = severity_map.get(rule["id"])
        if label is not None:
            if label not in _SEVERITY_LABELS:
                raise RuleOverlayError(
                    f"unknown severity label '{label}' for rule '{rule['id']}' "
                    f"(expected one of: {', '.join(_SEVERITY_LABELS)})"
                )
            rule["severity"] = label
        resolved_rules.append(rule)

    if "settings" in overlay:
        _apply_rdl_settings(resolved_rules, overlay["settings"])

    extend_path = overlay.get("extend")
    if extend_path:
        extra = json.loads(Path(extend_path).read_text(encoding="utf-8"))
        resolved_rules.extend(extra.get("rules", []) if isinstance(extra, dict) else extra)

    return {**data, "rules": resolved_rules}



_APPLY = {"bpa": apply_overlay, "pbir": apply_pbir_overlay, "rdl": apply_rdl_overlay}


def validate_rule_overlays(rules: dict[str, Any], rule_files: dict[str, Path]) -> None:
    """Apply each configured overlay once to its packaged file (``rule_files``,
    keyed bpa/pbir/rdl) so a bad rule ID, label, setting or extend file stops
    the run before anything starts, not mid-run. Section and key names are
    already checked by ``_config.validate_config``. Raises RuleOverlayError.
    """
    for section, overlay in rules.items():
        try:
            _APPLY[section](rule_files[section], overlay)
        except (OSError, ValueError) as exc:
            raise RuleOverlayError(f"rules.{section}.extend could not be read: {exc}") from exc
