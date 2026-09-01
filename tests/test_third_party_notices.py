"""THIRD-PARTY.md names every wrapped tool's license -- a bump has a
documentation blast radius nothing else tracks, the same reasoning behind
tests/test_pql_test_pin_consistency.py for the pql-test pin.

    pytest -m fab_test tests/test_third_party_notices.py
"""

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_THIRD_PARTY = _ROOT / "THIRD-PARTY.md"
_ANALYZERS_JSON = _ROOT / "src" / "fab_test" / "metadata" / "analyzers.json"
_PYPROJECT = _ROOT / "pyproject.toml"

# (registry key, expected substring naming the tool in THIRD-PARTY.md)
_WRAPPED_TOOLS = (
    ("tabular_editor_bpa", "Tabular Editor"),
    ("pbir_inspector", "fab-inspector"),
    ("pbir_a11y", "pbir-a11y"),
)

# Pinned pip dependencies whose license is not a short permissive one --
# each needs a row and a dedicated section here, the same as a tool_install
# analyzer, even though pip installs it rather than the tool bootstrap.
_NON_PERMISSIVE_PIP_DEPENDENCIES = ("pql-test",)


@pytest.mark.fab_test
def test_third_party_md_exists():
    assert _THIRD_PARTY.exists(), "THIRD-PARTY.md is missing"


@pytest.mark.fab_test
def test_every_tool_install_analyzer_is_named_in_third_party_md():
    """Every analyzer with a `tool_install` block downloads or builds an
    external tool -- each one needs a row here, not just the ones that existed
    when this file was written."""
    text = _THIRD_PARTY.read_text(encoding="utf-8")
    registry = json.loads(_ANALYZERS_JSON.read_text(encoding="utf-8"))["analyzer_registry"]

    missing = [
        name
        for name, needle in _WRAPPED_TOOLS
        if name in registry and "tool_install" in registry[name] and needle not in text
    ]
    assert missing == [], f"THIRD-PARTY.md does not name: {missing}"


@pytest.mark.fab_test
def test_every_non_permissive_pip_dependency_is_named_in_third_party_md():
    """pql-test isn't a `tool_install`-bootstrapped analyzer -- it's a
    regular pinned pip dependency in pyproject.toml -- so the tool_install
    scan above can't see it. It still needs a row here since it ships to
    every installer, unlike the on-demand-downloaded tools."""
    text = _THIRD_PARTY.read_text(encoding="utf-8")
    pyproject = _PYPROJECT.read_text(encoding="utf-8")

    missing = [
        name
        for name in _NON_PERMISSIVE_PIP_DEPENDENCIES
        if re.search(rf'"{re.escape(name)}==', pyproject) and name not in text
    ]
    assert missing == [], f"THIRD-PARTY.md does not name pinned dependency: {missing}"


@pytest.mark.fab_test
def test_pql_test_license_states_its_key_terms_as_written():
    """Business Source License 1.1 terms must be stated as written (name,
    Additional Use Grant, Change Date/License) -- no interpretation of what
    they permit, which is a legal question for the license text itself."""
    text = _THIRD_PARTY.read_text(encoding="utf-8")
    assert "Business Source License" in text or "BUSL" in text
    assert "Additional Use Grant" in text
    assert "Change Date" in text


@pytest.mark.fab_test
def test_pbir_a11y_license_is_named_as_source_available_not_permissive():
    """PolyForm Shield is the one non-permissive license here; it must read
    as such, not blend in with the two MIT entries next to it."""
    text = _THIRD_PARTY.read_text(encoding="utf-8")
    assert "PolyForm Shield" in text
    assert "source-available" in text.lower()


@pytest.mark.fab_test
def test_notices_state_nothing_is_vendored():
    """Every wrapped tool is downloaded/built at runtime, never shipped in
    the wheel -- the one fact a reader must not have to infer."""
    text = _THIRD_PARTY.read_text(encoding="utf-8")
    assert "does not vendor" in text or "not vendored" in text.lower()


@pytest.mark.fab_test
def test_readme_points_at_third_party_notices():
    """A reader checking the license first lands in README, not THIRD-PARTY.md
    directly -- the pointer has to exist for the notice to be found at all."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "THIRD-PARTY.md" in readme
