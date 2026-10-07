"""Contract tests for feature flags (tasks/feature-flags-epic.md).

Scope
-----
`data-agent` and `sqldb-test` have merged to dev but not released. While a
flag is off, the command is a stub that exits 2 naming its env var, its
tool is never resolved, and no menu, bundle, or report lists it. Turning
the flag on removes the stub. Unlike HIDDEN_ANALYZERS (test_hidden_analyzers.py),
off means the command does not run.

Always passes on any machine: every check is parsing, help text, or a
readiness lookup with the tool probe faked.
"""

import argparse
import json
import os
import subprocess
import sys

import pytest

from fab_test.scripts import _feature_flags as flags
from fab_test.scripts import fab_test_registry as registry
from fab_test.scripts.fab_test_parser import build_parser

_FEATURES = sorted(flags._FEATURES)
_SPELLINGS = [(name, spelling) for name in _FEATURES for spelling in flags.FEATURE_SPELLINGS[name]]


@pytest.fixture(autouse=True)
def _flags_at_defaults(monkeypatch):
    for name in _FEATURES:
        monkeypatch.delenv(flags.env_var(name), raising=False)


def _run_cli(*argv, enable=()):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FAB_TEST_ENABLE_")}
    env.update({flags.env_var(name): "1" for name in enable})
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


# --------------------------------------------------------------------------- #
# The flag table
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_every_flag_defaults_off():
    """A flag exists only while its feature is unreleased; releasing deletes the row."""
    assert flags._FEATURES
    assert not any(flags._FEATURES.values())


@pytest.mark.fab_test
def test_every_flag_declares_its_cli_spellings():
    assert set(flags.FEATURE_SPELLINGS) == set(flags._FEATURES)


@pytest.mark.fab_test
@pytest.mark.parametrize("name", _FEATURES)
@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("TRUE", True), (" yes ", True), ("0", False), ("", False)])
def test_env_var_turns_a_flag_on(monkeypatch, name, raw, expected):
    monkeypatch.setenv(flags.env_var(name), raw)

    assert flags.is_enabled(name) is expected


@pytest.mark.fab_test
def test_env_var_name_is_derived_from_the_registry_key():
    assert flags.env_var("data_agent") == "FAB_TEST_ENABLE_DATA_AGENT"
    assert flags.env_var("sqldb_test") == "FAB_TEST_ENABLE_SQLDB_TEST"


@pytest.mark.fab_test
@pytest.mark.parametrize("name", ["bpa", "playwright", "rdl", "doctor"])
def test_names_without_a_flag_are_always_enabled(name):
    assert flags.is_enabled(name)


# --------------------------------------------------------------------------- #
# The stub subcommand
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
@pytest.mark.parametrize(("name", "spelling"), _SPELLINGS)
@pytest.mark.parametrize("extra", [(), ("--help",), ("--format", "json", "-v"), ("Dev/Sales", "--all")])
def test_disabled_command_exits_2_naming_its_flag(name, spelling, extra):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([spelling, *extra])

    assert exc.value.code == 2


@pytest.mark.fab_test
@pytest.mark.parametrize("name", _FEATURES)
def test_disabled_command_message_names_the_env_var(name):
    spelling = flags.FEATURE_SPELLINGS[name][0]

    result = _run_cli(spelling, "--format", "json")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "is not enabled in this release" in result.stderr
    assert flags.env_var(name) in result.stderr


@pytest.mark.fab_test
def test_disabled_command_writes_no_results(tmp_path):
    output_dir = tmp_path / "results"

    result = _run_cli("data-agent", "--output-dir", str(output_dir))

    assert result.returncode == 2
    assert not output_dir.exists()


@pytest.mark.fab_test
@pytest.mark.parametrize("name", _FEATURES)
def test_help_topic_for_a_disabled_command_exits_2(name):
    result = _run_cli("help", flags.FEATURE_SPELLINGS[name][0])

    assert result.returncode == 2
    assert flags.env_var(name) in result.stderr


@pytest.mark.fab_test
def test_enabling_a_flag_removes_its_stub(monkeypatch):
    monkeypatch.setenv(flags.env_var("data_agent"), "1")
    subs = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))

    assert not set(flags.FEATURE_SPELLINGS["data_agent"]) & set(subs.choices)
    assert "sqldb-test" in subs.choices


# --------------------------------------------------------------------------- #
# Kept off the advertised surface
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_top_level_help_is_identical_with_flags_on_or_off():
    """Stubs add nothing to --help, so a release diff shows only shipped commands."""
    off = _run_cli("--help")
    on = _run_cli("--help", enable=_FEATURES)

    assert off.returncode == on.returncode == 0
    assert off.stdout == on.stdout
    for name in _FEATURES:  # primary spellings; a bare alias like "agent" is ordinary prose
        assert flags.FEATURE_SPELLINGS[name][0] not in off.stdout


@pytest.mark.fab_test
def test_stubs_are_never_suggested_for_a_typo():
    result = _run_cli("data-agnt")

    assert result.returncode == 2
    assert "unknown analyzer 'data-agnt'" in result.stderr
    assert "data-agent" not in result.stderr.replace("'data-agnt'", "")


@pytest.mark.fab_test
def test_visible_analyzers_excludes_a_disabled_one(monkeypatch):
    monkeypatch.setitem(registry.ANALYZER_REGISTRY, "data_agent", ("*.DataAgent", "Fabric Data Agent"))

    assert "data_agent" not in registry.visible_analyzers()
    assert ".DataAgent" not in registry._suffix_to_analyzers()

    monkeypatch.setenv(flags.env_var("data_agent"), "1")

    assert "data_agent" in registry.visible_analyzers()
    assert registry._suffix_to_analyzers()[".DataAgent"] == ("data_agent",)


@pytest.mark.fab_test
def test_all_bundle_drops_a_disabled_analyzer(tmp_path):
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(json.dumps({"fab_test_all": ["bpa", "data_agent", "sqldb_test", "rdl"]}), encoding="utf-8")

    assert registry.load_fab_test_all_analyzers(metadata) == ("bpa", "rdl")


@pytest.mark.fab_test
def test_doctor_refuses_a_disabled_analyzer_by_name():
    result = _run_cli("doctor", "--analyzer", "data_agent")

    assert result.returncode == 2
    assert flags.env_var("data_agent") in result.stderr


# --------------------------------------------------------------------------- #
# The tool is never resolved
# --------------------------------------------------------------------------- #


@pytest.fixture
def _probe_calls(monkeypatch):
    calls: list[str] = []

    def _fake_probe(analyzer_name, *_a, **_k):
        calls.append(analyzer_name)
        return {"ready": True, "resolved_path": "x", "reason": "r", "remediation": None, "version": "1"}

    def _fake_resolve(analyzer_name, *_a, **_k):
        calls.append(analyzer_name)
        return "x"

    monkeypatch.setattr(registry, "probe_executable", _fake_probe)
    monkeypatch.setattr(registry, "resolve_executable", _fake_resolve)
    return calls


@pytest.mark.fab_test
def test_disabled_data_agent_never_resolves_promptfoo(_probe_calls):
    assert registry.resolve_tool("data_agent", argparse.Namespace()) is None
    assert registry.preflight_error("data_agent", argparse.Namespace()) is None
    assert registry.check_readiness("data_agent", None)["reason"] == "no external tool required"
    assert _probe_calls == []


@pytest.mark.fab_test
def test_enabled_data_agent_resolves_promptfoo(monkeypatch, _probe_calls):
    monkeypatch.setenv(flags.env_var("data_agent"), "1")

    registry.resolve_tool("data_agent", argparse.Namespace())
    registry.check_readiness("data_agent", None)

    assert _probe_calls == ["data_agent", "data_agent"]
