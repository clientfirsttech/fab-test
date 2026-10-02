"""Offline checks for the opt-in Python Azure compatibility proof."""

from urllib.parse import parse_qs, urlsplit

import pytest

from tools.prove_azure_playwright import connection_options

pytestmark = pytest.mark.playwright


def test_connection_uses_current_service_contract(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://example.test/playwrightworkspaces/workspace/browsers")
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "test-token")

    options = connection_options("proof-run")

    query = parse_qs(urlsplit(options["endpoint"]).query)
    assert query == {
        "runId": ["proof-run"],
        "os": ["linux"],
        "sourceType": ["PlaywrightWorkspacesTestRun"],
        "api-version": ["2025-09-01"],
    }
    assert options["headers"]["Authorization"] == "Bearer test-token"
    assert "test-token" not in options["endpoint"]
    assert options["timeout"] == 30000
    assert options["expose_network"] == "<loopback>"


@pytest.mark.parametrize("missing", ["PLAYWRIGHT_SERVICE_URL", "PLAYWRIGHT_SERVICE_ACCESS_TOKEN"])
def test_missing_credential_names_variable_without_value(monkeypatch, missing):
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://example.test/browsers")
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv(missing)

    with pytest.raises(ValueError, match=missing) as raised:
        connection_options("proof-run")

    assert "test-token" not in str(raised.value)


@pytest.mark.parametrize("endpoint", [
    "http://example.test/browsers",
    "wss://user:password@example.test/browsers",
    "wss://example.test/browsers?token=test-token",
])
def test_unsafe_endpoint_is_rejected_without_echoing_it(monkeypatch, endpoint):
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", endpoint)
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "test-token")

    with pytest.raises(ValueError, match="PLAYWRIGHT_SERVICE_URL") as raised:
        connection_options("proof-run")

    assert endpoint not in str(raised.value)
    assert "test-token" not in str(raised.value)
