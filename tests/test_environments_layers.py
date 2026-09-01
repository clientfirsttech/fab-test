"""Contract tests for `environments.yml` layer resolution (Environments Metadata Layers §3).

Scope
-----
Six callers resolved `environments.yml` by building
``.github/metadata/environments.yml`` themselves, so the one metadata file a
consumer is most likely to need to tune was the one the override chain from
the TestPyPI Release epic did not reach. These assert each caller now
searches `.fab-test/metadata/` first, still accepts the legacy
`.github/metadata/`, and -- because this file has no safe packaged default --
names both places when it finds neither.

Always passes on any machine: every case is path resolution against a
tmp_path, no workspace and no credentials.

    pytest -m fab_test tests/test_environments_layers.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fab_test.scripts import (
    check_promotion_safety,
    deploy,
    generate_fabric_cicd_config,
    validate_environments_schema,
    validate_environments_yaml,
)
from fab_test.scripts.playwright_validation import resolver

# Valid for the stricter of the two validators, so a resolution test that
# reaches the right file reports success rather than a schema complaint.
_CONFIG = """\
defaults:
  capacity_id: cap-1
environments:
  dev:
    description: Development
    workspace_id: ws-{tag}
    allowed_branches: ["dev"]
    promotion_target: test
promotion_chain: ["dev"]
"""


def _write_env(root: Path, layer: str, tag: str = "default") -> Path:
    """Create ``<root>/<layer>/environments.yml`` and return it."""
    target = root / layer / "environments.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_CONFIG.format(tag=tag), encoding="utf-8")
    return target


@pytest.fixture(autouse=True)
def _no_ci_workspace(monkeypatch):
    """Resolve against the working directory, not a CI checkout that isn't here."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)


def _both_places_named(message: str) -> bool:
    """Both candidate directories appear, and no packaged copy is offered."""
    normalized = message.replace("\\", "/")
    return (
        ".fab-test/metadata" in normalized
        and ".github/metadata" in normalized
        and "packaged" not in normalized
    )


# --------------------------------------------------------------------------- #
# deploy.py
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_deploy_prefers_the_fab_test_layer(tmp_path):
    """A consumer's own override drives the deployment, not ours."""
    _write_env(tmp_path, ".github/metadata", tag="legacy")
    _write_env(tmp_path, ".fab-test/metadata", tag="override")

    config = deploy.load_environments_config(tmp_path)

    assert config["environments"]["dev"]["workspace_id"] == "ws-override"


@pytest.mark.fab_test
def test_deploy_still_reads_the_legacy_layer(tmp_path):
    """Every workflow in this repository keeps its file under .github/."""
    _write_env(tmp_path, ".github/metadata", tag="legacy")

    config = deploy.load_environments_config(tmp_path)

    assert config["environments"]["dev"]["workspace_id"] == "ws-legacy"


@pytest.mark.fab_test
def test_deploy_names_both_places_when_the_file_is_absent(tmp_path, capsys):
    """A deployment must not guess; it must say where to put the file."""
    with pytest.raises(SystemExit) as exc_info:
        deploy.load_environments_config(tmp_path)

    assert exc_info.value.code == 1
    assert _both_places_named(capsys.readouterr().err)


# --------------------------------------------------------------------------- #
# generate_fabric_cicd_config.py
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_generate_config_prefers_the_fab_test_layer(tmp_path):
    """The generated fabric-cicd config follows the same override chain."""
    _write_env(tmp_path, ".github/metadata", tag="legacy")
    _write_env(tmp_path, ".fab-test/metadata", tag="override")

    config = generate_fabric_cicd_config.load_config(tmp_path)

    assert config["environments"]["dev"]["workspace_id"] == "ws-override"


@pytest.mark.fab_test
def test_generate_config_names_both_places_when_absent(tmp_path, capsys):
    """The generator exits 1 rather than writing a config aimed nowhere."""
    with pytest.raises(SystemExit) as exc_info:
        generate_fabric_cicd_config.load_config(tmp_path)

    assert exc_info.value.code == 1
    assert _both_places_named(capsys.readouterr().err)


# --------------------------------------------------------------------------- #
# check_promotion_safety.py
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_promotion_checker_resolves_through_the_layers(tmp_path, monkeypatch):
    """Its default was a relative path, so it only worked from the repo root."""
    _write_env(tmp_path, ".fab-test/metadata", tag="override")
    monkeypatch.chdir(tmp_path)

    checker = check_promotion_safety.PromotionSafetyChecker()

    assert checker.config["environments"]["dev"]["workspace_id"] == "ws-override"


@pytest.mark.fab_test
def test_promotion_checker_still_honours_an_explicit_path(tmp_path):
    """Callers and tests pass a path; that must keep winning."""
    explicit = _write_env(tmp_path, "elsewhere", tag="explicit")

    checker = check_promotion_safety.PromotionSafetyChecker(str(explicit))

    assert checker.config["environments"]["dev"]["workspace_id"] == "ws-explicit"


@pytest.mark.fab_test
def test_promotion_checker_names_both_places_when_absent(tmp_path, monkeypatch):
    """Still a FileNotFoundError, so its callers' handling is unchanged."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError) as exc_info:
        check_promotion_safety.PromotionSafetyChecker()

    assert _both_places_named(str(exc_info.value))


@pytest.mark.fab_test
def test_promotion_checker_does_not_bind_a_path_at_import_time(tmp_path, monkeypatch):
    """A checker built in one directory must not carry another's file.

    The old default was evaluated in the signature, which made the path a
    property of the module rather than of the call.
    """
    _write_env(tmp_path, ".fab-test/metadata", tag="first")
    monkeypatch.chdir(tmp_path)
    first = check_promotion_safety.PromotionSafetyChecker()

    second_root = tmp_path / "second"
    _write_env(second_root, ".fab-test/metadata", tag="second")
    monkeypatch.chdir(second_root)
    second = check_promotion_safety.PromotionSafetyChecker()

    assert first.config["environments"]["dev"]["workspace_id"] == "ws-first"
    assert second.config["environments"]["dev"]["workspace_id"] == "ws-second"


# --------------------------------------------------------------------------- #
# playwright_validation/resolver.py
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_playwright_resolver_prefers_the_fab_test_layer(tmp_path, monkeypatch):
    """`fab-test playwright` resolves its workspace from the same file."""
    _write_env(tmp_path, ".github/metadata", tag="legacy")
    _write_env(tmp_path, ".fab-test/metadata", tag="override")
    monkeypatch.chdir(tmp_path)

    environments = resolver._load_environments()

    assert environments["dev"]["workspace_id"] == "ws-override"


@pytest.mark.fab_test
def test_playwright_resolver_names_both_places_when_absent(tmp_path, monkeypatch):
    """Stays a ServiceResolutionError so the wrapper still exits 1 cleanly."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(resolver.ServiceResolutionError) as exc_info:
        resolver._load_environments()

    assert _both_places_named(str(exc_info.value))


@pytest.mark.fab_test
def test_playwright_resolver_still_honours_an_explicit_path(tmp_path):
    """`--env-path` and the impact manifest both pass one."""
    explicit = _write_env(tmp_path, "elsewhere", tag="explicit")

    environments = resolver._load_environments(explicit)

    assert environments["dev"]["workspace_id"] == "ws-explicit"


# --------------------------------------------------------------------------- #
# the two validators
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_yaml_validator_resolves_through_the_layers(tmp_path, monkeypatch, capsys):
    """Validating the wrong file is worse than validating none."""
    override = _write_env(tmp_path, ".fab-test/metadata", tag="override")
    monkeypatch.chdir(tmp_path)

    exit_code = validate_environments_yaml.main([])

    assert exit_code == 0
    assert str(override) in capsys.readouterr().out


@pytest.mark.fab_test
def test_yaml_validator_names_both_places_when_absent(tmp_path, monkeypatch, capsys):
    """Nothing to validate is an error that says where to put the file."""
    monkeypatch.chdir(tmp_path)

    exit_code = validate_environments_yaml.main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert _both_places_named(captured.out + captured.err)


@pytest.mark.fab_test
def test_schema_validator_resolves_through_the_layers(tmp_path, monkeypatch, capsys):
    """`main` reads sys.argv directly, so the override arrives that way."""
    override = _write_env(tmp_path, ".fab-test/metadata", tag="override")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_environments_schema"])

    with pytest.raises(SystemExit):
        validate_environments_schema.main()

    assert str(override) in capsys.readouterr().out


@pytest.mark.fab_test
def test_schema_validator_names_both_places_when_absent(tmp_path, monkeypatch, capsys):
    """Exit 1 naming both candidates, not "File not found" naming one."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_environments_schema"])

    with pytest.raises(SystemExit) as exc_info:
        validate_environments_schema.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert _both_places_named(captured.out + captured.err)
