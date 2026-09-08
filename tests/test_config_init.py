"""Contract tests for `fab-test init` (Config Consolidation §10).

Scope
-----
Makes the first config file something the CLI writes instead of something
the user researches. Always passes on any machine -- no external tool or
artifact required.

    pytest -m fab_test tests/test_config_init.py
"""

import json
import subprocess

import pytest


@pytest.mark.fab_test
def test_init_creates_fab_test_yml_and_env_example(tmp_path):
    """fab-test init creates a commented fab-test.yml and .fab-test/.env.example.

    `.fab-test/.env.example` replaces the root `.env.example` for new
    repositories (task 8): it lives alongside `.fab-test/.gitignore`, the
    guard that makes a real `.env` there safe to keep in the same
    directory as the committed `.fab-test/metadata/`.
    """
    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fab-test.yml").exists()
    assert (tmp_path / ".fab-test" / ".env.example").exists()


@pytest.mark.fab_test
def test_init_scaffolds_fab_test_gitignore(tmp_path):
    """fab-test init writes .fab-test/.gitignore so a real .env stays untracked.

    `.fab-test/metadata/` is meant to be checked in; a `.env` in the same
    directory is one `git add .fab-test/` away from a leaked credential
    unless fab-test ships its own guard rather than relying on a
    consumer's root `.gitignore` already covering `.env`.
    """
    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    gitignore = tmp_path / ".fab-test" / ".gitignore"
    assert gitignore.exists()
    assert ".env" in gitignore.read_text(encoding="utf-8")


@pytest.mark.fab_test
def test_init_does_not_overwrite_existing_fab_test_yml(tmp_path):
    """An existing fab-test.yml is reported and left completely untouched."""
    config_path = tmp_path / "fab-test.yml"
    original_content = "jobs: 4  # my custom setting\n"
    config_path.write_text(original_content, encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert config_path.read_text(encoding="utf-8") == original_content
    assert "already" in (result.stdout + result.stderr).lower()


@pytest.mark.fab_test
def test_init_does_not_overwrite_existing_env_example(tmp_path):
    """An existing .fab-test/.env.example is reported and left untouched."""
    fab_test_dir = tmp_path / ".fab-test"
    fab_test_dir.mkdir()
    env_example = fab_test_dir / ".env.example"
    original_content = "MY_CUSTOM_VAR=1\n"
    env_example.write_text(original_content, encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert env_example.read_text(encoding="utf-8") == original_content


@pytest.mark.fab_test
def test_init_reports_both_existing_and_exits_zero_with_no_changes(tmp_path):
    """When both files already exist, init exits 0 and changes nothing."""
    config_path = tmp_path / "fab-test.yml"
    fab_test_dir = tmp_path / ".fab-test"
    fab_test_dir.mkdir()
    env_example = fab_test_dir / ".env.example"
    config_path.write_text("jobs: 1\n", encoding="utf-8")
    env_example.write_text("X=1\n", encoding="utf-8")
    config_mtime = config_path.stat().st_mtime
    env_mtime = env_example.stat().st_mtime

    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert config_path.stat().st_mtime == config_mtime
    assert env_example.stat().st_mtime == env_mtime


@pytest.mark.fab_test
def test_init_scaffolded_config_passes_validate(tmp_path):
    """The freshly scaffolded fab-test.yml passes config --validate unmodified."""
    init_result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )
    assert init_result.returncode == 0, init_result.stderr

    validate_result = subprocess.run(
        ["fab-test", "config", "--validate"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert validate_result.returncode == 0, validate_result.stderr


@pytest.mark.fab_test
def test_init_scaffolds_a_commented_workspace_line(tmp_path):
    """The scaffolded fab-test.yml documents `workspace:` alongside `environment:`.

    `workspace:` has worked since Artifact Targeting §3 but was documented
    nowhere a user would look -- not here, not in `_SETTING_SPECS`. A
    setting that cannot be found is a setting that does not exist.
    """
    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    content = (tmp_path / "fab-test.yml").read_text(encoding="utf-8")
    assert "workspace:" in content
    assert "environment:" in content


@pytest.mark.fab_test
def test_init_scaffolds_a_commented_telemetry_block(tmp_path):
    """The scaffolded fab-test.yml documents `telemetry.eventhouse`.

    The key has worked since Eventhouse Shipping but was never added to the
    scaffold, so a user running `init` had no way to discover that shipping
    telemetry from their own machine is possible without reading the skill
    or the source.
    """
    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    content = (tmp_path / "fab-test.yml").read_text(encoding="utf-8")
    assert "telemetry:" in content
    assert "eventhouse:" in content
    assert "uri:" in content
    assert "database:" in content
    assert "EVENTHOUSE_URI" in content
    assert "EVENTHOUSE_DATABASE" in content


@pytest.mark.fab_test
def test_init_scaffolds_a_commented_lakehouse_telemetry_block(tmp_path):
    """The scaffolded fab-test.yml documents `telemetry.lakehouse` alongside `.eventhouse`.

    Lakehouse Telemetry Sink §2: a user discovering telemetry via `init`
    should see both destinations are optional and independent, not just
    the Eventhouse one that shipped first.
    """
    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    content = (tmp_path / "fab-test.yml").read_text(encoding="utf-8")
    assert "lakehouse:" in content
    assert "workspace:" in content
    assert "LAKEHOUSE_WORKSPACE" in content
    assert "LAKEHOUSE_NAME" in content


@pytest.mark.fab_test
def test_init_json_format_lists_created_files(tmp_path):
    """--format json reports which files were created."""
    result = subprocess.run(
        ["fab-test", "init", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    created_names = {p.split("/")[-1].split("\\")[-1] for p in data["created"]}
    assert created_names == {"fab-test.yml", ".gitignore", ".env.example"}
    assert data["already_existed"] == []


@pytest.mark.fab_test
def test_init_dry_run_reports_without_writing_anything(tmp_path):
    """--dry-run reports what would be created and writes nothing."""
    result = subprocess.run(
        ["fab-test", "init", "--dry-run", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "fab-test.yml").exists()
    assert not (tmp_path / ".env.example").exists()
    data = json.loads(result.stdout)
    would_create_names = {p.split("/")[-1].split("\\")[-1] for p in data["would_create"]}
    assert would_create_names == {"fab-test.yml", ".gitignore", ".env.example"}
    assert data["created"] == []


@pytest.mark.fab_test
def test_init_dry_run_reports_existing_files_without_listing_them_as_would_create(tmp_path):
    """--dry-run against an existing fab-test.yml reports it as already existing, not pending creation."""
    (tmp_path / "fab-test.yml").write_text("jobs: 1\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "init", "--dry-run", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    would_create_names = {p.split("/")[-1].split("\\")[-1] for p in data["would_create"]}
    already_existed_names = {p.split("/")[-1].split("\\")[-1] for p in data["already_existed"]}
    assert "fab-test.yml" not in would_create_names
    assert "fab-test.yml" in already_existed_names
