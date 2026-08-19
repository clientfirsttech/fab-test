"""Contract tests for fab-test.yml discovery and loading (Config Consolidation §1).

Scope
-----
The config file is optional and additive: no fab-test.yml means behavior
identical to today. Always passes on any machine -- no external tool or
artifact required.

    pytest tests/test_config_loader.py
    pytest tests/test_config_loader.py -k merge
"""

import subprocess

import pytest

from fabric_ci_cd_dataops.scripts._config import (
    CONFIG_FILENAME,
    ConfigError,
    discover_config_path,
    load_config,
    load_pyproject_config,
    merged_file_config,
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
