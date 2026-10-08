"""Contract tests for the Fabric REST service client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts.playwright_validation.service_client import (
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "child1", "bookmark_name": "Child One", "page_id": "page1"},
    ]


def test_get_report_bookmarks_parses_a_legacy_report_json_definition(
    client: FabricRestClient,
) -> None:
    """A report that was never PBIR-converted keeps its bookmarks inside
    ``report.json``'s embedded config, not in ``definition/bookmarks/`` --
    discovery finds them there too, or every bookmark in the six reports of
    a classic workspace goes untested."""
    import base64
    import json

    report_json = {
        "config": json.dumps(
            {
                "bookmarks": [
                    {
                        "name": "bmk1",
                        "displayName": "Bookmark One",
                        "explorationState": {"activeSection": "page1"},
                    },
                    {
                        "name": "group1",
                        "displayName": "Group One",
                        "children": [
                            {
                                "name": "child1",
                                "displayName": "Child One",
                                "explorationState": {"activeSection": "page2"},
                            },
                        ],
                    },
                ]
            }
        ),
        "sections": [],
    }
    data = {
        "definition": {
            "parts": [
                {"path": "definition.pbir", "payload": base64.b64encode(b"{}").decode("utf-8")},
                {
                    "path": "report.json",
                    "payload": base64.b64encode(
                        json.dumps(report_json).encode("utf-8")
                    ).decode("utf-8"),
                },
            ]
        }
    }
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One", "page_id": "page1"},
        {"bookmark_id": "child1", "bookmark_name": "Child One", "page_id": "page2"},
    ]


def test_get_report_bookmarks_reads_a_legacy_config_given_as_an_object(
    client: FabricRestClient,
) -> None:
    """Some exports carry ``report.json``'s config as an object rather than
    an embedded JSON string -- both shapes name the same bookmarks."""
    import base64
    import json

    report_json = {
        "config": {
            "bookmarks": [
                {
                    "name": "bmk1",
                    "displayName": "Bookmark One",
                    "explorationState": {"activeSection": "page1"},
                },
            ]
        }
    }
    data = {
        "definition": {
            "parts": [
                {
                    "path": "report.json",
                    "payload": base64.b64encode(
                        json.dumps(report_json).encode("utf-8")
                    ).decode("utf-8"),
                },
            ]
        }
    }
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One", "page_id": "page1"},
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        bookmarks = client.get_report_bookmarks("ws-1", "rpt-1")

    assert bookmarks == [
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One", "page_id": "page1"},
    ]


def test_get_report_bookmarks_parses_a_bom_prefixed_pbir_bookmark_file(
    client: FabricRestClient,
) -> None:
    """PBIR JSON parts are often written with a UTF-8 BOM (Power BI Desktop
    / git export tooling); a bookmark file with one must still decode
    instead of silently disappearing from discovery."""
    import base64
    import json

    payload = base64.b64encode(
        b"\xef\xbb\xbf"
        + json.dumps(
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
            ]
        }
    }
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        roles = client.get_semantic_model_roles("ws-1", "sm-1")

    assert roles == ["Manager", "Analyst"]


def test_get_report_bookmarks_calls_the_fabric_getdefinition_endpoint(
    client: FabricRestClient,
) -> None:
    """Report bookmarks must be read from the Fabric REST API's item-based
    ``getDefinition`` (``api.fabric.microsoft.com/v1/workspaces/.../reports/
    .../getDefinition``), not the legacy Power BI ``/v1.0/myorg/groups/...``
    surface -- that surface has no ``getDefinition`` route for reports and
    404s outright, which silently emptied bookmark discovery for every
    report (masked because the caller only treats a 404 as "no bookmarks")."""
    data = {"definition": {"parts": []}}
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ) as mock_request:
        client.get_report_bookmarks("ws-1", "rpt-1")

    called_url = mock_request.call_args.args[1]
    assert called_url == (
        "https://api.fabric.microsoft.com/v1/workspaces/ws-1"
        "/reports/rpt-1/getDefinition"
    )


def test_get_semantic_model_roles_falls_back_to_xmla_on_404(
    client: FabricRestClient,
) -> None:
    """A semantic model with no PBIP definition (getDefinition 404s) falls
    back to a live `INFO.ROLES()` DAX query over its XMLA endpoint rather
    than reporting "no roles" on the strength of a 404 alone -- that 404 is
    exactly the non-PBIP-enabled-model case this fallback exists for."""
    with (
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.request",
            return_value=_mock_response({}, status_code=404),
        ),
        patch.object(client, "get_workspace_name", return_value="Sales"),
        patch.object(client, "get_dataset_name", return_value="SalesModel"),
        patch(
            "fab_test.scripts.playwright_validation.xmla_roles.execute_dax_query",
            return_value=[{"RoleName": "Manager"}, {"RoleName": "Analyst"}],
        ) as mock_execute,
    ):
        roles = client.get_semantic_model_roles("ws-1", "sm-1")

    assert roles == ["Manager", "Analyst"]
    server_arg = mock_execute.call_args.args[0]
    assert server_arg == "powerbi://api.powerbi.com/v1.0/myorg/Sales"
    catalog_arg = mock_execute.call_args.args[1]
    assert catalog_arg == "SalesModel"


def test_get_semantic_model_roles_falls_back_to_xmla_when_tmdl_has_no_role_parts(
    client: FabricRestClient,
) -> None:
    """A definition that downloads fine but names no `definition/roles/*.tmdl`
    parts still tries the XMLA fallback -- an empty TMDL role list and "this
    model genuinely has no roles" are not the same fact."""
    data = {"definition": {"parts": [{"path": "definition/tables/Sales.tmdl", "payload": ""}]}}
    with (
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.request",
            return_value=_mock_response(data),
        ),
        patch.object(client, "get_workspace_name", return_value="Sales"),
        patch.object(client, "get_dataset_name", return_value="SalesModel"),
        patch(
            "fab_test.scripts.playwright_validation.xmla_roles.execute_dax_query",
            return_value=[],
        ),
    ):
        roles = client.get_semantic_model_roles("ws-1", "sm-1")

    assert roles == []


def test_get_semantic_model_roles_xmla_fallback_failure_raises(
    client: FabricRestClient,
) -> None:
    """When the fallback itself can't run (XMLA query failure), the caller
    must see an error, not a silent `[]` -- otherwise "couldn't check" and
    "checked, found none" are indistinguishable, exactly the gap this
    fallback was built to close."""
    from fab_test.scripts.playwright_validation.xmla_roles import XmlaQueryError

    with (
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.request",
            return_value=_mock_response({}, status_code=404),
        ),
        patch.object(client, "get_workspace_name", return_value="Sales"),
        patch.object(client, "get_dataset_name", return_value="SalesModel"),
        patch(
            "fab_test.scripts.playwright_validation.xmla_roles.execute_dax_query",
            side_effect=XmlaQueryError("could not load ADOMD.NET"),
        ),
        pytest.raises(ServiceClientError, match="XMLA role discovery failed"),
    ):
        client.get_semantic_model_roles("ws-1", "sm-1")


def test_get_workspace_name_reads_the_display_name(client: FabricRestClient) -> None:
    """The XMLA endpoint addresses a workspace by display name, not GUID."""
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response({"name": "Sales"}),
    ):
        assert client.get_workspace_name("ws-1") == "Sales"


def test_get_dataset_name_reads_the_display_name(client: FabricRestClient) -> None:
    """The XMLA endpoint's Initial Catalog is the dataset's display name, not GUID."""
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response({"name": "SalesModel"}),
    ):
        assert client.get_dataset_name("ws-1", "sm-1") == "SalesModel"


def test_get_report_bookmarks_returns_empty_on_404(client: FabricRestClient) -> None:
    """A report with no PBIR definition yields no bookmarks, not an error --
    pages and roles are still worth testing without it."""
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response(data),
    ):
        reports = client.get_dependent_reports("ws-1", "sm-1")

    assert len(reports) == 1
    assert reports[0]["id"] == "rpt-1"
    assert reports[0]["displayName"] == "Sales Report"


def test_request_raises_on_http_error(client: FabricRestClient) -> None:
    """HTTP errors are raised as ServiceClientError with status and body."""
    with patch(
        "fab_test.scripts.playwright_validation.service_client.requests.request",
        return_value=_mock_response({}, status_code=401),
    ), pytest.raises(ServiceClientError) as exc_info:
        client.list_items("ws-1", "Report")

    assert exc_info.value.status_code == 401


_REQUEST = "fab_test.scripts.playwright_validation.service_client.requests.request"


def test_get_report_dataset_ids_reads_the_power_bi_dataset_behind_a_paginated_report(
    client: FabricRestClient,
) -> None:
    """A paginated report with no local .rdl names its dataset only in its
    datasources -- as the catalog of a sobe_wowvirtualserver connection."""
    data = {
        "value": [
            {
                "datasourceType": "AnalysisServices",
                "connectionDetails": {
                    "server": "pbiazure://api.powerbi.com/",
                    "database": "sobe_wowvirtualserver-4c353b5c-d311-4e90-b9d1-5766b87f59dc",
                },
            },
            {"datasourceType": "Sql", "connectionDetails": {"database": "sales"}},
        ]
    }
    with patch(_REQUEST, return_value=_mock_response(data)) as request:
        dataset_ids = client.get_report_dataset_ids("ws-1", "rpt-1")

    assert dataset_ids == ["4c353b5c-d311-4e90-b9d1-5766b87f59dc"]
    assert request.call_args.args[1].endswith("/groups/ws-1/reports/rpt-1/datasources")


def test_get_paginated_report_definition_returns_the_rdl_text(
    client: FabricRestClient,
) -> None:
    """The deployed definition's .rdl part is decoded -- BOM and all -- so it
    parses the same as a local file would."""
    import base64

    rdl = "﻿<Report><ReportParameters/></Report>"
    data = {
        "definition": {
            "parts": [
                {"path": ".platform", "payload": base64.b64encode(b"{}").decode()},
                {
                    "path": "Sales.rdl",
                    "payload": base64.b64encode(rdl.encode("utf-8")).decode(),
                },
            ]
        }
    }
    with patch(_REQUEST, return_value=_mock_response(data)) as request:
        text = client.get_paginated_report_definition("ws-1", "rpt-1")

    assert text == "<Report><ReportParameters/></Report>"
    assert request.call_args.args[1].endswith("/v1/workspaces/ws-1/items/rpt-1/getDefinition")


def test_get_paginated_report_definition_is_empty_when_there_is_no_rdl_part(
    client: FabricRestClient,
) -> None:
    """A definition with no .rdl part yields nothing to parse, not a crash."""
    with patch(_REQUEST, return_value=_mock_response({"definition": {"parts": []}})):
        assert client.get_paginated_report_definition("ws-1", "rpt-1") == ""


def test_execute_dax_query_returns_the_first_tables_rows(
    client: FabricRestClient,
) -> None:
    """A parameter's valid-values query comes back as rows keyed by column."""
    data = {"results": [{"tables": [{"rows": [{"Table[Column B]": 2}, {"Table[Column B]": 4}]}]}]}
    with patch(_REQUEST, return_value=_mock_response(data)) as request:
        rows = client.execute_dax_query("ws-1", "ds-1", "EVALUATE T")

    assert rows == [{"Table[Column B]": 2}, {"Table[Column B]": 4}]
    assert request.call_args.args[1].endswith("/groups/ws-1/datasets/ds-1/executeQueries")
    assert request.call_args.kwargs["json"] == {"queries": [{"query": "EVALUATE T"}]}
