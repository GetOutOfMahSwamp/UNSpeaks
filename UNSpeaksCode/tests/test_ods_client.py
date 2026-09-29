"""Tests for the ODS client. A fake ODS server (httpx.MockTransport) stands in for
the real one, so these tests work offline and never send requests to the UN."""

from __future__ import annotations

import json

import httpx
import pytest

from unspeaks.ods_client import (
    DocumentNotFoundError,
    InvalidRequestError,
    OdsClient,
    OdsUnavailableError,
    RateLimitedError,
    normalize_symbol,
)

FAKE_PDF = b"%PDF-1.4\n% pretend this is a UN resolution\n"
PDF_PATH = "/doc/UNDOC/GEN/N23/306/65/PDF/N2330665.PDF"


class FakeOds:
    """Behaves like ODS: /api/symbol/access redirects to the PDF.

    `access_responses` can hold responses to return from /api/symbol/access
    before the normal redirect (to simulate 429s, errors, etc.).
    """

    def __init__(self, access_responses=None, pdf_response=None):
        self.requests: list[httpx.Request] = []
        self.access_responses = list(access_responses or [])
        self.pdf_response = pdf_response or httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=FAKE_PDF
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/symbol/access":
            if self.access_responses:
                return self.access_responses.pop(0)
            return httpx.Response(302, headers={"location": PDF_PATH}, text="Found. Redirecting")
        if request.url.path == PDF_PATH:
            return self.pdf_response
        return httpx.Response(404)


@pytest.fixture
def make_client(tmp_path, limiter):
    clients = []

    def factory(fake_ods: FakeOds) -> OdsClient:
        client = OdsClient(cache_dir=tmp_path, limiter=limiter, transport=httpx.MockTransport(fake_ods))
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


def test_downloads_pdf_by_following_the_redirect(make_client, tmp_path):
    ods = FakeOds()
    fetched = make_client(ods).fetch_pdf("A/RES/78/1")

    assert fetched.from_cache is False
    assert fetched.path.read_bytes() == FAKE_PDF
    assert fetched.source_url == "https://documents.un.org" + PDF_PATH
    first = ods.requests[0]
    assert first.url.params["s"] == "A/RES/78/1"
    assert first.url.params["l"] == "en"
    assert first.url.params["t"] == "pdf"
    assert len(ods.requests) == 2  # the redirect + the PDF


def test_sends_an_honest_user_agent(make_client):
    ods = FakeOds()
    make_client(ods).fetch_pdf("A/RES/78/1")
    assert all(r.headers["user-agent"].startswith("UNSpeaks/") for r in ods.requests)


def test_second_fetch_comes_from_cache_without_any_request(make_client):
    ods = FakeOds()
    client = make_client(ods)
    client.fetch_pdf("A/RES/78/1")
    again = client.fetch_pdf("A/RES/78/1")
    assert again.from_cache is True
    assert len(ods.requests) == 2  # nothing new was sent


def test_each_redirect_hop_is_rate_limited(make_client, clock):
    make_client(FakeOds()).fetch_pdf("A/RES/78/1")
    assert clock.sleeps == [3.0]  # the PDF request waited 3 s after the redirect request


def test_cache_files_have_safe_names_and_metadata(make_client, tmp_path):
    fetched = make_client(FakeOds()).fetch_pdf("S/RES/2720 (2023)")
    assert fetched.path == tmp_path / "en" / "S_RES_2720(2023).pdf"
    meta = json.loads((tmp_path / "en" / "S_RES_2720(2023).json").read_text())
    assert meta["symbol"] == "S/RES/2720(2023)"
    assert meta["source_url"].startswith("https://documents.un.org/")


def test_honours_retry_after_on_429(make_client, clock):
    ods = FakeOds(access_responses=[httpx.Response(429, headers={"retry-after": "10"})])
    fetched = make_client(ods).fetch_pdf("A/RES/78/1")
    assert fetched.path.exists()
    assert clock.sleeps[0] == 10.0  # waited as long as the server asked before retrying


def test_gives_up_when_asked_to_wait_too_long(make_client):
    ods = FakeOds(access_responses=[httpx.Response(429, headers={"retry-after": "3600"})])
    with pytest.raises(RateLimitedError) as info:
        make_client(ods).fetch_pdf("A/RES/78/1")
    assert info.value.retry_after == 3600
    assert len(ods.requests) == 1  # no retry


def test_gives_up_after_repeated_429s(make_client):
    ods = FakeOds(access_responses=[httpx.Response(429, headers={"retry-after": "1"})] * 5)
    with pytest.raises(RateLimitedError):
        make_client(ods).fetch_pdf("A/RES/78/1")
    assert len(ods.requests) == 3  # MAX_ATTEMPTS


def test_retries_after_a_server_error(make_client):
    ods = FakeOds(access_responses=[httpx.Response(503)])
    assert make_client(ods).fetch_pdf("A/RES/78/1").path.exists()


def test_unknown_symbol_gives_a_clear_error(make_client, tmp_path):
    ods = FakeOds(access_responses=[httpx.Response(404)])
    with pytest.raises(DocumentNotFoundError, match="A/RES/99/999"):
        make_client(ods).fetch_pdf("A/RES/99/999")
    assert not any(tmp_path.rglob("*.pdf"))  # nothing cached


def test_html_instead_of_pdf_is_not_cached(make_client, tmp_path):
    html = httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Not found</html>")
    with pytest.raises(DocumentNotFoundError, match="did not return a PDF"):
        make_client(FakeOds(pdf_response=html)).fetch_pdf("A/RES/78/1")
    assert not any(tmp_path.rglob("*.pdf"))


def test_bot_protection_challenge_is_not_bypassed(make_client):
    challenge = httpx.Response(202, headers={"x-amzn-waf-action": "challenge"})
    ods = FakeOds(access_responses=[challenge])
    with pytest.raises(OdsUnavailableError, match="bot-protection"):
        make_client(ods).fetch_pdf("A/RES/78/1")
    assert len(ods.requests) == 1


def test_refuses_redirects_to_non_un_sites(make_client):
    ods = FakeOds(access_responses=[httpx.Response(302, headers={"location": "https://example.com/x.pdf"})])
    with pytest.raises(OdsUnavailableError, match="unexpected site"):
        make_client(ods).fetch_pdf("A/RES/78/1")


@pytest.mark.parametrize(
    "bad", ["", "   ", "A/RES/78/1; rm -rf /", "../../etc/passwd", "A//RES", "x" * 200, "A/RES/78/1?x=1"]
)
def test_rejects_invalid_symbols(bad):
    with pytest.raises(InvalidRequestError):
        normalize_symbol(bad)


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("A/RES/78/1", "A/RES/78/1"),
        (" S/RES/2720 (2023) ", "S/RES/2720(2023)"),
        ("A/C.3/78/L.12/Rev.1", "A/C.3/78/L.12/Rev.1"),
        ("A/78/PV.5", "A/78/PV.5"),
    ],
)
def test_accepts_real_symbol_formats(raw, clean):
    assert normalize_symbol(raw) == clean


def test_rejects_unknown_language(make_client):
    with pytest.raises(InvalidRequestError, match="language"):
        make_client(FakeOds()).fetch_pdf("A/RES/78/1", language="nl")
