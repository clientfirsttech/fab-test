"""A ratchet on the complexity report (Complexity and Coverage §7).

Scope
-----
The report in `build.yml` is non-gating on purpose: blocking a PR on a
function being one branch too long is the kind of gate people learn to
route around. But a report nobody reads is how 36 findings quietly became
45 over two epics, which is what this epic then had to pay back.

So the count is ratcheted instead. Any single function may exceed the
threshold — that stays a judgement call — but the *total* may not grow.
Lowering `max-complexity` was the other option and turns out not to be the
lever: at 15 it is already tighter than every surviving function, so
tightening it further would add noise rather than signal.

To lower the ceiling after a cleanup, run the report and set it to the new
count. Raising it needs a reason in the commit message, matching the
convention already stated in plan.md.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_RULES = "C901,PLR0911,PLR0912,PLR0913,PLR0915"

# Measured 2026-08-25. The Complexity and Coverage refactor took the report
# from 45 to 31; Review Cleanup task 5 took it to 29; Complexity Cleanup took
# it to 6 -- every addressable finding except deploy.py and
# check_promotion_safety.py, deliberately left out of scope pending the
# dead-code audit in plan.md's "Audit what the pipeline deletion stranded"
# task. A ratchet: down, never up.
COMPLEXITY_CEILING = 6


@pytest.fixture(scope="module")
def _report() -> list[str]:
    """Run ruff once for the whole module.

    Every test here wants the same list, and shelling out per test cost
    about four seconds of the suite for identical output.
    """
    ruff = shutil.which("ruff") or shutil.which("ruff.exe")
    command = (
        [ruff] if ruff else [sys.executable, "-m", "ruff"]
    ) + ["check", "src", "--select", _RULES, "--output-format", "concise"]
    proc = subprocess.run(
        command, cwd=_ROOT, capture_output=True, text=True, check=False
    )
    return [ln for ln in proc.stdout.splitlines() if ": C901" in ln or ": PLR" in ln]


@pytest.mark.fab_test
def test_the_complexity_report_does_not_grow(_report):
    """The total may fall or hold; it may not rise without a deliberate change."""
    findings = _report

    assert len(findings) <= COMPLEXITY_CEILING, (
        f"complexity findings rose to {len(findings)} (ceiling {COMPLEXITY_CEILING}).\n"
        "Split the new offender, or raise COMPLEXITY_CEILING with a reason in the "
        "commit message.\n" + "\n".join(findings)
    )


@pytest.mark.fab_test
def test_the_ceiling_is_not_left_slack_after_a_cleanup(_report):
    """A ceiling well above the real count stops being a ratchet.

    Allows a small margin so an unrelated one-line change does not force a
    ceiling edit, but flags the case where a cleanup landed and nobody
    tightened the number afterwards.
    """
    findings = _report

    assert COMPLEXITY_CEILING - len(findings) <= 5, (
        f"only {len(findings)} findings remain but the ceiling is "
        f"{COMPLEXITY_CEILING}; lower it to {len(findings)} to keep the ratchet honest"
    )


@pytest.mark.fab_test
@pytest.mark.parametrize(
    ("module", "function"),
    [
        # Matched on file *and* name: `main` alone also matches deploy.py's,
        # which is a different function and still over the threshold.
        ("fab_test.py", "`main`"),
        ("fab_test.py", "`_run_analyzer`"),
        ("fab_test_summary.py", "`_print_all_summary`"),
        ("invoke_tabular_editor_bpa.py", "`run_bpa`"),
        ("invoke_pql_test.py", "`run_pql_test`"),
    ],
)
def test_a_refactored_function_stays_out_of_the_report(module, function, _report):
    """Named explicitly: these were the epic's targets and must not regress.

    The count ratchet alone would let one of these grow back while another
    improved, netting out to no visible change.
    """
    offenders = [ln for ln in _report if module in ln and function in ln]

    assert not offenders, f"{function} in {module} is back in the report: {offenders}"
