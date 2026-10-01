"""Every .fabric/artifacts/rdl/<RULE-ID>.rdl must trip the rule it is named for.

The fixture's file name is the contract: DS-02.rdl exists to violate DS-02.
A fixture whose rule has no check yet is a known gap, not a failure -- it is
xfail(strict) so the day the check lands the test flips and forces the xfail
off. Rules with no fixture at all are listed by test_gaps_are_tracked.
"""

from pathlib import Path

import pytest

from fab_test.scripts._rdl_lint import CHECKS, load_rule_catalog, parse_rdl, run_checks

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_FIXTURES = sorted((_REPO / ".fabric" / "artifacts" / "rdl").glob("*.rdl"))
_CATALOG = load_rule_catalog(_REPO / "src" / "fab_test" / "metadata" / "rules" / "rdl-rules.json")


def _param(path: Path):
    if path.stem in CHECKS:
        return pytest.param(path, id=path.stem)
    return pytest.param(
        path, id=path.stem, marks=pytest.mark.xfail(strict=True, reason=f"{path.stem} has no check yet (gap)")
    )


@pytest.mark.parametrize("rdl", [_param(p) for p in _FIXTURES])
def test_fixture_trips_its_named_rule(rdl: Path):
    root, namespace = parse_rdl(rdl)
    fired = {rule for f in run_checks(root, namespace, _CATALOG) for rule in f["rule"].split("/")}
    assert rdl.stem in fired
