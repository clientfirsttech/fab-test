"""Contract tests for the XMLA/DAX role-discovery helper."""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts.playwright_validation import xmla_roles
from fab_test.scripts.playwright_validation.xmla_roles import (
    XmlaQueryError,
    _build_connection_string,
    _download_adomd,
    execute_dax_query,
)


def test_build_connection_string_basic() -> None:
    """The connection string names the workspace's XMLA URI, the dataset's
    display name as the catalog, and the bearer token -- no Roles= segment
    when none is requested."""
    conn_str = _build_connection_string(
        "powerbi://api.powerbi.com/v1.0/myorg/Sales", "SalesModel", "token-1"
    )
    assert conn_str == (
        "Provider=MSOLAP;Data Source=powerbi://api.powerbi.com/v1.0/myorg/Sales;"
        "Initial Catalog=SalesModel;Password=token-1;"
    )


def test_build_connection_string_with_roles() -> None:
    """A named role is appended as its own Roles= segment."""
    conn_str = _build_connection_string("server", "catalog", "token-1", roles="Manager")
    assert conn_str.endswith("Roles=Manager;")


def _mock_reader(rows: list[dict[str, object]]) -> MagicMock:
    """Build a MagicMock standing in for ADOMD.NET's DataReader."""
    columns = list(rows[0]) if rows else []
    reader = MagicMock()
    reader.FieldCount = len(columns)
    reader.GetName.side_effect = lambda i: columns[i]
    state = {"i": -1}

    def _read() -> bool:
        state["i"] += 1
        return state["i"] < len(rows)

    def _getitem(i: int) -> object:
        return rows[state["i"]][columns[i]]

    reader.Read.side_effect = _read
    reader.__getitem__.side_effect = _getitem
    return reader


def _mock_connection_cls(reader: MagicMock) -> tuple[MagicMock, MagicMock]:
    command = MagicMock()
    command.ExecuteReader.return_value = reader
    connection = MagicMock()
    connection.CreateCommand.return_value = command
    return MagicMock(return_value=connection), connection


def test_execute_dax_query_returns_rows() -> None:
    """Rows come back as one dict per row, keyed by ADOMD.NET's own column
    names (e.g. "[Name]") -- parsing those names is the caller's job."""
    rows_in = [{"[Name]": "Manager"}, {"[Name]": "Analyst"}]
    reader = _mock_reader(rows_in)
    connection_cls, connection = _mock_connection_cls(reader)

    with patch(
        "fab_test.scripts.playwright_validation.xmla_roles._ensure_adomd_loaded",
        return_value=connection_cls,
    ):
        rows = execute_dax_query("server", "catalog", "token-1", "EVALUATE INFO.ROLES()")

    assert rows == rows_in
    connection.Open.assert_called_once()
    connection.Close.assert_called_once()
    assert connection.CreateCommand.return_value.CommandText == "EVALUATE INFO.ROLES()"


def test_execute_dax_query_returns_empty_for_no_columns() -> None:
    """A query whose result table has no columns yields no rows, not a crash."""
    reader = MagicMock()
    reader.FieldCount = 0
    connection_cls, _ = _mock_connection_cls(reader)

    with patch(
        "fab_test.scripts.playwright_validation.xmla_roles._ensure_adomd_loaded",
        return_value=connection_cls,
    ):
        rows = execute_dax_query("server", "catalog", "token-1", "EVALUATE {}")

    assert rows == []


def test_execute_dax_query_raises_on_connection_open_failure() -> None:
    """A connection failure raises XmlaQueryError, distinguishable from a
    query that ran and legitimately returned zero rows."""
    connection = MagicMock()
    connection.Open.side_effect = RuntimeError("boom")
    connection_cls = MagicMock(return_value=connection)

    with (
        patch(
            "fab_test.scripts.playwright_validation.xmla_roles._ensure_adomd_loaded",
            return_value=connection_cls,
        ),
        pytest.raises(XmlaQueryError, match="Could not open XMLA connection"),
    ):
        execute_dax_query("server", "catalog", "token-1", "EVALUATE INFO.ROLES()")


def test_execute_dax_query_raises_on_query_failure_and_still_closes() -> None:
    """A bad DAX query raises XmlaQueryError, and the connection is always
    closed -- even on failure, not just the happy path."""
    command = MagicMock()
    command.ExecuteReader.side_effect = RuntimeError("bad dax")
    connection = MagicMock()
    connection.CreateCommand.return_value = command
    connection_cls = MagicMock(return_value=connection)

    with (
        patch(
            "fab_test.scripts.playwright_validation.xmla_roles._ensure_adomd_loaded",
            return_value=connection_cls,
        ),
        pytest.raises(XmlaQueryError, match="DAX query failed"),
    ):
        execute_dax_query("server", "catalog", "token-1", "EVALUATE bogus")

    connection.Close.assert_called_once()


def test_download_adomd_reuses_existing_cache(tmp_path) -> None:
    """A cache directory that already holds a .dll is reused with no
    network call -- the common case after the first run."""
    from fab_test.scripts.playwright_validation import xmla_roles

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "Microsoft.AnalysisServices.AdomdClient.dll").write_bytes(b"stub")

    with (
        patch.object(xmla_roles, "_cache_dir", return_value=cache),
        patch(
            "fab_test.scripts.playwright_validation.xmla_roles.urllib.request.urlretrieve"
        ) as mock_urlretrieve,
    ):
        result = _download_adomd("net8.0")

    assert result == cache
    mock_urlretrieve.assert_not_called()


def test_ensure_adomd_loaded_wraps_clr_runtime_failure(monkeypatch) -> None:
    """pythonnet raises a bare RuntimeError -- not ImportError -- from
    inside `import clr` itself when it can't create a CLR runtime (e.g. no
    .NET installed in the container). Confirmed live: this escaped as an
    uncaught traceback, once per report, before this except clause existed.
    Must surface as XmlaQueryError instead."""
    xmla_roles._adomd_cache.clear()
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "clr":
            raise RuntimeError("Can not determine dotnet root")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(XmlaQueryError, match="Could not load pythonnet's CLR runtime"):
        xmla_roles._ensure_adomd_loaded()
