"""How fab-test treats a service that says no (Polite HTTP epic, decision 7; skill ``aidd-polite-http``).

Pure rules every HTTP client shares: which class a failure is in, how long the server asked us to
wait, how long to back off, and the one sentence the caller gets. Clients keep their own transport
and loop; they ask this module what to do.
"""

from __future__ import annotations

import email.utils
import random
import socket
import ssl
import time
import urllib.error
from collections.abc import Callable
from typing import Any

FINAL = "final"            # retrying can't help: report it now
WAIT = "wait"              # the server named a wait: honor it as a floor
RETRYABLE = "retryable"    # transient: back off and try again within the budget

MAX_BACKOFF_SECONDS = 30.0
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_STATUS_REMEDIES = {
    400: "Check the request: the service refused it as written.",
    403: "Grant this identity access to the item.",
    404: "Check that the item exists and this identity can see it.",
    409: "The item is busy or changed; rerun when it is free.",
    413: "The request is too large for the service.",
}


def utc(epoch: float) -> str:
    """A clock time a person can act on: ``16:38:24 UTC``."""
    return time.strftime("%H:%M:%S UTC", time.gmtime(epoch))


def retry_after(headers: Any, now: float) -> float | None:
    """Seconds the server asked for (``retry-after-ms``, or ``Retry-After`` in seconds or as a date); None if none."""
    if headers is None:
        return None
    millis = headers.get("retry-after-ms")
    if millis is not None:
        try:
            return max(0.0, float(millis) / 1000)
        except ValueError:
            pass
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - now)


def classify(status: int, body: dict[str, Any], delay: float | None) -> str:
    """FINAL, WAIT or RETRYABLE for an HTTP error; the body's own ``isRetriable`` overrides the status.

    A server's Retry-After makes any retryable failure a WAIT (the floor), but never makes a final one retryable.
    """
    if body.get("isRetriable") is False:
        return FINAL
    if body.get("errorCode") == "RequestBlocked":
        return WAIT
    if status in _RETRYABLE_STATUSES or body.get("isRetriable") is True or status >= 500:
        return WAIT if delay is not None else RETRYABLE
    return FINAL


def _reason(exc: BaseException) -> BaseException:
    return exc.reason if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException) else exc


def network_class(exc: BaseException) -> str:
    """A name or a certificate can't be fixed by asking again; a refused, reset, cut or timed-out connection can."""
    reason = _reason(exc)
    return FINAL if isinstance(reason, (socket.gaierror, ssl.SSLCertVerificationError)) else RETRYABLE


def backoff(attempt: int, base: float, jitter: Callable[[], float] = random.random) -> float:
    """Exponential from ``base``, up to 20% jitter, capped; a zero base never waits."""
    if base <= 0:
        return 0.0
    return min(base * 2 ** attempt * (1 + jitter() / 5), MAX_BACKOFF_SECONDS)


def _sentence(text: str) -> str:
    text = " ".join(str(text).split()).rstrip(".")
    return f"{text}." if text else ""


def describe_http(host: str, status: int, body: dict[str, Any], *, until: float | None = None,
                  reason: str = "") -> str:
    """One sentence for the caller: what the service said, and what to do. Never the JSON body."""
    code = str(body.get("errorCode") or "")
    if code == "RequestBlocked":
        when = f" until {utc(until)}" if until is not None else ""
        return (f"Fabric is rate-limiting this identity (RequestBlocked){when}. Every run or tool using the same "
                "service principal shares its quota. Wait and rerun.")
    if code == "CapacityLimitExceeded":
        return ("The Fabric capacity is overloaded (CapacityLimitExceeded). Rerun later, and check its load in "
                "the Fabric Capacity Metrics app.")
    said = _sentence(body.get("message") or reason or "no detail")
    remedy = _STATUS_REMEDIES.get(status) or ("The service failed; rerun later." if status >= 500 else "")
    return " ".join(part for part in (f"{host} answered HTTP {status}{' ' + code if code else ''}: {said}",
                                      remedy) if part)


def describe_network(host: str, exc: BaseException) -> str:
    """One sentence for a failure below HTTP, naming the host and the fix."""
    reason = _reason(exc)
    if isinstance(reason, socket.gaierror):
        return f"cannot resolve {host}: check the network connection, the host name, or the proxy."
    if isinstance(reason, ssl.SSLCertVerificationError):
        detail = _sentence(getattr(reason, "verify_message", "") or getattr(reason, "reason", "") or reason)
        return (f"{host}'s certificate is not trusted ({detail.rstrip('.')}). Behind a TLS-inspecting proxy, set "
                "SSL_CERT_FILE to the proxy's CA bundle.")
    detail = _sentence(getattr(reason, "strerror", None) or reason).rstrip(".") or type(reason).__name__
    return f"{host} did not answer ({detail}); rerun later."
