"""Resolve where telemetry goes (Eventhouse Shipping §1).

A leaf module on purpose: `fab_test.py` and `eventhouse_logger.py` both need
the answer, and neither should import the other to get it.

The address follows the same precedence every other setting does --
environment variable, then config file, then nothing. There is no CLI flag
for it: a URI is not something anyone types at a prompt, and `--telemetry`
already exists to decide *whether* to ship rather than *where*.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ._config import CONFIG_FILENAME

EVENTHOUSE_URI_VAR = "EVENTHOUSE_URI"
EVENTHOUSE_DATABASE_VAR = "EVENTHOUSE_DATABASE"

# The switch that predates the config file. It stays, and it stays
# authoritative in both directions: an environment that turns telemetry off
# should not be overridden by a config file it does not control.
ENABLE_VAR = "ENABLE_EVENTHOUSE_LOGGING"

# The `telemetry.eventhouse` keys, and the environment variable that
# overrides each. `table` is deliberately absent: it follows from which
# analyzer ran, and a config key would only let the two disagree.
_EVENTHOUSE_KEYS: dict[str, str] = {
    "uri": EVENTHOUSE_URI_VAR,
    "database": EVENTHOUSE_DATABASE_VAR,
}

LAKEHOUSE_WORKSPACE_VAR = "LAKEHOUSE_WORKSPACE"
LAKEHOUSE_NAME_VAR = "LAKEHOUSE_NAME"

# The `telemetry.lakehouse` keys, mirroring `_EVENTHOUSE_KEYS`.
_LAKEHOUSE_KEYS: dict[str, str] = {
    "workspace": LAKEHOUSE_WORKSPACE_VAR,
    "lakehouse": LAKEHOUSE_NAME_VAR,
}


@dataclass(frozen=True)
class EventhouseConfig:
    """Where telemetry would be sent, and which layer said so."""

    uri: str
    database: str
    uri_origin: str
    database_origin: str

    @property
    def configured(self) -> bool:
        """Whether there is a complete destination to send to.

        Both halves or neither. Ingest needs a database as much as a
        cluster, and treating a half-set address as ready is how a run
        reports success against a database nobody named.
        """
        return bool(self.uri and self.database)


def resolve_eventhouse_config(file_config: dict) -> EventhouseConfig:
    """Return the Eventhouse address from the environment or the config file."""
    resolved = {}
    block = _eventhouse_block(file_config)
    for key, env_var in _EVENTHOUSE_KEYS.items():
        from_env = os.environ.get(env_var, "")
        if from_env:
            resolved[key] = (from_env, f"env:{env_var}")
        elif key in block:
            resolved[key] = (block[key], f"{CONFIG_FILENAME}:telemetry.eventhouse.{key}")
        else:
            resolved[key] = ("", "default")
    return EventhouseConfig(
        uri=resolved["uri"][0],
        database=resolved["database"][0],
        uri_origin=resolved["uri"][1],
        database_origin=resolved["database"][1],
    )


class TelemetryDependencyError(Exception):
    """A telemetry sink's SDK is not installed.

    Deliberately not an ``ImportError``: a caller turns this into a warning
    rather than a crash, and catching a bare ImportError there would swallow
    unrelated import bugs in the same handler. Shared across every sink
    (Kusto ingest, OneLake) so each one's "please install the extra" failure
    is catchable the same way.
    """


@dataclass(frozen=True)
class LakehouseConfig:
    """Where Lakehouse telemetry would be sent, and which layer said so."""

    workspace: str
    lakehouse: str
    workspace_origin: str
    lakehouse_origin: str

    @property
    def configured(self) -> bool:
        """Whether there is a complete destination to send to.

        Both halves or neither, mirroring `EventhouseConfig.configured`: a
        workspace without a lakehouse name (or vice versa) names nowhere to
        write.
        """
        return bool(self.workspace and self.lakehouse)


def resolve_lakehouse_config(file_config: dict) -> LakehouseConfig:
    """Return the Lakehouse address from the environment or the config file."""
    resolved = {}
    block = _lakehouse_block(file_config)
    for key, env_var in _LAKEHOUSE_KEYS.items():
        from_env = os.environ.get(env_var, "")
        if from_env:
            resolved[key] = (from_env, f"env:{env_var}")
        elif key in block:
            resolved[key] = (block[key], f"{CONFIG_FILENAME}:telemetry.lakehouse.{key}")
        else:
            resolved[key] = ("", "default")
    return LakehouseConfig(
        workspace=resolved["workspace"][0],
        lakehouse=resolved["lakehouse"][0],
        workspace_origin=resolved["workspace"][1],
        lakehouse_origin=resolved["lakehouse"][1],
    )


@dataclass(frozen=True)
class TelemetryDecision:
    """Whether this run ships telemetry, where to, and why not if not.

    ``requested`` and ``enabled`` differ in exactly one case: the caller asked
    for telemetry and there is nowhere to send it. A real run refuses there;
    a `--dry-run` still previews, because the job of a dry run is to show what
    would happen -- including that the destination is unset.
    """

    requested: bool
    enabled: bool
    eventhouse: EventhouseConfig
    lakehouse: LakehouseConfig
    refusal: str | None = None


def telemetry_decision(*, cli_telemetry: bool | None, file_config: dict) -> TelemetryDecision:
    """Decide whether this run ships telemetry, following the project's one rule.

    Precedence is the documented flag > env > config > default, applied to a
    yes/no question:

    * ``--no-telemetry`` / ``--telemetry`` -- explicit, and wins outright.
    * ``ENABLE_EVENTHOUSE_LOGGING`` -- explicit in both directions. A ``false``
      beats a configured destination, because configuration enables
      *implicitly* and an environment that says no should not be overruled by
      a config file it does not control.
    * A complete ``telemetry.eventhouse`` and/or ``telemetry.lakehouse``
      destination -- the reason to configure one is to send to it. Either
      alone is enough to enable; a run may ship to one, both, or neither.

    ``refusal`` is set only when the caller *asked* for telemetry and there is
    nowhere at all to send it. `ENABLE_EVENTHOUSE_LOGGING=true` with no
    address is not a refusal: that is what every existing caller has today,
    and this epic must not turn their runs into failures.
    """
    eventhouse = resolve_eventhouse_config(file_config)
    lakehouse = resolve_lakehouse_config(file_config)
    any_configured = eventhouse.configured or lakehouse.configured

    if cli_telemetry is False:
        return TelemetryDecision(
            requested=False, enabled=False, eventhouse=eventhouse, lakehouse=lakehouse
        )
    if cli_telemetry is True:
        return TelemetryDecision(
            requested=True,
            enabled=any_configured,
            eventhouse=eventhouse,
            lakehouse=lakehouse,
            refusal=None if any_configured else _missing_destination(eventhouse, lakehouse),
        )

    explicit = os.environ.get(ENABLE_VAR, "").lower()
    if explicit == "true":
        # No refusal: this is what every caller has today, and turning their
        # runs into failures is not a backward-compatible way to ship a wire.
        return TelemetryDecision(
            requested=True, enabled=any_configured, eventhouse=eventhouse, lakehouse=lakehouse
        )
    if explicit == "false":
        return TelemetryDecision(
            requested=False, enabled=False, eventhouse=eventhouse, lakehouse=lakehouse
        )

    return TelemetryDecision(
        requested=any_configured,
        enabled=any_configured,
        eventhouse=eventhouse,
        lakehouse=lakehouse,
    )


def _missing_destination(eventhouse: EventhouseConfig, lakehouse: LakehouseConfig) -> str:
    """Return why --telemetry cannot be honoured, naming both ways to fix each destination."""
    missing = [
        f"{name} (set `telemetry.eventhouse.{name}` in {CONFIG_FILENAME} or {var})"
        for name, var, value in (
            ("uri", EVENTHOUSE_URI_VAR, eventhouse.uri),
            ("database", EVENTHOUSE_DATABASE_VAR, eventhouse.database),
        )
        if not value
    ] + [
        f"{name} (set `telemetry.lakehouse.{name}` in {CONFIG_FILENAME} or {var})"
        for name, var, value in (
            ("workspace", LAKEHOUSE_WORKSPACE_VAR, lakehouse.workspace),
            ("lakehouse", LAKEHOUSE_NAME_VAR, lakehouse.lakehouse),
        )
        if not value
    ]
    return (
        "--telemetry was requested but no Eventhouse or Lakehouse destination is configured. "
        f"Missing: {'; '.join(missing)}."
    )


def eventhouse_rows(file_config: dict) -> list[dict[str, str]]:
    """Return `config --show` rows for telemetry, or none when unconfigured.

    Unconfigured telemetry adds no rows. An absent optional section is a
    default, not a setting worth naming -- the same reason an absent
    metadata override is not warned about.
    """
    resolved = resolve_eventhouse_config(file_config)
    if not (resolved.uri or resolved.database):
        return []
    return [
        {
            "key": "telemetry.eventhouse.uri",
            "value": resolved.uri,
            "origin": resolved.uri_origin,
        },
        {
            "key": "telemetry.eventhouse.database",
            "value": resolved.database,
            "origin": resolved.database_origin,
        },
    ]


def _eventhouse_block(file_config: dict) -> dict:
    """Return the `telemetry.eventhouse` mapping, or an empty one.

    Tolerant of a wrong shape because `validate_config` has already refused
    anything malformed by the time a run reaches here; this only has to
    avoid raising when called on a config that never went through it.
    """
    telemetry = file_config.get("telemetry")
    if not isinstance(telemetry, dict):
        return {}
    block = telemetry.get("eventhouse")
    return block if isinstance(block, dict) else {}


def _lakehouse_block(file_config: dict) -> dict:
    """Return the `telemetry.lakehouse` mapping, or an empty one. Mirrors `_eventhouse_block`."""
    telemetry = file_config.get("telemetry")
    if not isinstance(telemetry, dict):
        return {}
    block = telemetry.get("lakehouse")
    return block if isinstance(block, dict) else {}
