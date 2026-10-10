"""Every fabric-artifacts <RULE-ID>.rdl fixture must trip the rule it is named for.

The fixture's file name is the contract: DS-02.rdl exists to violate DS-02.
Each fixture is synced from the workspace as a Git Integration-shaped
``<RULE-ID>.PaginatedReport/<RULE-ID>.rdl`` folder; ACC-03 additionally keeps a
flat ``ACC-03.rdl`` sibling (no .platform wrapper) so discovery is proven to
find the same fixture with or without Git Integration conventions. A fixture
whose rule has no check yet is a known gap, not a failure -- it is
xfail(strict) so the day the check lands the test flips and forces the xfail
off. Rules with no fixture at all are listed by test_gaps_are_tracked.
"""

from pathlib import Path

import pytest

from fab_test.scripts._rdl_lint import implemented_rule_ids, load_rule_catalog, parse_rdl, run_checks

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_CATALOG = load_rule_catalog(_REPO / "src" / "fab_test" / "metadata" / "rules" / "rdl-rules.json")
_RULE_IDS = {rule["id"] for rule in _CATALOG}
_IMPLEMENTED = implemented_rule_ids(_CATALOG)
_FIXTURES = sorted(p for p in (_REPO / "fabric-artifacts").rglob("*.rdl") if p.stem in _RULE_IDS)


def _param(path: Path):
    if path.stem in _IMPLEMENTED:
        return pytest.param(path, id=path.stem)
    return pytest.param(
        path, id=path.stem, marks=pytest.mark.xfail(strict=True, reason=f"{path.stem} has no check yet (gap)")
    )


@pytest.mark.parametrize("rdl", [_param(p) for p in _FIXTURES])
def test_fixture_trips_its_named_rule(rdl: Path):
    root, namespace = parse_rdl(rdl)
    fired = {rule for f in run_checks(root, namespace, _CATALOG) for rule in f["rule"].split("/")}
    assert rdl.stem in fired


# Rules a fixture trips beyond the one it is named for. A ratchet: the
# hand-built fixtures predate isolation, and QRY-07's long inline SQL is
# DS-07 by definition. Shrink this; never grow it.
_KNOWN_EXTRA = {
    "ACC-03": {"DS-02", "DS-05", "DS-07", "LAY-05", "QRY-01", "QRY-02", "QRY-04"},
    "DS-05": {"DS-02", "DS-07"},
    "DS-07": {"DS-02", "DS-05", "QRY-01"},
    "LAY-03": {"SUB-01"},
    "QRY-01": {"DS-02", "DS-05", "DS-07"},
    "QRY-02": {"ACC-03", "DS-02", "DS-05", "DS-07", "QRY-01"},
    "QRY-04": {"DS-02", "DS-05", "DS-07", "LAY-05", "QRY-01", "QRY-02"},
    "QRY-07": {"DS-07"},
    "STR-01": {"DS-02"},
    "SUB-01": {"LAY-03"},
}


@pytest.mark.parametrize("rdl", [pytest.param(p, id=p.stem) for p in _FIXTURES if p.stem in _IMPLEMENTED])
def test_fixture_trips_no_unrelated_rule(rdl: Path):
    root, namespace = parse_rdl(rdl)
    fired = {rule for f in run_checks(root, namespace, _CATALOG) for rule in f["rule"].split("/")}
    assert fired - {rdl.stem} == _KNOWN_EXTRA.get(rdl.stem, set())
