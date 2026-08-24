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


def test_get_report_bookmarks_parses_flat_definition(client: FabricRestClient) -> None:
    """Bookmarks are parsed from the legacy base64-encoded bookmarks.json part,
    tagged with the page named in each bookmark's exploration state."""
    import base64
    import json

    bookmarks_payload = base64.b64encode(
        json.dumps(
            {
                "bookmarks": [
                    {
                        "name": "bmk1",
                        "displayName": "Bookmark One",
                        "explorationState": {"activeSection": "page1"},
                    },
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
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One", "page_id": "page1"},
        {"bookmark_id": "bmk2", "bookmark_name": "bmk2", "page_id": ""},
    ]


def test_get_report_bookmarks_expands_a_group_into_its_children(
    client: FabricRestClient,
) -> None:
    """A bookmark group in the flat index carries no state of its own --
    its children are tested, not the group itself."""
    import base64
    import json

    bookmarks_payload = base64.b64encode(
        json.dumps(
            {
                "bookmarks": [
                    {
                        "name": "group1",
                        "displayName": "Group One",
                        "children": [
                            {
                                "name": "child1",
                                "displayName": "Child One",
                                "explorationState": {"activeSection": "page1"},
                            },
                        ],
                    },
                ]
            }
        ).encode("utf-8")
    ).decode("utf-8")
    data = {
        "definition": {
            "parts": [
                {"path": "definition/bookmarks.json", "payload": bookmarks_payload},
            ]
        }
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "child1", "bookmark_name": "Child One", "page_id": "page1"},
    ]


def test_get_report_bookmarks_parses_pbir_bookmark_files(
    client: FabricRestClient,
) -> None:
    """Bookmarks are parsed from per-file PBIR ``definition/bookmarks/*.bookmark.json``
    parts, each tagged with the page its exploration state targets."""
    import base64
    import json

    payload = base64.b64encode(
        json.dumps(
            {
                "name": "bmk1",
                "displayName": "Bookmark One",
                "explorationState": {"activeSection": "page1"},
            }
        ).encode("utf-8")
    ).decode("utf-8")
    data = {
        "definition": {
            "parts": [
                {
                    "path": "definition/bookmarks/bmk1.bookmark.json",
                    "payload": payload,
                },
                {
                    "path": "definition/bookmarks/bookmarks.json",
                    "payload": base64.b64encode(b"{}").decode("utf-8"),
                },
            ]
        }
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One", "page_id": "page1"},
    ]


def test_get_report_bookmarks_skips_a_pbir_group_files_own_part(
    client: FabricRestClient,
) -> None:
    """A PBIR bookmark group's own ``*.bookmark.json`` lists children rather
    than exploration state, and is skipped -- each child has its own part."""
    import base64
    import json

    group_payload = base64.b64encode(
        json.dumps({"name": "group1", "children": ["child1"]}).encode("utf-8")
    ).decode("utf-8")
    child_payload = base64.b64encode(
        json.dumps(
            {
                "name": "child1",
                "displayName": "Child One",
                "explorationState": {"activeSection": "page1"},
            }
        ).encode("utf-8")
    ).decode("utf-8")
    data = {
        "definition": {
            "parts": [
                {"path": "definition/bookmarks/group1.bookmark.json", "payload": group_payload},
                {"path": "definition/bookmarks/child1.bookmark.json", "payload": child_payload},
            ]
        }
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "child1", "bookmark_name": "Child One", "page_id": "page1"},
    ]


def test_get_semantic_model_roles_reads_role_file_names(
    client: FabricRestClient,
) -> None:
    """Role names come from ``definition/roles/<name>.tmdl`` part paths."""
    data = {
        "definition": {
            "parts": [
                {"path": "definition/roles/Manager.tmdl", "payload": ""},
                {"path": "definition/roles/Analyst.tmdl", "payload": ""},
                {"path": "definition/tables/Sales.tmdl", "payload": ""},
            ]
        }
    }
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        roles = client.get_semantic_model_roles("ws-1", "sm-1")

    assert roles == ["Manager", "Analyst"]


def test_get_semantic_model_roles_returns_empty_on_404(
    client: FabricRestClient,
) -> None:
    """A semantic model with no PBIP definition yields no roles, not an error."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response({}, status_code=404),
    ):
        roles = client.get_semantic_model_roles("ws-1", "sm-1")

    assert roles == []


def test_get_report_bookmarks_returns_empty_on_404(client: FabricRestClient) -> None:
    """A report with no PBIR definition yields no bookmarks, not an error --
    pages and roles are still worth testing without it."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response({}, status_code=404),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == []


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
