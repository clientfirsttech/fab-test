"""analyzers.json pins fab-inspector once; several places restate that pin.

The pin is `tool_install.version`, but each install URL names the release tag
again and each platform carries its archive's sha256, so a bump that updates
one and misses another downloads a different release than the version it
reports, or one that fails verification. The .NET runtime the release needs
(`requires_runtime.min_major`) is restated by every workflow that installs
.NET to run `pbir`, and by the fab-test skill's `flags.md`. See the
fab-inspector 4.0.1 Update epic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_ANALYZERS_JSON = _ROOT / "src" / "fab_test" / "metadata" / "analyzers.json"


def _tool_install() -> dict:
    registry = json.loads(_ANALYZERS_JSON.read_text(encoding="utf-8"))["analyzer_registry"]
    return registry["pbir_inspector"]["tool_install"]


def _fallback() -> dict:
    """The .NET 8 fallback, as the bootstrap resolves it: its keys over the pin's."""
    tool = _tool_install()
    return {key: value for key, value in tool.items() if key != "runtime_fallback"} | tool["runtime_fallback"]


# The pin, and the older release a machine without its runtime falls back to.
_RELEASES = pytest.mark.parametrize("release", [_tool_install, _fallback], ids=["pin", "fallback"])


@pytest.mark.pbir
@_RELEASES
def test_every_install_url_downloads_the_pinned_release(release):
    tool = release()
    tag = f"/releases/download/v{tool['version']}/"

    stale = {platform: url for platform, url in tool["install_urls"].items() if tag not in url}

    assert stale == {}, f"install URLs that don't name v{tool['version']}: {stale}"


@pytest.mark.pbir
@_RELEASES
def test_every_platform_has_a_sha256_for_its_archive(release):
    tool = release()

    missing = set(tool["install_urls"]) - set(tool["install_sha256s"])
    malformed = {
        platform: digest
        for platform, digest in tool["install_sha256s"].items()
        if not re.fullmatch(r"[0-9a-f]{64}", digest)
    }

    assert missing == set(), f"platforms with no sha256: {sorted(missing)}"
    assert malformed == {}, f"sha256s that aren't 64 lowercase hex digits: {malformed}"


def _dotnet_floor() -> int:
    requirement = _tool_install()["requires_runtime"]
    assert requirement["name"] == "dotnet"
    return requirement["min_major"]


_DOTNET_VERSION_LINE = re.compile(r"dotnet-version:\s*[\"']?(\d+)\.")


@pytest.mark.pbir
def test_every_workflow_that_installs_dotnet_installs_the_release_s_runtime():
    """A workflow on an older major gets `doctor`'s not-ready, or a pbir
    `error` envelope, instead of findings."""
    floor = _dotnet_floor()
    workflows = sorted((_ROOT / ".github" / "workflows").glob("*.yml"))

    installed = {
        f"{path.name}:{line_no}": int(match.group(1))
        for path in workflows
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if (match := _DOTNET_VERSION_LINE.search(line))
    }
    too_old = {where: major for where, major in installed.items() if major < floor}

    assert installed, "no workflow installs .NET; this test no longer guards anything"
    assert too_old == {}, f"workflows installing .NET older than {floor}: {too_old}"


@pytest.mark.pbir
@pytest.mark.parametrize(
    "document",
    [
        Path(".github/skills/fab-test/references/flags.md"),
        Path("src/fab_test/skill/references/flags.md"),
        Path("docs/QUICK-VALIDATION.md"),
    ],
)
def test_the_docs_name_the_dotnet_runtime_the_release_needs(document):
    """The agent's skill and the human's prerequisites both say which .NET to
    install, and what runs on the fallback's."""
    floor, fallback = _dotnet_floor(), _fallback()
    text = (_ROOT / document).read_text(encoding="utf-8")

    named = sorted({int(m) for m in re.findall(r"\.NET (\d+)", text)})

    expected = sorted({floor, fallback["requires_runtime"]["min_major"]})
    assert named == expected, f"{document} names .NET {named}; the pin and its fallback need .NET {expected}"
    assert fallback["version"] in text, f"{document} doesn't name the fallback version {fallback['version']}"
