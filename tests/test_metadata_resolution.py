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
    metadata_path,
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
