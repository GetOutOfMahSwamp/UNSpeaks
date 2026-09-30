"""Tests for paging and citations. A fake client stands in for ODS."""

from __future__ import annotations

from pathlib import Path

import pytest

from unspeaks.documents import MAX_CHARS_PER_CALL, DocumentRequestError, DocumentService
from unspeaks.ods_client import DocumentNotFoundError, FetchedPdf

URL = "https://documents.un.org/doc/undoc/gen/n23/306/65/pdf/n2330665.pdf"


class FakeClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def fetch_pdf(self, symbol: str, language: str = "en") -> FetchedPdf:
        self.calls += 1
        if self.error:
            raise self.error
        return FetchedPdf(symbol, language, Path("fake.pdf"), URL, "2026-09-29T13:31:29+00:00", False)


def service_with(pages: list[str], client: FakeClient | None = None) -> DocumentService:
    return DocumentService(client or FakeClient(), page_loader=lambda path: pages)


TWELVE_PAGES = [f"Text of page {n}" for n in range(1, 13)]


def test_returns_the_first_pages_by_default():
    result = service_with(TWELVE_PAGES).get_pages("A/RES/78/1")
    assert [p.page for p in result.pages] == [1, 2, 3]
    assert result.pages[0].text == "Text of page 1"
    assert result.total_pages == 12
    assert result.next_page == 4


def test_continue_reading_with_next_page():
    result = service_with(TWELVE_PAGES).get_pages("A/RES/78/1", start_page=10, max_pages=5)
    assert [p.page for p in result.pages] == [10, 11, 12]
    assert result.next_page is None  # end of the document


def test_max_pages_is_capped_at_ten():
    result = service_with(TWELVE_PAGES).get_pages("A/RES/78/1", max_pages=50)
    assert len(result.pages) == 10


def test_page_past_the_end_gives_a_clear_error():
    with pytest.raises(DocumentRequestError, match="between 1 and 12"):
        service_with(TWELVE_PAGES).get_pages("A/RES/78/1", start_page=13)


def test_stops_early_when_pages_are_long():
    long_pages = ["x" * 10_000] * 6
    result = service_with(long_pages).get_pages("A/78/PV.5", max_pages=6)
    assert len(result.pages) == 3  # 3 x 10,000 characters fits the budget, a 4th doesn't
    assert result.next_page == 4
    assert "next_page" in result.note


def test_a_single_huge_page_is_cut_off():
    result = service_with(["y" * (MAX_CHARS_PER_CALL + 5000)]).get_pages("A/78/PV.5")
    assert len(result.pages[0].text) <= MAX_CHARS_PER_CALL + 10
    assert "cut off" in result.note


def test_every_answer_carries_a_citation():
    source = service_with(TWELVE_PAGES).get_pages("A/RES/78/1").source
    assert source.url == URL
    assert source.copyright == "© United Nations"
    assert source.citation == (
        f"United Nations, A/RES/78/1, Official Document System, {URL}, accessed 2026-09-29."
    )


def test_errors_from_ods_are_passed_on():
    client = FakeClient(error=DocumentNotFoundError("No document found for 'A/RES/99/999'"))
    with pytest.raises(DocumentNotFoundError):
        service_with(TWELVE_PAGES, client).get_pages("A/RES/99/999")


def test_works_with_a_real_pdf(tmp_path, make_pdf):
    pdf = tmp_path / "A_RES_78_1.pdf"
    pdf.write_bytes(make_pdf(["The General Assembly,", "Adopts the following"]))

    class PdfClient(FakeClient):
        def fetch_pdf(self, symbol, language="en"):
            return FetchedPdf(symbol, language, pdf, URL, "2026-09-29T13:31:29+00:00", False)

    result = DocumentService(PdfClient()).get_pages("A/RES/78/1")
    assert [p.text for p in result.pages] == ["The General Assembly,", "Adopts the following"]
