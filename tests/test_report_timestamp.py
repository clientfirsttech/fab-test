"""Contract tests for run timestamps and table styling.

Scope
-----
Reports show when the analyzer ran. The timestamp comes from the
*envelope*, stamped by `Timer` when the run starts — not from render time.
That keeps the renderer computing nothing and keeps rendering
deterministic: the same envelope still produces the same bytes, so a
report regenerated from a stored envelope does not silently disagree with
the original.

Always passes on any machine.
"""

import re

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_envelope import (
    ENVELOPE_OPTIONAL_KEYS,
    EnvelopeIdentity,
    Timer,
    build_envelope,
)
from fabric_ci_cd_dataops.scripts._report_html import render_report

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")


# --------------------------------------------------------------------------- #
# Timer
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_timer_records_a_utc_start_time():
    """Wall-clock, unlike elapsed_ms which is monotonic and has no epoch."""
    with Timer() as timer:
        pass

    assert _ISO_UTC.match(timer.started_at), timer.started_at


@pytest.mark.fab_test
def test_timer_still_measures_elapsed_milliseconds():
    """The new field is additive; duration measurement is unchanged."""
    with Timer() as timer:
        pass

    assert isinstance(timer.elapsed_ms, int)


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_started_at_is_an_optional_envelope_key():
    assert "started_at" in ENVELOPE_OPTIONAL_KEYS


@pytest.mark.fab_test
def test_started_at_is_omitted_when_not_supplied():
    """Optional means absent, consistent with the HTML path key."""
    envelope = build_envelope(EnvelopeIdentity("bpa", "x"), status="passed")

    assert "started_at" not in envelope


@pytest.mark.fab_test
def test_started_at_is_carried_when_supplied():
    envelope = build_envelope(
        EnvelopeIdentity("bpa", "x"),
        status="passed",
        started_at="2026-08-20T12:00:00+00:00",
    )

    assert envelope["started_at"] == "2026-08-20T12:00:00+00:00"


# --------------------------------------------------------------------------- #
# Report rendering
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_report_shows_the_run_time_and_duration():
    envelope = build_envelope(
        EnvelopeIdentity("bpa", "Sales.SemanticModel"),
        status="passed",
        started_at="2026-08-20T12:00:00+00:00",
        duration_ms=1500,
    )

    html = render_report(envelope)

    assert "2026-08-20T12:00:00+00:00" in html
    assert "1.5" in html or "1500" in html


@pytest.mark.fab_test
def test_report_labels_the_time_as_utc():
    """A bare timestamp invites the reader to assume local time."""
    envelope = build_envelope(
        EnvelopeIdentity("bpa", "x"), status="passed",
        started_at="2026-08-20T12:00:00+00:00",
    )

    assert "UTC" in render_report(envelope)


@pytest.mark.fab_test
def test_a_report_without_a_timestamp_still_renders():
    """Envelopes predating this key must not break the renderer."""
    html = render_report(build_envelope(EnvelopeIdentity("bpa", "x"), status="passed"))

    assert "<!DOCTYPE html>" in html


@pytest.mark.fab_test
def test_rendering_stays_deterministic_with_a_timestamp():
    """The time comes from the envelope, so re-rendering cannot drift."""
    envelope = build_envelope(
        EnvelopeIdentity("bpa", "x"), status="passed",
        started_at="2026-08-20T12:00:00+00:00",
    )

    assert render_report(envelope) == render_report(envelope)


# --------------------------------------------------------------------------- #
# Table styling
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_summary_tables_use_the_boxed_style():
    """Boxed borders make column boundaries unambiguous."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_list

    rows = [{
        "analyzer": "bpa", "aliases": (), "glob": "*.SemanticModel",
        "matched_artifacts": 1, "required_tool": "Tabular Editor", "scopes": ["path"],
    }]
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_list(rows, output_format="text")

    assert "╭" in buffer.getvalue(), "expected a rounded box border"


@pytest.mark.fab_test
def test_status_labels_carry_no_emoji():
    """Emoji with variation selectors are counted as one column but drawn as
    two, which is what pushed the Status column out of alignment."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _status_label

    for status in ("passed", "failed", "warning", "skipped", "dry-run"):
        label = _status_label(status)
        assert all(ord(ch) < 0x2000 for ch in label), f"{status!r} -> {label!r}"
