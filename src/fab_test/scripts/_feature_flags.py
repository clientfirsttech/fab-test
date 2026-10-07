"""Feature flags for analyzers that have merged but not released.

Feature Flags epic (tasks/feature-flags-epic.md). Unlike HIDDEN_ANALYZERS,
which only keeps a name off the menus, a flag that is off means the command
does not run: its subcommand is a stub that exits 2, its tool is never
resolved or installed, and no bundle or report lists it.

A flag is read from ``FAB_TEST_ENABLE_<NAME>`` (``1``/``true``/``yes``), at
call time rather than import time, so a test can flip it with monkeypatch.
Each entry is deleted once its feature ships: flip the default to ``True``,
release, then remove the row.
"""

import argparse
import os

# Registry key -> default. Off until the epic that owns it releases.
_FEATURES: dict[str, bool] = {
    "data_agent": False,
    "sqldb_test": False,
}

# Registry key -> every CLI spelling the feature's subcommand will accept.
# The stubs reserve these now, so a disabled feature answers with its flag
# rather than "unknown analyzer" or a "did you mean" for some other command.
FEATURE_SPELLINGS: dict[str, tuple[str, ...]] = {
    "data_agent": ("data-agent", "agent", "data_agent"),
    "sqldb_test": ("sqldb-test", "sqldb_test"),
}

_TRUTHY = frozenset({"1", "true", "yes"})


def env_var(name: str) -> str:
    """Return the environment variable that turns feature ``name`` on."""
    return f"FAB_TEST_ENABLE_{name.upper()}"


def is_enabled(name: str) -> bool:
    """Return whether ``name`` may run. Names without a flag are always enabled."""
    if name not in _FEATURES:
        return True
    raw = os.environ.get(env_var(name))
    if raw is None:
        return _FEATURES[name]
    return raw.strip().lower() in _TRUTHY


def disabled_analyzers() -> frozenset[str]:
    """Return the registry keys whose feature flag is currently off."""
    return frozenset(name for name in _FEATURES if not is_enabled(name))


def not_enabled_message(name: str) -> str:
    """The one message every surface gives for a disabled feature."""
    display = FEATURE_SPELLINGS.get(name, (name,))[0]
    return f"{display} is not enabled in this release. Set {env_var(name)}=1 to enable it."


class _DisabledFeatureParser(argparse.ArgumentParser):
    """A subparser that accepts any arguments and refuses to run.

    ``argparse.REMAINDER`` cannot swallow option-shaped arguments
    (``--help``, ``--format json``), so this overrides ``parse_known_args``
    instead. Exiting here, during parsing, is what guarantees a disabled
    command touches no config, credential, telemetry, or results folder --
    and it covers ``fab-test help <name>``, which parses ``<name> --help``.
    """

    feature: str = ""

    def parse_known_args(self, args=None, namespace=None):  # noqa: ARG002 -- argparse's signature
        self.exit(2, f"  ✗ fab-test: {not_enabled_message(self.feature)}\n")


def add_disabled_stubs(subs: argparse._SubParsersAction) -> frozenset[str]:
    """Register a stub for each disabled feature; return the spellings used.

    ``help`` is omitted (not ``argparse.SUPPRESS``) so the stub stays out of
    the subcommand listing, the same way pql-lint is hidden. Once a
    feature's real builder exists, its epic registers that instead whenever
    ``is_enabled`` is true.
    """
    spellings: set[str] = set()
    for name in sorted(disabled_analyzers()):
        primary, *aliases = FEATURE_SPELLINGS[name]
        stub = subs.add_parser(primary, aliases=aliases, add_help=False)
        stub.__class__ = _DisabledFeatureParser
        stub.feature = name
        spellings.update(FEATURE_SPELLINGS[name])
    return frozenset(spellings)
