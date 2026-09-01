"""Contract tests for the CI-safe browser-opening helper (Open Report Flag epic, Task 2).

Scope
-----
Only `open_report_in_browser` itself: launching a real browser is never
exercised (there is none in CI), so every case here stubs `webbrowser.open`
and asserts on its call/return, not on an actual window appearing.

Always passes on any machine -- no browser is launched, no analyzer binary
is invoked.
"""

import pytest

from fabric_ci_cd_dataops.scripts import _report_html
from fabric_ci_cd_dataops.scripts._report_html import open_report_in_browser


@pytest.mark.fab_test
def test_opens_the_path_when_not_ci(tmp_path, monkeypatch):
    monkeypatch.setattr(_report_html, "_is_ci", lambda: False)
    calls = []
    monkeypatch.setattr(_report_html.webbrowser, "open", lambda url: calls.append(url) or True)
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")

    opened = open_report_in_browser(report)

    assert opened is True
    assert len(calls) == 1
    assert calls[0].startswith("file://")
    assert report.name in calls[0]


@pytest.mark.fab_test
def test_skips_the_browser_under_ci(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(_report_html, "_is_ci", lambda: True)
    calls = []
    monkeypatch.setattr(_report_html.webbrowser, "open", lambda url: calls.append(url) or True)
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")

    opened = open_report_in_browser(report)

    assert opened is False
    assert calls == []
    assert str(report) in capsys.readouterr().out


@pytest.mark.fab_test
def test_falls_back_to_printing_when_no_browser_is_available(tmp_path, monkeypatch, capsys):
    """`webbrowser.open` returning False (no browser found) must not raise."""
    monkeypatch.setattr(_report_html, "_is_ci", lambda: False)
    monkeypatch.setattr(_report_html.webbrowser, "open", lambda url: False)
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")

    opened = open_report_in_browser(report)

    assert opened is False
    assert str(report) in capsys.readouterr().out


@pytest.mark.fab_test
def test_a_raising_webbrowser_is_swallowed_and_falls_back_to_printing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(_report_html, "_is_ci", lambda: False)

    def _boom(url):
        raise RuntimeError("no display")

    monkeypatch.setattr(_report_html.webbrowser, "open", _boom)
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")

    opened = open_report_in_browser(report)  # must not raise

    assert opened is False
    assert str(report) in capsys.readouterr().out


@pytest.mark.fab_test
def test_a_missing_path_is_skipped_without_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(_report_html, "_is_ci", lambda: False)
    calls = []
    monkeypatch.setattr(_report_html.webbrowser, "open", lambda url: calls.append(url) or True)
    missing = tmp_path / "does-not-exist.html"

    opened = open_report_in_browser(missing)

    assert opened is False
    assert calls == []


@pytest.mark.fab_test
def test_a_missing_path_prints_nothing_new(tmp_path, monkeypatch, capsys):
    """No dangling-path noise: the caller already prints the failure context."""
    monkeypatch.setattr(_report_html, "_is_ci", lambda: False)
    missing = tmp_path / "does-not-exist.html"

    open_report_in_browser(missing)

    assert capsys.readouterr().out == ""
