"""The shared polite-HTTP rules (Polite HTTP epic, decision 7): classes, Retry-After, backoff, the sentence."""

from __future__ import annotations

import email.message
import email.utils
import socket
import ssl
import urllib.error

import pytest

from fab_test.scripts import _http_policy as policy

pytestmark = pytest.mark.fab_test

NOW = 1_795_000_000.0  # a fixed epoch second


def _headers(**values: str) -> email.message.Message:
    headers = email.message.Message()
    for key, value in values.items():
        headers[key.replace("_", "-")] = value
    return headers


# -- Retry-After -----------------------------------------------------------------------


@pytest.mark.parametrize(("headers", "expected"), [
    (_headers(Retry_After="16"), 16.0),
    (_headers(retry_after_ms="1500"), 1.5),
    (_headers(Retry_After="Wed, 21 Oct 2026 07:28:30 GMT"), 0.0),  # a date already past: no wait left
    (_headers(Retry_After="soon"), None),
    (_headers(), None),
    (None, None),
])
def test_retry_after_reads_seconds_milliseconds_and_dates(headers, expected):
    assert policy.retry_after(headers, NOW) == expected


def test_retry_after_reads_a_future_http_date_as_seconds_from_now():
    future = email.utils.formatdate(NOW + 90, usegmt=True)

    assert policy.retry_after(_headers(Retry_After=future), NOW) == pytest.approx(90, abs=1)


# -- classification --------------------------------------------------------------------


@pytest.mark.parametrize(("status", "body", "delay", "expected"), [
    (400, {}, None, policy.FINAL),
    (404, {}, None, policy.FINAL),
    (409, {}, None, policy.FINAL),
    (422, {}, None, policy.FINAL),
    (429, {}, 16.0, policy.WAIT),
    (503, {}, 5.0, policy.WAIT),
    (429, {"errorCode": "RequestBlocked"}, None, policy.WAIT),
    (429, {}, None, policy.RETRYABLE),
    (429, {"errorCode": "CapacityLimitExceeded"}, None, policy.RETRYABLE),
    (500, {}, None, policy.RETRYABLE),
    (502, {}, None, policy.RETRYABLE),
    (504, {}, None, policy.RETRYABLE),
    (408, {}, None, policy.RETRYABLE),
    (500, {"isRetriable": False}, None, policy.FINAL),
    (429, {"isRetriable": False}, 16.0, policy.FINAL),
    (409, {"isRetriable": True}, None, policy.RETRYABLE),
    (418, {}, None, policy.FINAL),
    (500, {}, 7.0, policy.WAIT),          # Retry-After is a floor on every retryable failure
    (408, {}, 3.0, policy.WAIT),
    (409, {"isRetriable": True}, 3.0, policy.WAIT),
    (404, {}, 5.0, policy.FINAL),         # ...but never makes a final failure retryable
    (599, {}, None, policy.RETRYABLE),
])
def test_every_status_has_one_class(status, body, delay, expected):
    assert policy.classify(status, body, delay) == expected


@pytest.mark.parametrize(("reason", "expected"), [
    (socket.gaierror(11001, "getaddrinfo failed"), policy.FINAL),
    (ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate in chain"), policy.FINAL),
    (ConnectionRefusedError(10061, "refused"), policy.RETRYABLE),
    (ConnectionResetError(10054, "reset"), policy.RETRYABLE),
    (TimeoutError("timed out"), policy.RETRYABLE),
    (ssl.SSLEOFError(8, "EOF occurred in violation of protocol"), policy.RETRYABLE),  # a cut connection
])
def test_network_failures_are_final_for_names_and_certificates_only(reason, expected):
    assert policy.network_class(urllib.error.URLError(reason)) == expected


def test_a_bare_read_timeout_is_retryable():
    assert policy.network_class(TimeoutError("The read operation timed out")) == policy.RETRYABLE


# -- backoff ---------------------------------------------------------------------------


def test_backoff_doubles_from_the_base_adds_jitter_and_is_capped():
    assert policy.backoff(0, 2.0, jitter=lambda: 0.0) == 2.0
    assert policy.backoff(2, 2.0, jitter=lambda: 0.0) == 8.0
    assert policy.backoff(2, 2.0, jitter=lambda: 1.0) == pytest.approx(9.6)
    assert policy.backoff(10, 2.0, jitter=lambda: 0.0) == policy.MAX_BACKOFF_SECONDS


def test_backoff_with_a_zero_base_never_waits():
    assert policy.backoff(3, 0.0) == 0.0


# -- the caller's sentence --------------------------------------------------------------


def test_request_blocked_names_the_identity_quota_and_the_end_time():
    text = policy.describe_http("api.fabric.microsoft.com", 429, {
        "errorCode": "RequestBlocked",
        "message": "Request is blocked by the upstream service until: 11/22/2026 4:38:24 PM (UTC)",
    }, until=NOW + 120)

    assert "RequestBlocked" in text
    assert "until " + policy.utc(NOW + 120) in text
    assert "service principal" in text and "Wait and rerun" in text
    assert "{" not in text and "429" not in text


def test_capacity_limit_names_the_capacity_and_where_to_look():
    text = policy.describe_http("api.fabric.microsoft.com", 429, {"errorCode": "CapacityLimitExceeded",
                                                                  "message": "Try again later."})

    assert "CapacityLimitExceeded" in text and "Capacity Metrics" in text and "429" not in text


@pytest.mark.parametrize(("status", "remedy"), [
    (400, "request"),
    (404, "exists"),
    (409, "busy"),
    (500, "rerun later"),
])
def test_other_statuses_are_one_sentence_with_the_service_words_and_a_remedy(status, remedy):
    text = policy.describe_http("api.fabric.microsoft.com", status, {"errorCode": "SomeCode",
                                                                     "message": "Something went wrong."})

    assert text.startswith(f"api.fabric.microsoft.com answered HTTP {status} SomeCode: Something went wrong.")
    assert remedy in text.lower() and "{" not in text and ".." not in text


def test_a_status_with_no_body_still_reads_as_a_sentence():
    assert policy.describe_http("h.example", 502, {}, reason="Bad Gateway").startswith(
        "h.example answered HTTP 502: Bad Gateway.")


def test_network_sentences_name_the_host_and_the_fix():
    dns = policy.describe_network("api.fabric.microsoft.com", urllib.error.URLError(socket.gaierror(11001, "x")))
    tls = policy.describe_network("api.fabric.microsoft.com", urllib.error.URLError(
        ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate in chain")))
    reset = policy.describe_network("api.fabric.microsoft.com", urllib.error.URLError(ConnectionResetError(1, "x")))

    assert "cannot resolve api.fabric.microsoft.com" in dns and "proxy" in dns
    assert "api.fabric.microsoft.com" in tls and "SSL_CERT_FILE" in tls and "self-signed" in tls
    assert "api.fabric.microsoft.com" in reset and "rerun" in reset
    assert all("<urlopen error" not in text for text in (dns, tls, reset))


def test_utc_is_a_clock_time_with_its_zone():
    assert policy.utc(NOW) == "11:06:40 UTC"
