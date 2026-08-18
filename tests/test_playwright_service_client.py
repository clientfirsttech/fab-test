"""Contract tests for the Fabric REST service client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.service_client import (
    FabricRestClient,
    FabricToken,
    ServiceClientError,
)


@pytest.fixture
def client() -> FabricRestClient:
    """Return a FabricRestClient with a dummy token."""
    return FabricRestClient(FabricToken(access_token="token"))


def _mock_response(json_data: dict[str, Any], status_code: int = 200) -> MagicMock:
    """Build a mock requests response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.text = str(json_data)
    return response


def test_list_items_filters_by_type(client: FabricRestClient) -> None:
    """Only items matching the requested type are returned."""
    data = {
        "value": [
            {"id": "rpt-1", "displayName": "Sales Report", "type": "Report"},
            {"id": "sm-1", "displayName": "Sales Model", "type": "SemanticModel"},
        ]
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        items = client.list_items("ws-1", "Report")

    assert len(items) == 1
    assert items[0]["id"] == "rpt-1"
    assert items[0]["type"] == "Report"


def test_get_report_pages_returns_normalized_ids(client: FabricRestClient) -> None:
    """Pages are returned with page_id and page_name."""
    data = {
        "value": [
            {"name": "page1", "displayName": "Page One"},
            {"name": "page2", "displayName": "Page Two"},
        ]
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        pages = client.get_report_pages("ws-1", "rpt-1")

    assert pages == [
        {"page_id": "page1", "page_name": "Page One"},
        {"page_id": "page2", "page_name": "Page Two"},
    ]


def test_get_report_bookmarks_parses_definition(client: FabricRestClient) -> None:
    """Bookmarks are parsed from the base64-encoded bookmarks.json part."""
    import base64
    import json

    bookmarks_payload = base64.b64encode(
        json.dumps(
            {
                "bookmarks": [
                    {"name": "bmk1", "displayName": "Bookmark One"},
                    {"name": "bmk2"},
                ]
            }
        ).encode("utf-8")
    ).decode("utf-8")
    data = {
        "definition": {
            "parts": [
                {
                    "path": "definition/bookmarks.json",
                    "payload": bookmarks_payload,
                }
            ]
        }
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One"},
        {"bookmark_id": "bmk2", "bookmark_name": "bmk2"},
    ]


def test_get_dependent_reports_returns_reports(client: FabricRestClient) -> None:
    """Dependent reports are normalized from the API response."""
    data = {
        "value": [
            {
                "id": "rpt-1",
                "name": "Sales Report",
                "workspaceId": "ws-1",
            }
        ]
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        reports = client.get_dependent_reports("ws-1", "sm-1")

    assert len(reports) == 1
    assert reports[0]["id"] == "rpt-1"
    assert reports[0]["displayName"] == "Sales Report"


def test_request_raises_on_http_error(client: FabricRestClient) -> None:
    """HTTP errors are raised as ServiceClientError with status and body."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response({}, status_code=401),
    ), pytest.raises(ServiceClientError) as exc_info:
        client.list_items("ws-1", "Report")

    assert exc_info.value.status_code == 401
