"""Integration guard: embed constants must match the real powerbi-client enums.

Scope
-----
`embed_config.py` hard-codes three numeric enum values that the Power BI
JavaScript client interprets. Nothing in the offline contract tier can
tell a right value from a wrong one -- a unit test comparing the constant
to a literal is a mirror, not a guard, and that is exactly how
`tokenType = 0` ("Aad", labelled "Embed") survived long enough to 403
every real run.

This module closes that gap by parsing the enums out of the same CDN
bundle `render_spec.py` injects and asserting our
constants match. It is marked `integration` because it needs network:
per pytest.ini's convention it skips when the bundle is unreachable
rather than failing a laptop or an offline CI leg.
"""

from __future__ import annotations

import re

import pytest

from fab_test.scripts.playwright_validation.embed_config import (
    _PERMISSIONS_READ,
    _TOKEN_TYPE_EMBED,
    _VIEW_MODE_VIEW,
)

pytestmark = [pytest.mark.integration, pytest.mark.playwright]

# Pinned to the exact build render_spec.py injects, so this
# guard cannot pass against a different version than the one we embed with.
_BUNDLE_URL = "https://cdn.jsdelivr.net/npm/powerbi-client@2.23.1/dist/powerbi.js"


@pytest.fixture(scope="module")
def bundle() -> str:
    """Return the powerbi-client bundle, skipping when it cannot be fetched."""
    requests = pytest.importorskip("requests")
    try:
        response = requests.get(_BUNDLE_URL, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"powerbi-client bundle unreachable: {exc}")
    return response.text


def _enum_value(bundle: str, enum_name: str, member: str) -> int:
    """Extract one member's numeric value from a TypeScript-compiled enum.

    tsc emits reverse-mapped enums as `Name[Name["Member"] = <n>] = "Member"`,
    so the assignment is the authoritative value regardless of declaration order.
    """
    match = re.search(
        rf'{enum_name}\[{enum_name}\["{member}"\]\s*=\s*(\d+)\]',
        bundle,
    )
    assert match, f"{enum_name}.{member} not found in the bundle"
    return int(match.group(1))


def test_token_type_embed_matches_the_library(bundle: str) -> None:
    """The constant that broke production: Embed is 1, Aad is 0."""
    assert _enum_value(bundle, "TokenType", "Embed") == _TOKEN_TYPE_EMBED
    assert _enum_value(bundle, "TokenType", "Aad") != _TOKEN_TYPE_EMBED


def test_permissions_read_matches_the_library(bundle: str) -> None:
    assert _enum_value(bundle, "Permissions", "Read") == _PERMISSIONS_READ


def test_view_mode_view_matches_the_library(bundle: str) -> None:
    assert _enum_value(bundle, "ViewMode", "View") == _VIEW_MODE_VIEW
