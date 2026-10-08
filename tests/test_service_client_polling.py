"""Long-running-operation polling in the Fabric REST service client.

Fabric's ``getDefinition`` always answers HTTP 202 with ``Retry-After: 20``,
yet a semantic model export is usually done in about a second. These pin how
often the client checks back: soon enough not to idle on a finished export,
spaced out enough not to be throttled.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts.playwright_validation.service_client import (
    FabricRestClient,
    FabricToken,
    ServiceClientError,
)

_MODULE = "fab_test.scripts.playwright_validation.service_client"
_OPERATION = "https://api.fabric.microsoft.com/v1/operations/op-1"


@pytest.fixture
def client() -> FabricRestClient:
    """Return a FabricRestClient with a dummy token."""
    return FabricRestClient(FabricToken(access_token="token"))


def _accepted(retry_after: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 202
    response.headers = {"Location": _OPERATION, "Retry-After": retry_after}
    response.text = ""
    return response


def _status(status: str, *, status_code: int = 200, retry_after: str = "20") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"status": status}
    response.headers = {"Retry-After": retry_after}
    response.text = status
    return response


def _result() -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"definition": {"parts": []}}
    return response


def _sleeps_while_exporting(client: FabricRestClient, accepted: MagicMock, polls: list[MagicMock]) -> list[float]:
    """Run one getDefinition through the poll loop and return each wait."""
    with (
        patch(f"{_MODULE}.requests.request", return_value=accepted),
        patch(f"{_MODULE}.requests.get", side_effect=[*polls, _result()]),
        patch(f"{_MODULE}.time.sleep") as sleep,
    ):
        client.get_item_definition("ws-1", "sm-1")
    return [call.args[0] for call in sleep.call_args_list]


def test_given_a_long_retry_after_should_check_back_after_two_seconds(client: FabricRestClient) -> None:
    sleeps = _sleeps_while_exporting(client, _accepted("20"), [_status("Succeeded")])
    assert sleeps == [2.0]


def test_given_a_running_operation_should_back_off_up_to_retry_after(client: FabricRestClient) -> None:
    polls = [_status("Running") for _ in range(5)] + [_status("Succeeded")]
    sleeps = _sleeps_while_exporting(client, _accepted("20"), polls)
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 20.0, 20.0]


def test_given_a_retry_after_shorter_than_two_seconds_should_honor_it(client: FabricRestClient) -> None:
    sleeps = _sleeps_while_exporting(client, _accepted("1"), [_status("Succeeded")])
    assert sleeps == [1.0]


def test_given_a_throttled_status_check_should_wait_retry_after_and_keep_polling(
    client: FabricRestClient,
) -> None:
    polls = [_status("", status_code=429, retry_after="7"), _status("Succeeded")]
    sleeps = _sleeps_while_exporting(client, _accepted("20"), polls)
    assert sleeps == [2.0, 7.0]


def test_request_polls_a_long_running_operation_to_completion(
    client: FabricRestClient,
) -> None:
    """Fabric's ``getDefinition`` endpoints only ever answer with HTTP 202
    plus a ``Location`` to poll -- never the definition inline. Without
    following that operation to ``Succeeded`` and then fetching
    ``{operation}/result``, every getDefinition call got back an empty body
    (``None``), which crashed ``get_semantic_model_roles`` outright and was
    silently swallowed into "no bookmarks" for ``get_report_bookmarks``."""
    accepted = MagicMock()
    accepted.status_code = 202
    accepted.headers = {
        "Location": "https://api.fabric.microsoft.com/v1/operations/op-1",
        "Retry-After": "0",
    }
    accepted.text = ""

    running = MagicMock()
    running.status_code = 200
    running.json.return_value = {"status": "Running"}
    running.headers = {"Retry-After": "0"}

    succeeded = MagicMock()
    succeeded.status_code = 200
    succeeded.json.return_value = {"status": "Succeeded"}
    succeeded.headers = {}

    result = MagicMock()
    result.status_code = 200
    result.json.return_value = {"definition": {"parts": []}}

    with (
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.request",
            return_value=accepted,
        ),
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.get",
            side_effect=[running, succeeded, result],
        ) as mock_get,
        patch(
            "fab_test.scripts.playwright_validation.service_client.time.sleep"
        ),
    ):
        data = client.get_report_bookmarks("ws-1", "rpt-1")

    assert data == []
    result_call_url = mock_get.call_args_list[-1].args[0]
    assert result_call_url == "https://api.fabric.microsoft.com/v1/operations/op-1/result"


def test_request_raises_when_long_running_operation_fails(
    client: FabricRestClient,
) -> None:
    """A ``Failed`` operation status must surface as an error, not silently
    resolve to an empty/None result."""
    accepted = MagicMock()
    accepted.status_code = 202
    accepted.headers = {
        "Location": "https://api.fabric.microsoft.com/v1/operations/op-1",
        "Retry-After": "0",
    }
    accepted.text = ""

    failed = MagicMock()
    failed.status_code = 200
    failed.json.return_value = {"status": "Failed", "error": "boom"}
    failed.headers = {}

    with (
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.request",
            return_value=accepted,
        ),
        patch(
            "fab_test.scripts.playwright_validation.service_client.requests.get",
            return_value=failed,
        ),
        patch(
            "fab_test.scripts.playwright_validation.service_client.time.sleep"
        ),
        pytest.raises(ServiceClientError, match="boom"),
    ):
        client.get_semantic_model_roles("ws-1", "sm-1")
