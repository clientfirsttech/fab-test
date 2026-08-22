"""Contract tests for Playwright embed configuration builder."""

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
        tokenType=0,
        permissions=0,
        viewMode=0,
        pageName="",
        bookmark=None,
    )


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
