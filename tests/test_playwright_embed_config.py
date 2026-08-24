"""Contract tests for Playwright embed configuration builder.

Scope
-----
The values in this module's constant block are the difference between a
report that renders and one that 403s. `tokenType` in particular was
shipped as `0` under a comment reading `models.TokenType.Embed` -- `0` is
`Aad`. Declaring an embed token as an AAD token sends the embed host down
a cluster-resolution path that an embed token cannot satisfy, so the
iframe 403s and shows its generic error page while the SDK never fires a
typed `error` event.

The equality assertion below used to encode `tokenType=0`, which made it
a mirror of the bug rather than a guard against it: it compared a
hand-written constant to itself and would have passed for any value.
`test_token_type_is_embed_not_aad` pins the correct value on its own, and
`tests/test_playwright_embed_enums.py` ties all three constants back to
the real library.
"""

from __future__ import annotations

from fabric_ci_cd_dataops.scripts.playwright_validation.embed_config import EmbedConfig, build_embed_config


def test_build_embed_config_defaults() -> None:
    """Default embed config uses report id, embed URL, and token."""
    config = build_embed_config(
        report_id="rpt-1",
        embed_url="https://app.powerbi.com/reportEmbed?reportId=rpt-1",
        embed_token="token-1",
    )

    assert config == EmbedConfig(
        type="report",
        id="rpt-1",
        embedUrl="https://app.powerbi.com/reportEmbed?reportId=rpt-1",
        accessToken="token-1",
        tokenType=1,
        permissions=0,
        viewMode=0,
        pageName="",
        bookmark=None,
    )


def test_token_type_is_embed_not_aad() -> None:
    """`tokenType` must be 1 (Embed); 0 is Aad and 403s against a real workspace.

    Pinned on its own rather than only inside the equality assertion above,
    so the reason survives even if that assertion is ever relaxed. The
    enum, read from powerbi-client@2.23.1:

        TokenType[TokenType["Aad"]   = 0
        TokenType[TokenType["Embed"] = 1
    """
    config = build_embed_config(
        report_id="rpt-1",
        embed_url="https://app.powerbi.com/reportEmbed",
        embed_token="token-1",
    )

    assert config.tokenType == 1, "0 is Aad -- an embed token declared as AAD 403s"


def test_build_embed_config_with_page_and_bookmark() -> None:
    """Page and bookmark dimensions are reflected in the embed config."""
    config = build_embed_config(
        report_id="rpt-1",
        embed_url="https://app.powerbi.com/reportEmbed",
        embed_token="token-1",
        page_id="ReportSection1",
        bookmark_id="Bookmark1",
    )

    assert config.pageName == "ReportSection1"
    assert config.bookmark == {"name": "Bookmark1"}


def test_embed_config_to_dict() -> None:
    """to_dict returns a plain dictionary for JSON serialization."""
    config = build_embed_config(
        report_id="rpt-1",
        embed_url="https://app.powerbi.com/reportEmbed",
        embed_token="token-1",
    )

    data = config.to_dict()

    assert data["type"] == "report"
    assert data["id"] == "rpt-1"
    assert data["accessToken"] == "token-1"
    assert data["bookmark"] is None
