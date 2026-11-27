"""promptfoo provider for Fabric Data Agents (Data Agent Testing epic).

A port of fabric-data-agent-testing-template's ``provider.ts`` to promptfoo's
Python contract, ``call_api(prompt, options, context)``. Each call creates an
assistant and a thread, posts the prompt, runs it, polls until the run ends,
reads the agent's last reply, and deletes the thread -- unless the test names
a ``conversation``, whose thread is kept for the next turn.

promptfoo loads the package-level entry point by path; that entry point imports
this module using the interpreter selected by ``PROMPTFOO_PYTHON``.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fab_test.scripts import _data_agent_provider_run as provider_run
from fab_test.scripts import _http_policy as policy
from fab_test.scripts._credentials import (
    AUTH_CHOICES,
    DATA_AGENT_AUTH_VAR,
    AzureCliSignInError,
    IncompleteServicePrincipalError,
    ServicePrincipal,
    azure_cli_token,
    data_agent_auth,
    redact_secrets,
    resolve_service_principal,
)

DATA_AGENT_API_VERSION = "2024-05-01-preview"
_DEFAULT_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_POLL_SECONDS = 2
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
ALLOWED_HOSTS_VAR = "FAB_TEST_DATA_AGENT_ALLOWED_HOSTS"
_TOKEN_HOST_SUFFIXES = (".fabric.microsoft.com", ".powerbi.com")
PROGRESS_VAR = "FAB_TEST_DATA_AGENT_PROGRESS"
_PROGRESS_LOCK = threading.Lock()

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_THREAD_CACHE: dict[str, str] = {}
_BLOCKED: dict[str, tuple[float, str, bool]] = {}  # agent URL -> (until, why, for the whole run)
_SECRETS: set[str] = set()
_TOKEN_LOCK = threading.Lock()
_THREAD_LOCK = threading.Lock()
_BLOCK_SECONDS_WITHOUT_HEADER = 60.0  # Fabric's request quota is counted in 60 s windows


class _Final(RuntimeError):
    """A failure no retry can fix (credentials, a rejected token, missing access): report it at once."""

    status: int | None = None  # the HTTP status behind it, when there was one
    wait: float | None = None  # a server's wait behind it (a posted turn's block), which still blocks the agent


class _Retry(RuntimeError):
    """A failure asking again may fix. ``delay`` is the server's wait (a floor), None for plain backoff."""

    def __init__(self, message: str, delay: float | None = None) -> None:
        super().__init__(message)
        self.delay = delay
        self.status: int | None = None


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


def _monotonic() -> float:
    return time.monotonic()


def _scope() -> str:
    return os.environ.get("FABRIC_SCOPE") or _DEFAULT_SCOPE


def _auth_mode() -> str:
    """"az" or "service-principal": the wrapper's choice, else the chain (Data Agent az login epic)."""
    requested = os.environ.get(DATA_AGENT_AUTH_VAR, "")
    if requested in AUTH_CHOICES:
        return requested
    try:
        return data_agent_auth()
    except IncompleteServicePrincipalError as exc:
        raise _Final(f"{exc}; `fab-test auth status` shows what is set") from None


def _identity() -> str:
    """Who asked, as the sign-in chose it: the wrapper's choice, else the chain the provider itself follows."""
    try:
        return "your az login identity" if _auth_mode() == "az" else "the service principal"
    except _Final:
        return "the service principal"  # half-set: the principal is what was meant


def _principal() -> ServicePrincipal:
    """The service principal fab-test resolves everywhere (env, then .fab-test/.env or .env); nothing else."""
    try:
        principal = resolve_service_principal()
    except IncompleteServicePrincipalError as exc:
        raise _Final(f"{exc}; `fab-test auth status` shows what is set") from None
    if principal is None:
        raise _Final(
            "Data Agent tests need a service principal: set FABRIC_TENANT_ID, FABRIC_CLIENT_ID and "
            "FABRIC_CLIENT_SECRET, in the environment or .fab-test/.env; `fab-test auth status` shows what is set"
        )
    _SECRETS.add(principal.client_secret)
    return principal


def _redact(text: str) -> str:
    """Remove the client secret (from the environment or a .env file) and every token this process holds."""
    text = redact_secrets(text)
    tokens = {token for token, _expiry in _TOKEN_CACHE.values()}
    for value in _SECRETS | tokens:
        if len(value) >= 8:
            text = text.replace(value, "<redacted>")
    return _BEARER.sub("Bearer <redacted>", text)


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    cached = getattr(exc, "_fab_test_body", None)
    if cached is not None:
        return cached
    body = ""
    with contextlib.suppress(Exception):
        payload = exc.read()
        body = payload.decode("utf-8", errors="replace") if payload else ""
    exc._fab_test_body = body  # read once: the stream can't be read twice
    return body


def _error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        detail = _http_error_body(exc).strip() or str(exc.reason or exc)
        return _redact(f"HTTP {exc.code}: {detail}")
    return _redact(str(exc))


def _allowed_host(host: str) -> bool:
    """Fabric and Power BI hosts, plus exact hosts the caller's environment names (decision 17).

    Read from the environment, never the suite: whoever writes a suite controls its URL,
    so a suite must not be able to widen where the token goes.
    """
    host = host.lower().rstrip(".")
    if host.endswith(_TOKEN_HOST_SUFFIXES):
        return True
    extra = os.environ.get(ALLOWED_HOSTS_VAR, "")
    return host in {item.strip().lower() for item in extra.split(",") if item.strip()}


def _check_destination(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise _Final(f"Data Agent URLs must use https: {parsed.scheme}://{parsed.hostname or ''}")
    if not _allowed_host(parsed.hostname or ""):
        raise _Final(
            f"fab-test sends the Fabric token only to Fabric or Power BI hosts, not {parsed.hostname!r}. "
            f"Remove the suite's base_url/fabric_urls, or allow the exact host in the caller's "
            f"{ALLOWED_HOSTS_VAR} (comma-separated)"
        )
    if parsed.username or parsed.password:
        raise _Final(f"Data Agent URLs must not carry user info ({parsed.hostname!r}); "
                     "the token is the only credential")
    return parsed


def destination_problem(url: Any) -> str | None:
    """The run's refusal for a URL the token must not go to, or None. Lint shares it (decision 18)."""
    try:
        _check_destination(str(url).rstrip("/"))
    except _Final as exc:
        return str(exc)
    return None


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib keeps the Authorization header across a redirect, so fab-test follows none."""

    def redirect_request(self, _req, _fp, code, _msg, _headers, newurl):  # urllib calls it positionally
        host = urllib.parse.urlsplit(newurl).hostname
        raise _Final(f"the Data Agent API answered HTTP {code}, a redirect to {host!r}; fab-test does not follow "
                     "redirects with a token. Check the agent URL")


_OPENER = urllib.request.build_opener(_RefuseRedirects())


def _urlopen(request: urllib.request.Request, timeout: float):
    return _OPENER.open(request, timeout=timeout)


def _http_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    token = kwargs.get("token")
    parsed = _check_destination(url) if token else urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise _Final(f"Data Agent URLs must use https: {parsed.geturl()}")
    data = kwargs.get("json")
    body = json.dumps(data).encode("utf-8") if data is not None else kwargs.get("data")
    headers = kwargs.get("headers") or {"Content-Type": "application/json"}
    if token:
        headers = {**headers, "Authorization": "Bearer " + token}
    request = urllib.request.Request(parsed.geturl(), data=body, headers=headers, method=method)  # noqa: S310
    with _urlopen(request, timeout=kwargs.get("timeout", 30)) as response:
        payload = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(payload) if payload else {}
    except ValueError:
        start = " ".join(payload.split())[:120]
        raise _Final(_redact(f"{parsed.hostname} answered with a body that is not JSON, starting: {start}")) from None


def _field(data: Any, key: str, url: str) -> Any:
    """A 2xx without what the call needs is final (aidd-polite-http): name the host and the fields that came back,
    never their values."""
    if isinstance(data, dict) and data.get(key):
        return data[key]
    host = urllib.parse.urlsplit(url).hostname or url
    sent = ", ".join(sorted(map(str, data))) if isinstance(data, dict) and data else "nothing"
    raise _Final(_redact(f"{host} answered without '{key}' (it sent: {sent}); its API may have changed"))


def _token_url(principal: ServicePrincipal) -> str:
    return f"https://login.microsoftonline.com/{principal.tenant_id}/oauth2/v2.0/token"


def _token_cache_key(scope: str, principal: ServicePrincipal | None = None) -> str:
    principal = principal or _principal()
    return f"{principal.tenant_id}:{principal.client_id}:{scope}"


def _az_token(scope: str, *, force_refresh: bool) -> str:
    key = f"az:{scope}"
    with _TOKEN_LOCK:
        cached = None if force_refresh else _TOKEN_CACHE.get(key)
    if cached and cached[1] - _now() > _TOKEN_REFRESH_MARGIN_SECONDS:
        return cached[0]
    try:
        token, expires_on = azure_cli_token(scope)
    except AzureCliSignInError as exc:
        raise _Final(str(exc)) from None  # a sign-in no retry fixes (aidd-polite-http)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, expires_on)
    return token


def _get_token(*, force_refresh: bool = False) -> str:
    scope = _scope()
    if _auth_mode() == "az":
        return _az_token(scope, force_refresh=force_refresh)
    principal = _principal()
    key = _token_cache_key(scope, principal)
    with _TOKEN_LOCK:
        cached = None if force_refresh else _TOKEN_CACHE.get(key)
    if cached and cached[1] - _now() > _TOKEN_REFRESH_MARGIN_SECONDS:
        return cached[0]
    form = {
        "grant_type": "client_credentials",
        "client_id": principal.client_id,
        "client_secret": principal.client_secret,
        "scope": scope,
    }
    try:
        data = _http_json(
            "POST", _token_url(principal), timeout=30,
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except _TRANSPORT_ERRORS as exc:
        raise _classified(exc, _token_url(principal)) from None
    token = _field(data, "access_token", _token_url(principal))
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, _now() + int(data.get("expires_in", 3600)))
    return token


def _rejected(exc: urllib.error.HTTPError) -> _Final | None:
    """The message for a status no retry fixes, in the words the service paths use (`_service_export`)."""
    if exc.code == 401:
        return _Final(
            "Fabric rejected the token (HTTP 401) -- it is for a different tenant than the workspace, expired, "
            "or the tenant does not yet let service principals use Fabric APIs. Check FABRIC_TENANT_ID and "
            "which identity `fab-test auth status` reports"
        ) if _identity() == "the service principal" else _Final(
            "Fabric rejected your az login token (HTTP 401) -- it is for a different tenant than the workspace "
            "or expired. Run `az login --tenant <the workspace's tenant>`"
        )
    if exc.code == 403:
        return _Final(
            f"{_identity()} may not use this Data Agent (HTTP 403); it needs a role in the agent's "
            "workspace and read access to the agent's data sources. Run `fab-test auth status`"
        )
    return _not_retriable(exc)


def _not_retriable(exc: urllib.error.HTTPError) -> _Final | None:
    """A paused capacity names the fix; every other status is classified by ``_classified``."""
    if _json_body(exc).get("errorCode") == "CapacityNotActive":
        return _Final(f"the agent's Fabric capacity is paused (CapacityNotActive): resume the capacity behind the "
                      f"workspace, then run again. {_error_text(exc)}")
    return None


def _json_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        body = json.loads(_http_error_body(exc) or "{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# OSError covers URLError (and HTTPError), timeouts, resets and TLS errors; IncompleteRead and other
# http.client errors, and a TLS error during read(), escape urllib unwrapped
_TRANSPORT_ERRORS = (OSError, http.client.HTTPException)


def _classified(exc: Exception, url: str) -> _Final | _Retry:
    """The failure as ``aidd-polite-http`` classes it, worded for the person who ran the suite."""
    host = urllib.parse.urlsplit(url).hostname or url
    if not isinstance(exc, urllib.error.HTTPError):
        text = _redact(policy.describe_network(host, exc))
        return _Final(text) if policy.network_class(exc) == policy.FINAL else _Retry(text)
    body = _json_body(exc)
    if "message" not in body and body.get("error_description"):  # the token endpoint's spelling
        body = {**body, "message": body["error_description"]}
    elif not body and (raw := _http_error_body(exc).strip()) and raw[0] not in "{[":
        body = {"message": " ".join(raw.split())[:200]}  # plain text is still the service's own words
    delay = policy.retry_after(exc.headers, _now())
    kind = policy.classify(exc.code, body, delay)
    if kind == policy.WAIT and delay is None:
        delay = _BLOCK_SECONDS_WITHOUT_HEADER
    text = _redact(policy.describe_http(host, exc.code, body, until=_now() + delay if delay is not None else None,
                                        reason=str(exc.reason or "")))
    failure = _Final(text) if kind == policy.FINAL else _Retry(text, delay if kind == policy.WAIT else None)
    failure.status = exc.code
    return failure


def _authed_json(method: str, url: str, *, timeout: int, **kwargs: Any) -> dict[str, Any]:
    """Call the agent API with a cached token; a 401 refreshes it once, then is final."""
    token = _get_token()
    for attempt in range(2):
        try:
            return _http_json(method, url, token=token, timeout=timeout, **kwargs)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 0:
                token = _get_token(force_refresh=True)
                continue
            raise _rejected(exc) or _classified(exc, url) from None
        except _TRANSPORT_ERRORS as exc:
            raise _classified(exc, url) from None
    raise AssertionError("unreachable")


class _Runtime:
    def __getattr__(self, name: str) -> Any:
        return globals()[name]


_RUNTIME = _Runtime()


def _validated_base_url(raw_url: str) -> str:
    return provider_run.validated_base_url(_RUNTIME, raw_url)


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """promptfoo's provider contract: ``{"output": text}``, or a redacted ``{"error": message}``."""
    return provider_run.call_api(_RUNTIME, prompt, options, context)
