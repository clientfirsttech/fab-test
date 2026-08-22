"""Contract tests for metadata override resolution (TestPyPI Release §3).

Scope
-----
A consumer who installs `fab-test` from an index needs somewhere to put a
tuned ruleset. That place is `.fab-test/metadata/` -- fab-test's own
directory. It is deliberately not `.github/metadata/`, which belongs to
GitHub and is this repository's internal layout; telling a consumer to
create it there would leak our arrangement into their repository.

`.github/metadata/` still resolves, because vision.md's
backward-compatibility constraint covers it and every workflow in
`.github/workflows/` depends on it.

Always passes on any machine -- resolution is pure path lookup against a
tmp_path, no external tool required.

    pytest -m fab_test tests/test_metadata_resolution.py
"""

import json
import subprocess
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._metadata import (
    PACKAGED_METADATA,
    MetadataNotFoundError,
    metadata_path,
    resolve_environments_yml,
    resolve_metadata,
)

_RULES = Path("rules") / "BPARules.json"


def _write(root: Path, layer: str, relative: Path, text: str = "[]") -> Path:
    """Create ``<root>/<layer>/<relative>`` and return it."""
    target = root / layer / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


@pytest.mark.fab_test
def test_a_repo_with_no_override_gets_the_packaged_copy(tmp_path):
    """An install outside a checkout has no override, and must still work."""
    resolved, origin = resolve_metadata(_RULES, tmp_path)

    assert resolved == PACKAGED_METADATA / _RULES
    assert origin == "packaged"


@pytest.mark.fab_test
def test_a_repo_with_no_override_resolves_without_complaining(tmp_path, capsys):
    """An absent override is a default, not a missing file worth warning about.

    Warning here would put a line on every run of every consumer who never
    asked to override anything.
    """
    metadata_path(_RULES, tmp_path)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.fab_test
def test_a_fab_test_override_wins_over_the_packaged_copy(tmp_path):
    """The documented place for a consumer's own ruleset."""
    override = _write(tmp_path, ".fab-test/metadata", _RULES)

    resolved, origin = resolve_metadata(_RULES, tmp_path)

    assert resolved == override
    assert origin == ".fab-test/metadata"


@pytest.mark.fab_test
def test_a_github_metadata_copy_still_resolves(tmp_path):
    """This repository and the reference implementation keep working."""
    existing = _write(tmp_path, ".github/metadata", _RULES)

    resolved, origin = resolve_metadata(_RULES, tmp_path)

    assert resolved == existing
    assert origin == ".github/metadata"


@pytest.mark.fab_test
def test_the_fab_test_directory_wins_over_github_metadata(tmp_path):
    """When both exist, the one a consumer was told to create wins.

    The other is the legacy location, kept only so existing repositories
    do not break.
    """
    _write(tmp_path, ".github/metadata", _RULES, text='["github"]')
    preferred = _write(tmp_path, ".fab-test/metadata", _RULES, text='["fab-test"]')

    resolved, origin = resolve_metadata(_RULES, tmp_path)

    assert resolved == preferred
    assert origin == ".fab-test/metadata"


@pytest.mark.fab_test
def test_a_directory_in_place_of_the_file_is_not_mistaken_for_an_override(tmp_path):
    """Only a readable file is an override; a directory of that name is not."""
    (tmp_path / ".fab-test" / "metadata" / _RULES).mkdir(parents=True)

    resolved, origin = resolve_metadata(_RULES, tmp_path)

    assert resolved == PACKAGED_METADATA / _RULES
    assert origin == "packaged"


@pytest.mark.fab_test
def test_metadata_path_returns_just_the_path(tmp_path):
    """Callers that only need a path should not have to unpack an origin."""
    override = _write(tmp_path, ".fab-test/metadata", _RULES)

    assert metadata_path(_RULES, tmp_path) == override


@pytest.mark.fab_test
def test_config_show_names_the_layer_each_ruleset_came_from():
    """`config --show` answers "which rules are in force?" without reading source.

    The resolved path alone does not say whether it is an override or the
    packaged copy, and a consumer debugging an unexpected finding needs to
    know which.
    """
    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr

    rows = {row["key"]: row for row in json.loads(result.stdout)["settings"]}
    valid_origins = {".fab-test/metadata", ".github/metadata", "packaged"}
    for key in ("rules.bpa", "rules.pbir"):
        assert key in rows, f"missing '{key}' in {sorted(rows)}"
        assert rows[key]["origin"] in valid_origins, rows[key]["origin"]
        assert rows[key]["value"].endswith(".json"), rows[key]["value"]


# ---------------------------------------------------------------------------
# Files with no packaged default (Environments Metadata Layers §2)
# ---------------------------------------------------------------------------

_ENV = Path("environments.yml")


@pytest.mark.fab_test
def test_a_file_with_no_packaged_default_never_resolves_into_the_wheel(tmp_path):
    """`environments.yml` carries workspace GUIDs, so a packaged copy is unsafe.

    Falling back to one would aim a `prod` deployment at whatever workspace
    happened to be baked into the distribution, and report success while
    doing it. Absent is a hard error; wrong-and-confident is not an option.
    """
    with pytest.raises(MetadataNotFoundError):
        resolve_metadata(_ENV, tmp_path, packaged=False)


@pytest.mark.fab_test
def test_a_missing_file_names_every_place_it_could_go(tmp_path):
    """Naming only the last path tried tells the caller to fix the wrong file."""
    with pytest.raises(MetadataNotFoundError) as exc_info:
        resolve_metadata(_ENV, tmp_path, packaged=False)

    message = str(exc_info.value)
    assert ".fab-test/metadata" in message.replace("\\", "/")
    assert ".github/metadata" in message.replace("\\", "/")
    assert "packaged" not in message, "a packaged copy is not an option to offer"
    assert exc_info.value.candidates, "the candidates must be inspectable, not only printed"


@pytest.mark.fab_test
def test_packaged_false_still_prefers_the_fab_test_layer(tmp_path):
    """Dropping the packaged fallback must not change precedence above it."""
    _write(tmp_path, ".github/metadata", _ENV, text="environments: {}")
    preferred = _write(tmp_path, ".fab-test/metadata", _ENV, text="environments: {}")

    resolved, origin = resolve_metadata(_ENV, tmp_path, packaged=False)

    assert resolved == preferred
    assert origin == ".fab-test/metadata"


@pytest.mark.fab_test
def test_packaged_false_accepts_the_legacy_github_layer(tmp_path):
    """Every workflow in this repository still keeps its file there."""
    existing = _write(tmp_path, ".github/metadata", _ENV, text="environments: {}")

    resolved, origin = resolve_metadata(_ENV, tmp_path, packaged=False)

    assert resolved == existing
    assert origin == ".github/metadata"


@pytest.mark.fab_test
def test_environments_yml_fixes_the_no_packaged_rule_in_one_place(tmp_path):
    """Six callers need this rule; none of them should spell it themselves."""
    with pytest.raises(MetadataNotFoundError):
        resolve_environments_yml(tmp_path)


@pytest.mark.fab_test
def test_environments_yml_resolves_from_either_repository_layer(tmp_path):
    """The override chain reaches the file a consumer is most likely to tune."""
    existing = _write(tmp_path, ".github/metadata", _ENV, text="environments: {}")
    assert resolve_environments_yml(tmp_path).path == existing

    preferred = _write(tmp_path, ".fab-test/metadata", _ENV, text="environments: {}")
    assert resolve_environments_yml(tmp_path).path == preferred


@pytest.mark.fab_test
def test_a_resolved_file_opens_without_reaching_for_an_attribute(tmp_path):
    """Six call sites held a plain path; the result must drop into `open()`."""
    _write(tmp_path, ".fab-test/metadata", _ENV, text="environments: {}")

    found = resolve_environments_yml(tmp_path)

    with open(found, encoding="utf-8") as fh:
        assert fh.read() == "environments: {}"
    assert Path(found).is_file()


@pytest.mark.fab_test
def test_the_two_value_unpacking_existing_callers_use_keeps_working(tmp_path):
    """Regression guard for widening the return type.

    `config --show`, the registry, and `_all_analyzers` all unpack two
    values. Naming the fields is only worth doing if it stays a strict
    superset of the tuple they already destructure.
    """
    override = _write(tmp_path, ".fab-test/metadata", _RULES)

    result = resolve_metadata(_RULES, tmp_path)
    resolved, origin = result

    assert (resolved, origin) == (override, ".fab-test/metadata")
    assert result.path == override
    assert result.origin == ".fab-test/metadata"


# ---------------------------------------------------------------------------
# The last two private loaders (Environments Metadata Layers §4)
# ---------------------------------------------------------------------------

_MAP = Path("artifact-map.json")


@pytest.mark.fab_test
def test_the_artifact_map_honours_the_fab_test_layer(tmp_path):
    """`artifact-map.json` predates the layers and only read `.github/`."""
    from fabric_ci_cd_dataops.scripts._artifact_types import load_artifact_map

    _write(tmp_path, ".github/metadata", _MAP, text=json.dumps({".Report": "Legacy"}))
    _write(tmp_path, ".fab-test/metadata", _MAP, text=json.dumps({".Report": "Override"}))

    assert load_artifact_map(tmp_path)[".Report"] == "Override"


@pytest.mark.fab_test
def test_the_artifact_map_still_falls_back_to_the_packaged_copy(tmp_path):
    """Unlike environments.yml, a shipped default here is correct and safe."""
    from fabric_ci_cd_dataops.scripts._artifact_types import load_artifact_map

    assert load_artifact_map(tmp_path)[".SemanticModel"] == "SemanticModel"


@pytest.mark.fab_test
def test_a_malformed_override_still_warns_and_falls_back(tmp_path, capsys):
    """The layer search must not swallow the diagnostic it replaced."""
    from fabric_ci_cd_dataops.scripts._artifact_types import load_artifact_map

    _write(tmp_path, ".fab-test/metadata", _MAP, text="{ not json")

    result = load_artifact_map(tmp_path)

    assert result[".SemanticModel"] == "SemanticModel"
    assert ".fab-test" in capsys.readouterr().err.replace("\\", "/")


@pytest.mark.fab_test
def test_the_analyzer_runner_resolves_analyzers_json_by_default(tmp_path, monkeypatch):
    """Its --metadata-path default was a relative `.github/metadata/` string.

    Outside a checkout that names a file which cannot exist, so a pip
    install had no analyzer definitions at all.
    """
    from fabric_ci_cd_dataops.scripts.run_analyzer import AnalyzerRunner

    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)

    runner = AnalyzerRunner()

    assert runner.metadata is not None
    assert Path(runner.metadata_path).is_file()


@pytest.mark.fab_test
def test_the_analyzer_runner_still_honours_an_explicit_path(tmp_path, monkeypatch):
    """Every existing caller and test passes one."""
    from fabric_ci_cd_dataops.scripts.run_analyzer import AnalyzerRunner

    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    override = _write(tmp_path, ".fab-test/metadata", Path("analyzers.json"), text='{"analyzers": {}}')

    runner = AnalyzerRunner(str(override))

    assert Path(runner.metadata_path) == override
