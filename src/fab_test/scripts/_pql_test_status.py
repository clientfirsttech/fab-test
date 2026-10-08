"""Classify a finished pql-test run: its status, message and counts.

Pure functions over pql-test's own output, kept apart from the wrapper that
runs it. The rule they share: "did anything run?" is asked before "did it
pass?", so an empty or unreachable run never reads as a green check.
"""

from __future__ import annotations

from typing import Any


def is_skipped(result: dict[str, Any]) -> bool:
    """Return True when a pql-test result entry represents a skipped test."""
    return bool(result.get("skipped"))


def summarize_results(
    test_results: list[dict[str, Any]] | None,
) -> dict[str, int] | None:
    """Count passed/failed/skipped when pql-test did not report its own counters."""
    if not test_results:
        return None
    total = len(test_results)
    passed = sum(1 for r in test_results if isinstance(r, dict) and r.get("passed"))
    skipped = sum(
        1 for r in test_results if isinstance(r, dict) and is_skipped(r)
    )
    return {
        "passed": passed,
        "failed": total - passed - skipped,
        "skipped": skipped,
        "total": total,
    }


_CONNECTION_ERROR_MARKER = "a connection cannot be made"


def _is_connection_error(result: dict[str, Any]) -> bool:
    """Whether a failing result's error is pql-test being unable to reach the model.

    pql-test discovers tests statically from the .SemanticModel's PQL
    definitions -- no live connection needed -- then tries to execute each
    one. When the model is unreachable (e.g. a closed Desktop session), each
    execution fails with this ADOMD.NET message rather than an assertion
    mismatch.
    """
    error = result.get("error") or ""
    return _CONNECTION_ERROR_MARKER in str(error).lower()


def is_connection_skip(findings: list[dict[str, Any]]) -> bool:
    """Whether every failure in this run was pql-test failing to reach the model.

    One genuine assertion failure among connection errors still fails the
    run -- a real failure must never hide behind a platform-availability
    skip.
    """
    return bool(findings) and all(_is_connection_error(f) for f in findings)


NOTHING_RAN = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}


_DISCOVERY_FAILED_MARKER = "live test discovery failed against "


def discovery_connection_error(output: str) -> str:
    """pql-test's reason when live discovery could not connect to a deployed model, else "".

    Live discovery is the only way pql-test finds tests in a deployed model,
    and when the connection fails it prints a warning and reports "No tests
    found." -- which reads as an empty model. Only a connection failure is
    returned: a model reached without PQL.Assert installed really has no tests.
    """
    for line in output.splitlines():
        _, marker, rest = line.partition(_DISCOVERY_FAILED_MARKER)
        if marker and "AdomdConnectionException" in rest:
            return rest.split(": ", 1)[-1].strip()
    return ""


def _nothing_ran_message(returncode: int, connection_error: str) -> str:
    """Say why a run with no tests and no findings ran nothing."""
    if connection_error:
        return (
            f"pql-test ran no tests: could not connect to the model ({connection_error}). "
            "pql-test connects as its own sign-in; check `pql-test auth status`"
        )
    if returncode == 0:
        return "pql-test found no tests to run in this model"
    return "pql-test ran no tests"


def classify(
    test_summary: dict[str, int] | None,
    findings: list[dict[str, Any]],
    returncode: int,
    connection_error: str = "",
) -> tuple[str, str]:
    """Classify the run and build its message.

    An all-skipped run is reported as skipped, not failed. Skips mean the
    platform or workspace was unavailable, and vision.md is explicit that
    platform gaps degrade to skips -- so CI does not go red for missing
    credentials, while a real assertion failure still does.

    A non-zero exit with no test results at all -- no native output, or a
    total of zero -- means pql-test never connected to the model (most
    commonly a local Desktop session that closed). There is nothing to
    report as a finding, so this degrades to skipped the same way, instead
    of the misleading "0 tests, 0 passed, 0 failed, 0 skipped" failed
    message a bare fall-through would produce.

    A run can also have results -- pql-test discovers tests statically from
    the model's TMDL, so it reports a count of tests it never managed to
    run, each failing with the same connection-refused error rather than an
    assertion mismatch. Nothing executed, so that is reported as a warning
    with no tests: not `failed` (nothing asserted wrong), not `passed`
    (a green check over an empty run is how a developer comes to believe
    tests ran when they did not). Only when every failure shares that
    signature, though -- one genuine assertion failure among connection
    errors must still fail the run.
    """
    counts = test_summary or {}
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    total = counts.get("total", 0)
    counter_msg = f"{total} tests, {passed} passed, {failed} failed, {skipped} skipped"

    # "Did anything run?" is asked before "did it pass?": zero tests passing
    # is not a pass, and a green check is how a developer comes to believe
    # tests ran when none did.
    if total == 0 and not findings:
        return "warning", _nothing_ran_message(returncode, connection_error)
    if returncode == 0 and not findings:
        return "passed", f"pql-test passed: {counter_msg}"
    all_skipped = (
        test_summary is not None and total > 0 and passed == 0 and failed == 0
        and skipped == total
    )
    if all_skipped:
        return "skipped", f"pql-test skipped: {counter_msg}"
    if is_connection_skip(findings):
        return "warning", "pql-test ran no tests: could not connect to the model"
    return "failed", f"pql-test failed: {counter_msg}"
