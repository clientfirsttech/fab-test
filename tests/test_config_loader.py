"""Contract tests for fab-test.yml discovery and loading (Config Consolidation §1).

Scope
-----
The config file is optional and additive: no fab-test.yml means behavior
identical to today. Always passes on any machine -- no external tool or
artifact required.

    pytest tests/test_config_loader.py
    pytest tests/test_config_loader.py -k merge
"""

import json
import subprocess
from pathlib import Path

import pytest

from fab_test.scripts._config import (
    _VALID_KEYS,
    CONFIG_FILENAME,
    ConfigError,
    discover_config_path,
    load_config,
    load_pyproject_config,
    merged_file_config,
    resolve_setting,
    validate_config,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "fab_test"
    / "schemas"
    / "fab-test.schema.json"
)


@pytest.mark.fab_test
def test_discover_config_path_finds_fab_test_yml_at_repo_root(tmp_path):
    """A fab-test.yml at the repository root is discovered."""
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text("artifact_dir: .fabric/artifacts\n", encoding="utf-8")

    assert discover_config_path(tmp_path) == config_file


@pytest.mark.fab_test
def test_discover_config_path_returns_none_when_absent(tmp_path):
    """No fab-test.yml at the repository root discovers nothing."""
    assert discover_config_path(tmp_path) is None


@pytest.mark.fab_test
def test_discover_config_path_prefers_explicit_override(tmp_path):
    """--config PATH is used instead of the discovered fab-test.yml."""
    (tmp_path / CONFIG_FILENAME).write_text("a: 1\n", encoding="utf-8")
    override = tmp_path / "custom.yml"
    override.write_text("b: 2\n", encoding="utf-8")

    assert discover_config_path(tmp_path, str(override)) == override


@pytest.mark.fab_test
def test_load_config_parses_yaml_into_a_plain_dict(tmp_path):
    """A valid fab-test.yml is parsed into a plain dictionary."""
    (tmp_path / CONFIG_FILENAME).write_text(
        "artifact_dir: .fabric/artifacts\njobs: 4\n", encoding="utf-8"
    )

    config = load_config(tmp_path)

    assert config == {"artifact_dir": ".fabric/artifacts", "jobs": 4}


@pytest.mark.fab_test
def test_load_config_returns_empty_dict_when_no_config_file_exists(tmp_path):
    """No config file returns an empty configuration -- behavior identical to today."""
    assert load_config(tmp_path) == {}


@pytest.mark.fab_test
def test_load_config_returns_empty_dict_for_an_empty_file(tmp_path):
    """An empty (or comment-only) fab-test.yml parses to an empty dict, not None."""
    (tmp_path / CONFIG_FILENAME).write_text("# nothing here yet\n", encoding="utf-8")

    assert load_config(tmp_path) == {}


@pytest.mark.fab_test
def test_load_config_loads_explicit_override_path(tmp_path):
    """--config PATH loads that file instead of the discovered fab-test.yml."""
    (tmp_path / CONFIG_FILENAME).write_text("a: 1\n", encoding="utf-8")
    override = tmp_path / "custom.yml"
    override.write_text("b: 2\n", encoding="utf-8")

    assert load_config(tmp_path, str(override)) == {"b": 2}


@pytest.mark.fab_test
def test_load_config_raises_config_error_when_explicit_path_missing(tmp_path):
    """A --config path that doesn't exist raises ConfigError naming the file."""
    missing = tmp_path / "does-not-exist.yml"

    with pytest.raises(ConfigError, match=str(missing).replace("\\", "\\\\")):
        load_config(tmp_path, str(missing))


@pytest.mark.fab_test
def test_load_config_raises_config_error_on_malformed_yaml(tmp_path):
    """Malformed YAML raises ConfigError naming the file and the parse error."""
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text("artifact_dir: [unclosed\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=str(config_file).replace("\\", "\\\\")):
        load_config(tmp_path)


@pytest.mark.fab_test
def test_load_config_raises_config_error_when_top_level_is_not_a_mapping(tmp_path):
    """A YAML list (or scalar) at the top level raises ConfigError."""
    (tmp_path / CONFIG_FILENAME).write_text("- one\n- two\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="mapping"):
        load_config(tmp_path)


@pytest.mark.fab_test
def test_main_exits_2_on_malformed_config_yaml(tmp_path):
    """A real fab-test invocation with malformed --config YAML exits 2."""
    config_file = tmp_path / "bad.yml"
    config_file.write_text("artifact_dir: [unclosed\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "--config", str(config_file), "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2
    assert "bad.yml" in result.stderr


@pytest.mark.fab_test
def test_main_unaffected_when_no_config_file_exists(tmp_path):
    """No fab-test.yml anywhere: fab-test behaves exactly as before this epic."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run", "--artifact-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Merging fab-test.yml with [tool.fab-test] (Config Consolidation §2)
# --------------------------------------------------------------------------- #


def _write_pyproject_table(tmp_path, **kwargs):
    lines = ["[tool.fab-test]"]
    for key, value in kwargs.items():
        rendered = f'"{value}"' if isinstance(value, str) else str(value)
        lines.append(f"{key} = {rendered}")
    (tmp_path / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.fab_test
def test_merge_returns_pyproject_only_when_no_yaml_exists(tmp_path):
    """Only [tool.fab-test]: every current setting resolves exactly as before."""
    _write_pyproject_table(tmp_path, jobs=4, format="json")

    config, warnings = merged_file_config(tmp_path, tmp_path / "pyproject.toml")

    assert config == {"jobs": 4, "format": "json"}
    assert warnings == []


@pytest.mark.fab_test
def test_merge_prefers_fab_test_yml_for_overlapping_keys(tmp_path):
    """fab-test.yml wins over [tool.fab-test] for a key present in both."""
    _write_pyproject_table(tmp_path, jobs=4, output_dir="pyproject-results")
    (tmp_path / CONFIG_FILENAME).write_text("jobs: 8\n", encoding="utf-8")

    config, _warnings = merged_file_config(tmp_path, tmp_path / "pyproject.toml")

    assert config["jobs"] == 8
    assert config["output_dir"] == "pyproject-results"


@pytest.mark.fab_test
def test_merge_warns_once_when_both_sources_exist(tmp_path):
    """Both sources present produces exactly one warning naming both files."""
    _write_pyproject_table(tmp_path, jobs=4)
    (tmp_path / CONFIG_FILENAME).write_text("jobs: 8\n", encoding="utf-8")

    _config, warnings = merged_file_config(tmp_path, tmp_path / "pyproject.toml")

    assert len(warnings) == 1
    assert "pyproject.toml" in warnings[0]
    assert CONFIG_FILENAME in warnings[0]


@pytest.mark.fab_test
def test_merge_returns_empty_dict_and_no_warnings_when_neither_exists(tmp_path):
    """Neither source exists: empty config, no warnings."""
    config, warnings = merged_file_config(tmp_path, tmp_path / "pyproject.toml")

    assert config == {}
    assert warnings == []


@pytest.mark.fab_test
def test_load_pyproject_config_reads_tool_fab_test_section(tmp_path):
    """[tool.fab-test] values are returned as a plain dict."""
    _write_pyproject_table(tmp_path, jobs=4, format="json")

    assert load_pyproject_config(tmp_path / "pyproject.toml") == {"jobs": 4, "format": "json"}


@pytest.mark.fab_test
def test_load_pyproject_config_missing_file_returns_empty(tmp_path):
    """A missing pyproject.toml yields an empty config, not an error."""
    assert load_pyproject_config(tmp_path / "does-not-exist.toml") == {}


@pytest.mark.fab_test
def test_load_pyproject_config_missing_section_returns_empty(tmp_path):
    """A pyproject.toml without [tool.fab-test] yields an empty config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.other]\nx = 1\n", encoding="utf-8")

    assert load_pyproject_config(pyproject) == {}


@pytest.mark.fab_test
def test_load_pyproject_config_malformed_toml_returns_empty(tmp_path):
    """Malformed TOML yields an empty config rather than crashing."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("not [ valid toml", encoding="utf-8")

    assert load_pyproject_config(pyproject) == {}


@pytest.mark.fab_test
def test_main_narrates_duplicate_config_source_warning(tmp_path):
    """A real invocation with both sources present narrates the warning once."""
    _write_pyproject_table(tmp_path, jobs=4)
    (tmp_path / CONFIG_FILENAME).write_text("jobs: 8\n", encoding="utf-8")
    (tmp_path / ".fabric" / "artifacts").mkdir(parents=True)

    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert combined.count("pyproject.toml") == 1
    assert CONFIG_FILENAME in combined


# --------------------------------------------------------------------------- #
# Validating config keys and types (Config Consolidation §3)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_validate_config_passes_for_empty_config():
    """An empty config is trivially valid."""
    validate_config({})  # must not raise


@pytest.mark.fab_test
def test_validate_config_passes_for_valid_config():
    """A config with only known keys and correct types is valid."""
    validate_config({"jobs": 4, "format": "json", "artifact_dir": "/tmp/x"})  # must not raise


@pytest.mark.fab_test
def test_validate_config_passes_for_rules_overlay_key():
    """rules (bpa/pbir overlay config) is a valid top-level key."""
    validate_config({"rules": {"bpa": {"disable": ["SOME_RULE"]}}})  # must not raise


@pytest.mark.fab_test
def test_validate_config_raises_naming_unknown_key_and_suggestion():
    """A typo'd key exits naming the key and the closest valid key."""
    with pytest.raises(ConfigError, match="artifact_dir"):
        validate_config({"artifac_dir": "/tmp/x"})


@pytest.mark.fab_test
def test_validate_config_raises_naming_unknown_key_with_no_close_match():
    """A key with no close match still names the offending key."""
    with pytest.raises(ConfigError, match="totally_bogus_setting"):
        validate_config({"totally_bogus_setting": 1})


@pytest.mark.fab_test
def test_validate_config_raises_naming_expected_type():
    """A key with the wrong type exits naming the expected type."""
    with pytest.raises(ConfigError, match="int"):
        validate_config({"jobs": "four"})


@pytest.mark.fab_test
def test_main_exits_2_on_unknown_config_key(tmp_path):
    """A real invocation with a typo'd config key exits 2 with a suggestion."""
    (tmp_path / CONFIG_FILENAME).write_text("artifac_dir: /tmp/x\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 2
    assert "artifac_dir" in result.stderr
    assert "artifact_dir" in result.stderr


@pytest.mark.fab_test
def test_main_exits_2_on_wrong_type_config_value(tmp_path):
    """A real invocation with a wrong-typed config value exits 2 naming the type."""
    (tmp_path / CONFIG_FILENAME).write_text("jobs: four\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 2
    assert "jobs" in result.stderr


# --------------------------------------------------------------------------- #
# Centralized precedence resolution (Config Consolidation §4)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_resolve_setting_cli_flag_wins_over_everything(monkeypatch):
    """An explicit CLI value wins over env var, config, and packaged default."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")

    value, origin = resolve_setting(
        "timeout",
        cli_value=300,
        env_var="ANALYZER_TIMEOUT",
        file_config={"timeout": 999},
        packaged_default=120,
        cast=int,
    )

    assert (value, origin) == (300, "flag")


@pytest.mark.fab_test
def test_resolve_setting_env_var_wins_over_config_and_default(monkeypatch):
    """The env var wins when no CLI value is given."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "200")

    value, origin = resolve_setting(
        "timeout",
        cli_value=None,
        env_var="ANALYZER_TIMEOUT",
        file_config={"timeout": 999},
        packaged_default=120,
        cast=int,
    )

    assert (value, origin) == (200, "env:ANALYZER_TIMEOUT")


@pytest.mark.fab_test
def test_resolve_setting_config_wins_over_packaged_default(monkeypatch):
    """The config file wins when no CLI value or env var is given."""
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)

    value, origin = resolve_setting(
        "timeout",
        cli_value=None,
        env_var="ANALYZER_TIMEOUT",
        file_config={"timeout": 999},
        packaged_default=120,
        cast=int,
    )

    assert (value, origin) == (999, f"{CONFIG_FILENAME}:timeout")


@pytest.mark.fab_test
def test_resolve_setting_falls_back_to_packaged_default(monkeypatch):
    """The packaged default wins when nothing else is set."""
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)

    value, origin = resolve_setting(
        "timeout",
        cli_value=None,
        env_var="ANALYZER_TIMEOUT",
        file_config={},
        packaged_default=120,
        cast=int,
    )

    assert (value, origin) == (120, "default")


@pytest.mark.fab_test
def test_resolve_setting_ignores_malformed_env_var(monkeypatch):
    """A malformed env var (fails cast) falls through to config/default instead of raising."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "not-a-number")

    value, origin = resolve_setting(
        "timeout",
        cli_value=None,
        env_var="ANALYZER_TIMEOUT",
        file_config={"timeout": 999},
        packaged_default=120,
        cast=int,
    )

    assert (value, origin) == (999, f"{CONFIG_FILENAME}:timeout")


@pytest.mark.fab_test
def test_resolve_setting_without_env_var_checks_config_directly():
    """A setting with no env_var (e.g. environment/--env) skips straight to config."""
    value, origin = resolve_setting(
        "environment",
        cli_value=None,
        env_var=None,
        file_config={"environment": "DEV"},
        packaged_default="",
    )

    assert (value, origin) == ("DEV", f"{CONFIG_FILENAME}:environment")


# --------------------------------------------------------------------------- #
# JSON schema and deep rule-overlay validation (Config Consolidation §11)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_schema_file_exists_and_is_valid_json():
    """The packaged schema file parses as JSON."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"] == "fab-test.yml"


@pytest.mark.fab_test
def test_schema_properties_match_valid_keys():
    """The schema's top-level properties and the loader's _VALID_KEYS can't drift."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["properties"].keys()) == set(_VALID_KEYS.keys())


@pytest.mark.fab_test
def test_schema_rule_overlay_properties_match_validator():
    """The schema's ruleOverlay keys and validate_config's nested check can't drift."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    overlay_props = set(schema["$defs"]["ruleOverlay"]["properties"].keys())
    assert overlay_props == {"disable", "severity", "extend"}


@pytest.mark.fab_test
def test_validate_config_accepts_a_full_valid_rules_overlay():
    """A structurally valid rules overlay passes."""
    validate_config({
        "rules": {
            "bpa": {"disable": ["RULE_A"], "severity": {"RULE_B": "warning"}, "extend": "extra.json"},
            "pbir": {"disable": ["RULE_C"]},
            "rdl": {"disable": ["DS-02"], "severity": {"QRY-07": "info"}},
        }
    })  # must not raise


@pytest.mark.fab_test
def test_schema_rules_analyzers_match_the_overlay_allowlist():
    """The schema's rules.<analyzer> keys and _RULE_OVERLAY_ANALYZERS can't drift --
    an analyzer added to one without the other either rejects a valid config
    (schema) or accepts one the loader then rejects anyway (validator)."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    from fab_test.scripts._config import _RULE_OVERLAY_ANALYZERS

    assert set(schema["properties"]["rules"]["properties"].keys()) == set(_RULE_OVERLAY_ANALYZERS)


@pytest.mark.fab_test
def test_validate_config_rejects_unknown_rules_analyzer():
    """rules.<name> for an analyzer other than bpa/pbir is rejected with a suggestion."""
    with pytest.raises(ConfigError, match="pbir"):
        validate_config({"rules": {"pbi": {"disable": ["X"]}}})


@pytest.mark.fab_test
def test_validate_config_rejects_unknown_rule_overlay_key():
    """A typo'd overlay key (disble instead of disable) is rejected with a suggestion."""
    with pytest.raises(ConfigError, match="disable"):
        validate_config({"rules": {"bpa": {"disble": ["X"]}}})


@pytest.mark.fab_test
def test_validate_config_rejects_non_list_disable():
    """rules.bpa.disable must be a list, not a bare string."""
    with pytest.raises(ConfigError, match="disable"):
        validate_config({"rules": {"bpa": {"disable": "RULE_A"}}})


@pytest.mark.fab_test
def test_validate_config_rejects_non_string_items_in_disable():
    """rules.bpa.disable's items must all be strings."""
    with pytest.raises(ConfigError, match="disable"):
        validate_config({"rules": {"bpa": {"disable": [123]}}})


@pytest.mark.fab_test
def test_validate_config_rejects_non_string_severity_values():
    """rules.bpa.severity must map rule IDs to string labels."""
    with pytest.raises(ConfigError, match="severity"):
        validate_config({"rules": {"bpa": {"severity": {"RULE_A": 2}}}})


@pytest.mark.fab_test
def test_config_validate_real_cli_reports_success_for_a_valid_config(tmp_path):
    """fab-test config --validate exits 0 and reports success for a valid config."""
    (tmp_path / CONFIG_FILENAME).write_text("jobs: 2\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "config", "--validate"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "valid" in (result.stdout + result.stderr).lower()


@pytest.mark.fab_test
def test_config_validate_real_cli_exits_2_for_invalid_config(tmp_path):
    """fab-test config --validate exits 2 for a config with an unknown key."""
    (tmp_path / CONFIG_FILENAME).write_text("not_a_real_key: 1\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "config", "--validate"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 2
    assert "not_a_real_key" in result.stderr


# --------------------------------------------------------------------------- #
# Backward-compatibility sweep (Config Consolidation §12)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_only_pyproject_config_produces_identical_command_behavior(tmp_path):
    """A repository with only [tool.fab-test] (no fab-test.yml) behaves exactly
    as it did before this epic: config --show resolves every value from
    pyproject.toml's table, with no fab-test.yml in the picture at all.
    """
    _write_pyproject_table(tmp_path, jobs=3, format="json", timeout=45)
    assert not (tmp_path / CONFIG_FILENAME).exists()

    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    by_key = {row["key"]: row for row in data["settings"]}
    assert by_key["jobs"]["value"] == 3
    assert by_key["format"]["value"] == "json"
    assert by_key["timeout"]["value"] == 45
    # Known imprecision (not fixed here -- outside this sweep task's file
    # scope): resolve_setting's origin label is always "fab-test.yml:key"
    # for a config-sourced value, even when it actually came from
    # [tool.fab-test] and no fab-test.yml exists. The *value* is correct;
    # only the displayed origin string doesn't distinguish the two files.
    assert by_key["jobs"]["origin"] == f"{CONFIG_FILENAME}:jobs"


@pytest.mark.parametrize(
    ("env_var", "config_key", "config_value", "env_value", "expected"),
    [
        ("ANALYZER_TIMEOUT", "timeout", 300, "45", 45),
        ("FABRIC_ENVIRONMENT", "environment", "PROD", "STAGING", "STAGING"),
    ],
)
@pytest.mark.fab_test
def test_every_documented_env_var_still_overrides_config_file(
    monkeypatch, env_var, config_key, config_value, env_value, expected
):
    """Every documented env var (ANALYZER_TIMEOUT, FABRIC_ENVIRONMENT) overrides
    the config file, exactly as it did before this epic's resolver existed.
    """
    monkeypatch.setenv(env_var, env_value)

    value, origin = resolve_setting(
        config_key,
        cli_value=None,
        env_var=env_var,
        file_config={config_key: config_value},
        packaged_default=None,
        cast=int if isinstance(expected, int) else None,
    )

    assert value == expected
    assert origin == f"env:{env_var}"


@pytest.mark.parametrize(
    ("config_key", "env_var"),
    [("timeout", "ANALYZER_TIMEOUT"), ("environment", "FABRIC_ENVIRONMENT")],
)
@pytest.mark.fab_test
def test_cli_flag_wins_over_config_for_every_resolver_backed_setting(config_key, env_var):
    """A CLI flag wins over both the config file and its env var, for every
    setting routed through resolve_setting.
    """
    value, origin = resolve_setting(
        config_key,
        cli_value="explicit-cli-value",
        env_var=env_var,
        file_config={config_key: "config-value"},
        packaged_default="default-value",
    )

    assert value == "explicit-cli-value"
    assert origin == "flag"


@pytest.mark.fab_test
def test_cli_flag_wins_over_config_for_every_argparse_backed_setting(monkeypatch):
    """A CLI flag wins over [tool.fab-test] for jobs/format/artifact-dir/output-dir --
    the settings that still use baked-in argparse defaults rather than the resolver.
    """
    from fab_test.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_PYPROJECT_CONFIG",
        {
            "jobs": 4,
            "format": "json",
            "artifact_dir": "/configured/artifacts",
            "output_dir": "/configured/results",
        },
    )
    parser = fab_test_module.build_parser()
    ns = parser.parse_args([
        "bpa", "--dry-run",
        "--jobs", "9",
        "--format", "text",
        "--artifact-dir", "/explicit/artifacts",
        "--output-dir", "/explicit/results",
    ])

    assert ns.jobs == 9
    assert ns.output_format == "text"
    assert ns.artifact_dir == "/explicit/artifacts"
    assert ns.output_dir == "/explicit/results"
