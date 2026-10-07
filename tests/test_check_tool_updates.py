"""Contract tests for tools/check_tool_updates.py (Tool Version Currency epic).

Scope
-----
Version selection per `release_source.type` (`github_release`'s prerelease
and asset-completeness filtering, `url_template`'s version-line filtering,
`pypi`'s pin-vs-latest comparison), the drift/current/unknown status
decision, and the never-fail-the-build contract on a flaky or malformed
upstream response.

Never touches the network -- every upstream call goes through
`_get_json`, monkeypatched to a fixture or a raising stub. Outside
`src/fab_test`, so not counted toward the coverage floor (see
the module's own docstring for why that tradeoff is accepted here).

    pytest tests/test_check_tool_updates.py
"""

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "tools" / "check_tool_updates.py"


def _load_module():
    """Import tools/check_tool_updates.py, which is not part of any package."""
    spec = importlib.util.spec_from_file_location("check_tool_updates", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = _load_module()


# --------------------------------------------------------------------------- #
# Version parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3.4.0", (3, 4, 0)),
        ("v3.4.0", (3, 4, 0)),
        ("V2.28.0", (2, 28, 0)),
        ("2.27", (2, 27)),
        ("1.2.3-rc1", (1, 2, 3)),
        ("", ()),
    ],
)
def test_parse_version(raw, expected):
    assert c._parse_version(raw) == expected


def test_parse_version_orders_numerically_not_lexically():
    """2.9.0 must sort below 2.10.0, unlike a plain string comparison."""
    assert c._parse_version("2.10.0") > c._parse_version("2.9.0")


# --------------------------------------------------------------------------- #
# github_release: fab-inspector's three tag flavors and one prerelease
# --------------------------------------------------------------------------- #


def _fab_inspector_release(tag, *, prerelease=False, draft=False, with_cli_asset=True):
    suffix = "-FabInspCLI.zip" if with_cli_asset else "-CLI.zip"
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "html_url": f"https://github.com/NatVanG/fab-inspector/releases/tag/{tag}",
        "assets": [
            {"name": f"linux-x64{suffix}"},
            {"name": f"win-x64{suffix}"},
            {"name": f"osx-x64{suffix}"},
        ],
    }


_PBIR_TOOL_INSTALL = {
    "version": "3.4.0",
    "release_source": {
        "type": "github_release",
        "repo": "NatVanG/fab-inspector",
        "asset_prefixes": {"linux": "linux-x64", "win32": "win-x64", "darwin": "osx-x64"},
        "asset_suffix": "-FabInspCLI.zip",
        "allow_prerelease": False,
    },
}


def test_github_release_ignores_prerelease_by_default(monkeypatch):
    """A newer prerelease (v3.5.0) is never proposed over the current stable pin."""
    releases = [
        _fab_inspector_release("v3.5.0", prerelease=True),
        _fab_inspector_release("v3.4.0"),
    ]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_github_release("pbir_inspector", _PBIR_TOOL_INSTALL)

    assert result["available"] == "3.4.0"
    assert result["status"] == c.STATUS_CURRENT


def test_github_release_skips_a_tag_flavor_missing_the_cli_asset(monkeypatch):
    """A -Winform/-AvaloniaUI-style release with no *-FabInspCLI.zip asset is not usable."""
    releases = [
        _fab_inspector_release("v3.6.0", with_cli_asset=False),
        _fab_inspector_release("v3.4.0"),
    ]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_github_release("pbir_inspector", _PBIR_TOOL_INSTALL)

    assert result["available"] == "3.4.0"


def test_github_release_skips_drafts(monkeypatch):
    releases = [
        _fab_inspector_release("v3.6.0", draft=True),
        _fab_inspector_release("v3.4.0"),
    ]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_github_release("pbir_inspector", _PBIR_TOOL_INSTALL)

    assert result["available"] == "3.4.0"


def test_github_release_reports_drift_when_a_real_stable_upgrade_exists(monkeypatch):
    releases = [
        _fab_inspector_release("v3.5.0"),
        _fab_inspector_release("v3.4.0"),
    ]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_github_release("pbir_inspector", _PBIR_TOOL_INSTALL)

    assert result["current"] == "3.4.0"
    assert result["available"] == "3.5.0"
    assert result["status"] == c.STATUS_UPDATE_AVAILABLE
    assert result["url"] == "https://github.com/NatVanG/fab-inspector/releases/tag/v3.5.0"


def test_github_release_requires_every_declared_platform_asset(monkeypatch):
    """A release missing even one platform's asset is skipped entirely."""
    incomplete = _fab_inspector_release("v3.5.0")
    incomplete["assets"] = [a for a in incomplete["assets"] if "win-x64" not in a["name"]]
    releases = [incomplete, _fab_inspector_release("v3.4.0")]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_github_release("pbir_inspector", _PBIR_TOOL_INSTALL)

    assert result["available"] == "3.4.0"


def test_github_release_allow_prerelease_true_permits_a_prerelease():
    tool_install = {
        **_PBIR_TOOL_INSTALL,
        "release_source": {**_PBIR_TOOL_INSTALL["release_source"], "allow_prerelease": True},
    }
    releases = [_fab_inspector_release("v3.5.0", prerelease=True)]

    def _fake(url, timeout=c._TIMEOUT):
        return releases

    import unittest.mock

    with unittest.mock.patch.object(c, "_get_json", _fake):
        result = c._check_github_release("pbir_inspector", tool_install)

    assert result["available"] == "3.5.0"


# --------------------------------------------------------------------------- #
# url_template: Tabular Editor's version line (2.x, never TE3)
# --------------------------------------------------------------------------- #


_TE_TOOL_INSTALL = {
    "version": "2.28.0",
    "install_url_template": "https://cdn.tabulareditor.com/files/TabularEditor.{version}.zip",
    "release_source": {
        "type": "url_template",
        "repo": "TabularEditor/TabularEditor",
        "version_line": "2",
    },
}


def _te_release(tag, *, prerelease=False, draft=False):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft}


def test_url_template_never_proposes_a_te3_tag(monkeypatch):
    releases = [_te_release("3.0.0"), _te_release("2.28.0"), _te_release("2.27.2")]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_url_template("tabular_editor_bpa", _TE_TOOL_INSTALL)

    assert result["available"] == "2.28.0"
    assert result["status"] == c.STATUS_CURRENT


def test_url_template_reports_drift_and_derives_the_cdn_url(monkeypatch):
    releases = [_te_release("2.29.0"), _te_release("2.28.0")]
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: releases)

    result = c._check_url_template("tabular_editor_bpa", _TE_TOOL_INSTALL)

    assert result["current"] == "2.28.0"
    assert result["available"] == "2.29.0"
    assert result["status"] == c.STATUS_UPDATE_AVAILABLE
    assert result["url"] == "https://cdn.tabulareditor.com/files/TabularEditor.2.29.0.zip"


def test_url_template_with_no_repo_is_unknown(monkeypatch):
    tool_install = {
        "version": "2.28.0",
        "release_source": {"type": "url_template", "version_line": "2"},
    }
    result = c._check_url_template("tabular_editor_bpa", tool_install)
    assert result["status"] == c.STATUS_UNKNOWN


# --------------------------------------------------------------------------- #
# pypi: pql-test's pin lives only in pyproject.toml
# --------------------------------------------------------------------------- #


_PQL_TEST_TOOL_INSTALL = {
    "release_source": {"type": "pypi", "package": "pql-test", "version_source": "pyproject.toml"},
}


def test_pypi_reads_the_pin_from_pyproject_toml_and_reports_drift(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["tabulate", "pql-test==0.1.12", "playwright"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(c, "_PYPROJECT_TOML", pyproject)
    monkeypatch.setattr(
        c, "_get_json", lambda url, timeout=c._TIMEOUT: {"info": {"version": "0.1.13"}}
    )

    result = c._check_pypi("pql_test", _PQL_TEST_TOOL_INSTALL)

    assert result["current"] == "0.1.12"
    assert result["available"] == "0.1.13"
    assert result["status"] == c.STATUS_UPDATE_AVAILABLE
    assert result["url"] == "https://pypi.org/project/pql-test/0.1.13/"


def test_pypi_reports_current_when_the_pin_matches_latest(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["pql-test==0.1.13"]\n', encoding="utf-8")
    monkeypatch.setattr(c, "_PYPROJECT_TOML", pyproject)
    monkeypatch.setattr(
        c, "_get_json", lambda url, timeout=c._TIMEOUT: {"info": {"version": "0.1.13"}}
    )

    result = c._check_pypi("pql_test", _PQL_TEST_TOOL_INSTALL)

    assert result["status"] == c.STATUS_CURRENT


# --------------------------------------------------------------------------- #
# npm: promptfoo is pinned in analyzers.json and published to the npm registry
# --------------------------------------------------------------------------- #


_PROMPTFOO_TOOL_INSTALL = {
    "version": "0.124.0",
    "release_source": {"type": "npm", "package": "promptfoo"},
}


def test_npm_compares_the_pin_against_the_registry_s_latest_tag(monkeypatch):
    seen: list[str] = []

    def _fake_get_json(url, timeout=c._TIMEOUT):
        seen.append(url)
        return {"version": "0.125.1"}

    monkeypatch.setattr(c, "_get_json", _fake_get_json)

    result = c._check_npm("data_agent", _PROMPTFOO_TOOL_INSTALL)

    assert seen == ["https://registry.npmjs.org/promptfoo/latest"]
    assert result["current"] == "0.124.0"
    assert result["available"] == "0.125.1"
    assert result["status"] == c.STATUS_UPDATE_AVAILABLE
    assert result["url"] == "https://www.npmjs.com/package/promptfoo/v/0.125.1"


def test_npm_reports_current_when_the_pin_matches_latest(monkeypatch):
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: {"version": "0.124.0"})

    assert c._check_npm("data_agent", _PROMPTFOO_TOOL_INSTALL)["status"] == c.STATUS_CURRENT


def test_npm_reports_unknown_on_an_unexpected_response_shape(monkeypatch):
    monkeypatch.setattr(c, "_get_json", lambda url, timeout=c._TIMEOUT: [])

    assert c._check_npm("data_agent", _PROMPTFOO_TOOL_INSTALL)["status"] == c.STATUS_UNKNOWN


# --------------------------------------------------------------------------- #
# A flaky upstream never fails the build
# --------------------------------------------------------------------------- #


def test_check_all_reports_unknown_on_a_network_error_for_every_tool(monkeypatch):
    import urllib.error

    def _raise(url, timeout=c._TIMEOUT):
        raise urllib.error.URLError("simulated outage")

    monkeypatch.setattr(c, "_get_json", _raise)

    results = c.check_all()

    assert results
    assert all(r["status"] == c.STATUS_UNKNOWN for r in results)


def test_check_all_isolates_one_tool_s_failure_from_the_others(monkeypatch):
    """One tool's malformed response must not stop the rest from being checked."""

    def _flaky(url, timeout=c._TIMEOUT):
        if "pypi.org" in url:
            raise TimeoutError("simulated timeout")
        return [{"tag_name": "v3.4.0", "prerelease": False, "draft": False, "assets": [
            {"name": "linux-x64-FabInspCLI.zip"},
            {"name": "win-x64-FabInspCLI.zip"},
            {"name": "osx-x64-FabInspCLI.zip"},
        ]}]

    monkeypatch.setattr(c, "_get_json", _flaky)
    monkeypatch.setattr(c, "_pinned_pypi_version", lambda package: "0.1.12")

    results = c.check_all()
    by_tool = {r["tool"]: r for r in results}

    assert by_tool["pql_test"]["status"] == c.STATUS_UNKNOWN
    assert by_tool["pbir_inspector"]["status"] == c.STATUS_CURRENT


def test_main_never_fails_the_build_on_unknown_status_even_with_fail_on_update(monkeypatch):
    import urllib.error

    def _raise(url, timeout=c._TIMEOUT):
        raise urllib.error.URLError("simulated outage")

    monkeypatch.setattr(c, "_get_json", _raise)

    assert c.main(["--fail-on-update"]) == 0


# --------------------------------------------------------------------------- #
# CLI surface: --format json, --fail-on-update
# --------------------------------------------------------------------------- #


def test_main_format_json_emits_one_record_per_tool_with_the_stable_shape(monkeypatch, capsys):
    fake_results = [
        {"tool": "a", "current": "1", "available": "1", "url": None, "status": c.STATUS_CURRENT},
        {"tool": "b", "current": "1", "available": "2", "url": "http://x", "status": c.STATUS_UPDATE_AVAILABLE},
    ]
    monkeypatch.setattr(c, "check_all", lambda: fake_results)

    code = c.main(["--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload == fake_results
    for record in payload:
        assert set(record) == {"tool", "current", "available", "url", "status"}


def test_main_fail_on_update_exits_nonzero_when_a_tool_has_drifted(monkeypatch):
    fake_results = [
        {"tool": "a", "current": "1", "available": "2", "url": None, "status": c.STATUS_UPDATE_AVAILABLE},
    ]
    monkeypatch.setattr(c, "check_all", lambda: fake_results)

    assert c.main(["--fail-on-update"]) == 1


def test_main_without_fail_on_update_exits_zero_despite_drift(monkeypatch):
    fake_results = [
        {"tool": "a", "current": "1", "available": "2", "url": None, "status": c.STATUS_UPDATE_AVAILABLE},
    ]
    monkeypatch.setattr(c, "check_all", lambda: fake_results)

    assert c.main([]) == 0


def test_get_json_sends_the_github_token_when_set(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "s3cr3t-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def _fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.headers)
        return _FakeResponse()

    monkeypatch.setattr(c.urllib.request, "urlopen", _fake_urlopen)

    c._get_json("https://api.github.com/repos/x/y/releases")

    assert captured["headers"].get("Authorization") == "Bearer s3cr3t-token"


def test_get_json_refuses_a_non_https_url():
    with pytest.raises(ValueError, match="Refusing to fetch"):
        c._get_json("http://example.com/insecure")
