#!/usr/bin/env python3
"""Report drift between the tool versions fab-test pins and what upstream ships.

Reads each wrapped tool's ``release_source`` from ``analyzers.json`` and asks
the declared upstream feed (a GitHub Releases API, a GitHub repo used only
for version discovery, or the PyPI JSON API) what the newest eligible release
is, then compares it against the version fab-test currently pins.

Deliberately outside ``src/``: this is maintainer tooling invoked by
``.github/workflows/check-tool-updates.yml``, never by fab-test itself and
never packaged into the wheel every user installs. If that workflow is ever
deleted, delete this script with it -- its only caller. A script whose
workflow was removed is how eight modules under ``scripts/`` became
untestable dead code (see "Standalone Tasks" in plan.md); this comment is
here so the same thing does not happen quietly a second time.

Usage:
    python tools/check_tool_updates.py [--format text|json] [--fail-on-update]

Exit codes:
    0  No drift (or drift found without --fail-on-update, or a tool's status
       could not be determined -- a flaky upstream must never fail a build)
    1  --fail-on-update was passed and at least one tool has a newer release
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Ensure UTF-8 output on Windows, where the default console pipe encoding
# (cp1252) cannot render the status symbols below.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ANALYZERS_JSON = _REPO_ROOT / "src" / "fabric_ci_cd_dataops" / "metadata" / "analyzers.json"
_PYPROJECT_TOML = _REPO_ROOT / "pyproject.toml"
_USER_AGENT = "fab-test-tool-currency-checker/1.0"
_TIMEOUT = 15
_ALLOWED_SCHEMES = frozenset({"https"})

STATUS_CURRENT = "current"
STATUS_UPDATE_AVAILABLE = "update-available"
STATUS_UNKNOWN = "unknown"


def _parse_version(value: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple of ints.

    A leading ``v`` (as in fab-inspector's ``v3.4.0`` tags) is stripped
    first. A component that isn't a plain integer (a suffix like ``-rc1``)
    stops the parse there -- good enough for the numeric-only versions every
    tool here actually publishes, and safer than guessing at a total
    ordering for something it doesn't need to compare.
    """
    value = value.lstrip("vV")
    parts: list[int] = []
    for chunk in value.split("."):
        match = re.match(r"^\d+", chunk)
        if not match:
            break
        parts.append(int(match.group()))
    return tuple(parts)


def _get_json(url: str, timeout: int = _TIMEOUT) -> Any:
    """GET ``url`` and return the parsed JSON body.

    Sends ``GITHUB_TOKEN`` as a bearer token when set and the URL is a
    GitHub API call -- the unauthenticated API allows only 60 requests/hour,
    easily exhausted by a handful of releases lookups.
    """
    scheme = urlparse(url).scheme
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Refusing to fetch a {scheme or 'scheme-less'} URL: {url}")
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - scheme checked above
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked above
        return json.loads(response.read().decode("utf-8"))


def _github_releases(repo: str) -> list[dict[str, Any]]:
    """Return up to 100 releases for ``repo``, newest first (the API's own order)."""
    return _get_json(f"https://api.github.com/repos/{repo}/releases?per_page=100")


def _load_registry() -> dict[str, Any]:
    data = json.loads(_ANALYZERS_JSON.read_text(encoding="utf-8"))
    return data.get("analyzer_registry", {})


def _pinned_pypi_version(package: str) -> str | None:
    """Read ``package``'s pinned version out of pyproject.toml's dependencies.

    The single source of truth for this pin -- deliberately not duplicated
    into analyzers.json, so there is exactly one place a bump can miss.
    """
    data = tomllib.loads(_PYPROJECT_TOML.read_text(encoding="utf-8"))
    dependencies = data.get("project", {}).get("dependencies", [])
    prefix = f"{package}=="
    for dep in dependencies:
        if dep.startswith(prefix):
            return dep[len(prefix):]
    return None


def _check_github_release(name: str, tool_install: dict[str, Any]) -> dict[str, Any]:
    """Check a tool whose releases live on GitHub and ship the assets it needs.

    Selects the newest release that is not a prerelease (unless
    ``allow_prerelease`` says otherwise) and whose assets include, for
    *every* declared platform, ``{asset_prefix}{asset_suffix}`` -- fab-
    inspector publishes three tag flavors per version (``-Winform``,
    ``-AvaloniaUI``, and the plain one that actually carries
    ``*-FabInspCLI.zip``), and a release missing even one platform's asset
    is not a usable upgrade.
    """
    release_source = tool_install["release_source"]
    repo = release_source["repo"]
    allow_prerelease = release_source.get("allow_prerelease", True)
    asset_prefixes: dict[str, str] = release_source.get("asset_prefixes", {})
    asset_suffix = release_source.get("asset_suffix", "")
    required_assets = {f"{prefix}{asset_suffix}" for prefix in asset_prefixes.values()}

    releases = _github_releases(repo)
    best_version: tuple[int, ...] | None = None
    best_tag = None
    best_url = None
    for release in releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not allow_prerelease:
            continue
        asset_names = {asset["name"] for asset in release.get("assets", [])}
        if required_assets and not required_assets.issubset(asset_names):
            continue
        parsed = _parse_version(release.get("tag_name", ""))
        if not parsed:
            continue
        if best_version is None or parsed > best_version:
            best_version = parsed
            best_tag = release["tag_name"]
            best_url = release.get("html_url")

    if best_tag is None:
        return _result(name, tool_install, available=None, url=None, status=STATUS_UNKNOWN)
    return _result(name, tool_install, available=best_tag.lstrip("vV"), url=best_url)


def _check_url_template(name: str, tool_install: dict[str, Any]) -> dict[str, Any]:
    """Check a tool downloaded from a URL template, versioned via a GitHub repo.

    The repo is consulted for version discovery only -- the actual download
    stays on the CDN template in ``install_url_template``, since that is
    where the real distribution lives (Tabular Editor's GitHub releases
    exist, but the CDN is the URL fab-test has always used and is not being
    changed here).
    """
    release_source = tool_install["release_source"]
    repo = release_source.get("repo")
    version_line = release_source.get("version_line", "")
    if not repo:
        return _result(name, tool_install, available=None, url=None, status=STATUS_UNKNOWN)

    releases = _github_releases(repo)
    best_version: tuple[int, ...] | None = None
    best_tag = None
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        if version_line and not tag.lstrip("vV").startswith(f"{version_line}."):
            continue
        parsed = _parse_version(tag)
        if not parsed:
            continue
        if best_version is None or parsed > best_version:
            best_version = parsed
            best_tag = tag

    if best_tag is None:
        return _result(name, tool_install, available=None, url=None, status=STATUS_UNKNOWN)
    version = best_tag.lstrip("vV")
    url_template = tool_install.get("install_url_template", "")
    url = url_template.format(version=version) if url_template else None
    return _result(name, tool_install, available=version, url=url)


def _check_pypi(name: str, tool_install: dict[str, Any]) -> dict[str, Any]:
    """Check a tool installed as a pinned PyPI package (pql-test)."""
    release_source = tool_install["release_source"]
    package = release_source["package"]
    current = _pinned_pypi_version(package)

    data = _get_json(f"https://pypi.org/pypi/{package}/json")
    available = data.get("info", {}).get("version")
    if not available:
        return _result(name, tool_install, available=None, url=None, status=STATUS_UNKNOWN, current=current)
    url = f"https://pypi.org/project/{package}/{available}/"
    return _result(name, tool_install, available=available, url=url, current=current)


def _result(
    name: str,
    tool_install: dict[str, Any],
    *,
    available: str | None,
    url: str | None,
    status: str | None = None,
    current: str | None = None,
) -> dict[str, Any]:
    """Build one tool's report record, comparing ``current`` against ``available``."""
    if current is None:
        current = tool_install.get("version")
    if status is None:
        if available is None or current is None:
            status = STATUS_UNKNOWN
        elif _parse_version(available) > _parse_version(current):
            status = STATUS_UPDATE_AVAILABLE
        else:
            status = STATUS_CURRENT
    return {
        "tool": name,
        "current": current,
        "available": available,
        "url": url,
        "status": status,
    }


_CHECKERS = {
    "github_release": _check_github_release,
    "url_template": _check_url_template,
    "pypi": _check_pypi,
}


def check_all() -> list[dict[str, Any]]:
    """Return one report record per tool that declares a `release_source`.

    A tool with no `release_source` (nothing wired up yet) is silently
    skipped rather than reported unknown -- there is nothing drifting
    because nothing is being watched, which is a different fact than "we
    tried to watch it and failed".
    """
    registry = _load_registry()
    results = []
    for name, config in registry.items():
        tool_install = config.get("tool_install") or {}
        release_source = tool_install.get("release_source")
        if not release_source:
            continue
        checker = _CHECKERS.get(release_source.get("type", ""))
        if checker is None:
            results.append(
                _result(name, tool_install, available=None, url=None, status=STATUS_UNKNOWN)
            )
            continue
        try:
            results.append(checker(name, tool_install))
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ):
            # A flaky upstream, an API shape change, or a missing required
            # field must never fail the check for every other tool, and
            # must never fail the build on its own -- see module docstring.
            results.append(
                _result(name, tool_install, available=None, url=None, status=STATUS_UNKNOWN)
            )
    return results


def _print_text(results: list[dict[str, Any]]) -> None:
    for r in results:
        if r["status"] == STATUS_CURRENT:
            print(f"✓ {r['tool']}: {r['current']} (current)")
        elif r["status"] == STATUS_UPDATE_AVAILABLE:
            print(f"↑ {r['tool']}: {r['current']} → {r['available']} available ({r['url']})")
        else:
            print(f"? {r['tool']}: status unknown (current pin: {r['current']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on-update",
        action="store_true",
        help="Exit 1 if any tool has a newer release available",
    )
    args = parser.parse_args(argv)

    results = check_all()

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        _print_text(results)

    if args.fail_on_update and any(r["status"] == STATUS_UPDATE_AVAILABLE for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
