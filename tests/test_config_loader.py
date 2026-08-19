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
