"""Discover RLS role names for a semantic model via a live XMLA/DAX query.

Fallback for ``get_semantic_model_roles`` when the Fabric ``getDefinition``-based
TMDL discovery finds nothing (a non-PBIP-enabled semantic model): runs
``EVALUATE INFO.ROLES()`` over the model's XMLA endpoint via ADOMD.NET (through
pythonnet), which ships as a transitive dependency already -- ``pql-test``
(a hard dependency of this package) requires ``pyadomd``, which requires
``pythonnet``. See "Discover RLS roles for non-PBIP-enabled semantic models"
in ``tasks/playwright-ci-guide-epic.md`` for the investigation this closes:
the Power BI REST ``executeQueries`` API cannot run ``INFO`` functions at all,
so a live XMLA connection is the only way to ask a model what roles it has.

Confirmed live on plain ``ubuntu-latest`` (no extra runtime install): pythonnet
defaults to Mono on Linux, which isn't installed on a bare runner, so
``PYTHONNET_RUNTIME`` must be set to ``coreclr`` *before* the first
``import clr`` -- the .NET SDK GitHub-hosted runners (and this project's own
Playwright container image) already ship is enough once pythonnet is told to
use it.
"""

from __future__ import annotations

import contextlib
import os
import platform
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_ADOMD_ASSEMBLY = "Microsoft.AnalysisServices.AdomdClient"
_ADOMD_VERSION = "19.114.0"
_ADOMD_PKG_ID = "microsoft.analysisservices.adomdclient"

# Keyed cache rather than a rebound module global -- avoids `global` inside
# `_ensure_adomd_loaded` for what is otherwise a one-line memoization.
_adomd_cache: dict[str, Any] = {}


class XmlaQueryError(Exception):
    """Raised when the DAX query against a model's XMLA endpoint fails."""


def _cache_dir(lib_folder: str) -> Path:
    return Path.home() / ".fab-test" / "adomd" / _ADOMD_PKG_ID / _ADOMD_VERSION / lib_folder


def _download_adomd(lib_folder: str) -> Path:
    """Download the ADOMD.NET NuGet package and extract one ``lib/<folder>/``
    into a user-local cache, returning that directory.

    A no-op past the first call: the cache is keyed by package version, so a
    second run (or a second process) reuses what's already there.
    """
    cache = _cache_dir(lib_folder)
    if cache.is_dir() and any(p.suffix == ".dll" for p in cache.iterdir()):
        return cache

    url = (
        f"https://api.nuget.org/v3-flatcontainer/{_ADOMD_PKG_ID}/"
        f"{_ADOMD_VERSION}/{_ADOMD_PKG_ID}.{_ADOMD_VERSION}.nupkg"
    )
    prefix = f"lib/{lib_folder}/"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as fh:
            tmp_path = fh.name
        urllib.request.urlretrieve(url, tmp_path)  # fixed nuget.org host
        with zipfile.ZipFile(tmp_path) as archive:
            for member in archive.namelist():
                if not member.startswith(prefix) or member.endswith("/"):
                    continue
                rel = member[len(prefix) :]
                dest = (cache / rel).resolve()
                if not dest.is_relative_to(cache.resolve()):
                    raise OSError(f"unsafe path in ADOMD.NET package: {member}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
    return cache


def _ensure_adomd_loaded() -> Any:
    """Load and return the ``AdomdConnection`` class, downloading ADOMD.NET
    first if it isn't already cached. Cached in-process after the first call.
    """
    if "connection_cls" in _adomd_cache:
        return _adomd_cache["connection_cls"]

    lib_folder = "net472" if platform.system() == "Windows" else "net8.0"
    if platform.system() != "Windows":
        # Must be set before the first `import clr` -- pythonnet reads it
        # once, at load time, to pick a runtime.
        os.environ.setdefault("PYTHONNET_RUNTIME", "coreclr")

    try:
        import clr  # pythonnet; only imported when actually needed
    except ImportError as exc:
        raise XmlaQueryError(
            "pythonnet is not installed. It ships as a transitive dependency "
            "of pql-test, so this indicates a broken fab-test install."
        ) from exc
    except Exception as exc:
        # (not ImportError) from inside `import clr` itself when it can't
        # create a runtime -- confirmed live: PYTHONNET_RUNTIME=coreclr set,
        # but no .NET runtime installed in the container (a bare
        # ubuntu-latest runner ships one; this project's own Playwright
        # container image does not), raising "Can not determine dotnet
        # root" / "Failed to create a .NET runtime (coreclr)" uncaught,
        # once per report, before this except existed.
        raise XmlaQueryError(f"Could not load pythonnet's CLR runtime: {exc}") from exc

    try:
        cache_dir = _download_adomd(lib_folder)
    except OSError as exc:
        raise XmlaQueryError(f"Could not download ADOMD.NET: {exc}") from exc

    cache_str = str(cache_dir)
    if cache_str not in sys.path:
        sys.path.append(cache_str)

    try:
        clr.AddReference(_ADOMD_ASSEMBLY)
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection
    except Exception as exc:
        raise XmlaQueryError(f"Could not load ADOMD.NET: {exc}") from exc

    _adomd_cache["connection_cls"] = AdomdConnection
    return AdomdConnection


def _build_connection_string(
    server: str, catalog: str, access_token: str, *, roles: str = ""
) -> str:
    parts = [f"Provider=MSOLAP;Data Source={server};Initial Catalog={catalog};"]
    parts.append(f"Password={access_token};")
    if roles:
        parts.append(f"Roles={roles};")
    return "".join(parts)


def execute_dax_query(
    server: str,
    catalog: str,
    access_token: str,
    dax_query: str,
    *,
    roles: str = "",
) -> list[dict[str, Any]]:
    """Execute a DAX query against a semantic model's XMLA endpoint.

    ``server`` is the full XMLA URI (``powerbi://api.powerbi.com/v1.0/myorg/
    <WorkspaceName>``); ``catalog`` is the dataset's *display name*, not its
    GUID -- the XMLA endpoint addresses both by name. Raises
    ``XmlaQueryError`` on any failure to load ADOMD.NET, connect, or run the
    query, so a caller can distinguish "asked and got zero rows back" from
    "couldn't ask at all."
    """
    adomd_connection_cls = _ensure_adomd_loaded()
    conn_str = _build_connection_string(server, catalog, access_token, roles=roles)

    try:
        connection = adomd_connection_cls(conn_str)
        connection.Open()
    except Exception as exc:
        raise XmlaQueryError(f"Could not open XMLA connection: {exc}") from exc

    try:
        command = connection.CreateCommand()
        command.CommandText = dax_query
        try:
            reader = command.ExecuteReader()
        except Exception as exc:
            raise XmlaQueryError(f"DAX query failed: {exc}") from exc
        try:
            field_count = reader.FieldCount
            if field_count == 0:
                return []
            columns = [reader.GetName(i) for i in range(field_count)]
            rows: list[dict[str, Any]] = []
            while reader.Read():
                rows.append({col: reader[i] for i, col in enumerate(columns)})
            return rows
        finally:
            reader.Close()
    finally:
        connection.Close()
