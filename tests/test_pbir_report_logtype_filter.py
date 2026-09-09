"""Contract test for the PBIR Inspector Log Type filter fix (PBIR TestRun.html
Log Type Filter epic).

FabInspCLI's ``TestRun.html`` filters results client-side via
``matchLogType()``, which checks ``item.LogType === 2`` to decide whether a
row is an Error. But the CLI's own ``MessageTypeEnum`` (verified against
``NatVanG/fab-inspector``'s source) is ``Error = 0, Warning = 1,
Information = 2, ...``, and a rule result's ``LogType`` is only ever
``Error`` or ``Warning`` -- never ``Information`` -- so the "Error" filter
option always matches zero rows. The "Warning" branch (``=== 1``) is
already correct and must stay untouched.

Always passes on any machine: no PBIR Inspector binary is invoked.
"""

from pathlib import Path

import pytest

from fab_test.scripts._pbir_report_fixups import fix_log_type_filter

_BROKEN_MATCH_LOG_TYPE = """\
        function matchLogType(item, filterLogType) {
            if (filterLogType === "any") {
                return true;
            }

            const normalizedLogType = normalizeText(item.LogType);
            const isWarning = item.LogType === 1 || normalizedLogType === "1" || normalizedLogType === "warning";
            const isError = item.LogType === 2 || normalizedLogType === "2" || normalizedLogType === "error";

            if (filterLogType === "warning") {
                return isWarning;
            }

            if (filterLogType === "error") {
                return isError;
            }

            return true;
        }"""


def _write_report(tmp_path: Path, body: str = _BROKEN_MATCH_LOG_TYPE) -> Path:
    report = tmp_path / "TestRun.html"
    report.write_text(f"<html><body><script>{body}</script></body></html>", encoding="utf-8")
    return report


@pytest.mark.pbir
def test_broken_error_check_is_corrected_to_log_type_zero(tmp_path):
    report = _write_report(tmp_path)

    fix_log_type_filter(report)

    html = report.read_text(encoding="utf-8")
    assert "item.LogType === 2" not in html
    assert 'normalizedLogType === "2"' not in html
    assert "item.LogType === 0" in html
    assert 'normalizedLogType === "0"' in html


@pytest.mark.pbir
def test_warning_check_is_left_unchanged(tmp_path):
    report = _write_report(tmp_path)

    fix_log_type_filter(report)

    html = report.read_text(encoding="utf-8")
    assert 'item.LogType === 1 || normalizedLogType === "1" || normalizedLogType === "warning"' in html


@pytest.mark.pbir
def test_missing_report_file_does_not_raise(tmp_path):
    fix_log_type_filter(tmp_path / "does-not-exist.html")  # no exception


@pytest.mark.pbir
def test_report_without_the_expected_marker_is_left_untouched(tmp_path):
    """A future template change should degrade gracefully, not crash the run."""
    report = _write_report(tmp_path, body="console.log('no filter here');")

    fix_log_type_filter(report)

    assert report.read_text(encoding="utf-8") == (
        "<html><body><script>console.log('no filter here');</script></body></html>"
    )


@pytest.mark.pbir
def test_already_patched_report_is_a_no_op(tmp_path):
    """Running the fix twice (e.g. a rerun over the same native_out) must not
    corrupt an already-corrected file."""
    report = _write_report(tmp_path)
    fix_log_type_filter(report)
    once_patched = report.read_text(encoding="utf-8")

    fix_log_type_filter(report)

    assert report.read_text(encoding="utf-8") == once_patched
