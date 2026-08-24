"""Contract tests for workspace-qualified targets (Artifact Targeting and Auth §3).

Scope
-----
Turning ``Sales Dev.Workspace/Sales.SemanticModel`` into the IDs the
analyzers already accept. Item resolution within a workspace already
existed (`resolve_item`); only workspace-name-to-ID was missing.

Every test drives a fake client implementing the `ServiceClient`
protocol, so this exercises the resolution rules without a Fabric tenant
and always passes on any machine.
"""

import pytest

from fabric_ci_cd_dataops.scripts._config import ConfigError, validate_config
from fabric_ci_cd_dataops.scripts._target import parse_target, workspace_conflict
from fabric_ci_cd_dataops.scripts.playwright_validation.resolver import (
    ServiceResolutionError,
    resolve_workspace_id,
)

_GUID = "33333333-3333-3333-3333-333333333333"


class _FakeClient:
    """Records lookups so tests can assert a GUID short-circuits them."""

    def __init__(self, workspaces=()):
        self._workspaces = list(workspaces)
        self.list_workspaces_calls = 0

    def list_workspaces(self):
        self.list_workspaces_calls += 1
        return self._workspaces

    def list_items(self, workspace_id, item_type):  # pragma: no cover - protocol filler
        return []

    def get_dependent_reports(self, workspace_id, semantic_model_id):  # pragma: no cover
        return []

    def get_report_dataset_id(self, workspace_id, report_id):  # pragma: no cover
        return ""


# --------------------------------------------------------------------------- #
# Workspace name resolution
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_display_name_resolves_to_its_id():
    """The common case: a name the user typed becomes the GUID the API needs."""
    client = _FakeClient([{"id": _GUID, "displayName": "Sales Dev"}])

    assert resolve_workspace_id(client, "Sales Dev") == _GUID


@pytest.mark.fab_test
def test_a_guid_is_used_verbatim_with_no_lookup():
    """Already an ID: skip the round trip entirely rather than confirm it."""
    client = _FakeClient([])

    assert resolve_workspace_id(client, _GUID) == _GUID
    assert client.list_workspaces_calls == 0


@pytest.mark.fab_test
def test_unmatched_name_lists_the_workspaces_that_are_visible():
    """Naming what the identity *can* see turns a dead end into a next step."""
    client = _FakeClient(
        [
            {"id": _GUID, "displayName": "Sales Prod"},
            {"id": "44444444-4444-4444-4444-444444444444", "displayName": "Finance"},
        ]
    )

    with pytest.raises(ServiceResolutionError) as excinfo:
        resolve_workspace_id(client, "Sales Dev")

    message = str(excinfo.value)
    assert "Sales Dev" in message
    assert "Sales Prod" in message
    assert "Finance" in message


@pytest.mark.fab_test
def test_ambiguous_name_lists_the_candidate_ids():
    """Two workspaces can share a display name; the GUIDs are the way out."""
    other = "44444444-4444-4444-4444-444444444444"
    client = _FakeClient(
        [
            {"id": _GUID, "displayName": "Sales Dev"},
            {"id": other, "displayName": "Sales Dev"},
        ]
    )

    with pytest.raises(ServiceResolutionError) as excinfo:
        resolve_workspace_id(client, "Sales Dev")

    message = str(excinfo.value)
    assert _GUID in message
    assert other in message


@pytest.mark.fab_test
def test_matching_ignores_case_and_surrounding_whitespace():
    """Display names are typed by humans, so normalize the way resolve_item does."""
    client = _FakeClient([{"id": _GUID, "displayName": "Sales Dev"}])

    assert resolve_workspace_id(client, "  sales dev  ") == _GUID


@pytest.mark.fab_test
def test_no_visible_workspaces_still_names_the_target():
    """An identity that can see nothing gets a message about that, not an empty list."""
    with pytest.raises(ServiceResolutionError) as excinfo:
        resolve_workspace_id(_FakeClient([]), "Sales Dev")

    assert "Sales Dev" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Conflict with --workspace-id
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_workspace_qualified_target_agreeing_with_the_flag_is_fine():
    """Saying the same thing twice is redundant, not contradictory."""
    target = parse_target(f"{_GUID}.Workspace/Sales.SemanticModel")

    assert workspace_conflict(target, _GUID) is None


@pytest.mark.fab_test
def test_workspace_qualified_target_disagreeing_with_the_flag_is_reported():
    """Two different workspaces in one invocation names both rather than picking."""
    target = parse_target("Sales Dev.Workspace/Sales.SemanticModel")

    message = workspace_conflict(target, _GUID)

    assert message is not None
    assert "Sales Dev" in message
    assert _GUID in message


@pytest.mark.fab_test
def test_no_conflict_when_only_one_source_names_a_workspace():
    """A flag alone, or a target alone, is the normal case."""
    assert workspace_conflict(parse_target("Sales.SemanticModel"), _GUID) is None
    assert workspace_conflict(parse_target(f"{_GUID}.Workspace/S.Report"), "") is None
    assert workspace_conflict(None, _GUID) is None


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_workspace_is_a_valid_config_key():
    """`workspace:` in fab-test.yml resolves through the existing precedence chain."""
    validate_config({"workspace": "Sales Dev"})


@pytest.mark.fab_test
def test_workspace_config_key_must_be_a_string():
    """A GUID typed without quotes should fail loudly, not resolve strangely."""
    with pytest.raises(ConfigError):
        validate_config({"workspace": 12345})
