"""Build Power BI JavaScript embed configuration for Playwright tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EmbedConfig:
    """Payload passed to the Power BI JavaScript client's ``embed`` method."""

    type: str
    id: str
    embedUrl: str
    accessToken: str
    tokenType: int
    permissions: int
    viewMode: int
    pageName: str
    bookmark: dict[str, str] | None

    def to_dict(self) -> dict[str, Any]:
        """Return the embed configuration as a dictionary."""
        return asdict(self)


# Numeric values align with the powerbi-client enum constants used by the CDN build.
_TOKEN_TYPE_EMBED = 0  # models.TokenType.Embed
_PERMISSIONS_READ = 0  # models.Permissions.Read
_VIEW_MODE_VIEW = 0  # models.ViewMode.View


def build_embed_config(
    report_id: str,
    embed_url: str,
    embed_token: str,
    page_id: str = "",
    bookmark_id: str = "",
) -> EmbedConfig:
    """Create an embed configuration for a report/page/bookmark combination."""
    bookmark = {"name": bookmark_id} if bookmark_id else None
    return EmbedConfig(
        type="report",
        id=report_id,
        embedUrl=embed_url,
        accessToken=embed_token,
        tokenType=_TOKEN_TYPE_EMBED,
        permissions=_PERMISSIONS_READ,
        viewMode=_VIEW_MODE_VIEW,
        pageName=page_id,
        bookmark=bookmark,
    )
