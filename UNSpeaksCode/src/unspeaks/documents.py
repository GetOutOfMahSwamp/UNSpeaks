"""Read UN documents page by page, always with a source citation.

This is the logic behind the `get_document` MCP tool. It keeps answers small:
the AI asks for a few pages at a time and continues with `next_page`.
"""

from __future__ import annotations

import threading
from typing import Callable

from pydantic import BaseModel, Field

from unspeaks.ods_client import OdsClient
from unspeaks.pdf_text import load_pages

DEFAULT_PAGES = 3
MAX_PAGES_PER_CALL = 10
MAX_CHARS_PER_CALL = 30_000  # keeps one answer to roughly 7-10 pages of UN text


class DocumentRequestError(Exception):
    """The request can't be answered, e.g. the page number is past the end."""


class Page(BaseModel):
    page: int = Field(description="Page number, as in the PDF")
    text: str


class Source(BaseModel):
    symbol: str
    language: str
    url: str = Field(description="Where the PDF was downloaded from")
    downloaded_at: str = Field(description="When UNSpeaks downloaded it (UTC)")
    copyright: str = "© United Nations"
    citation: str = Field(description="Ready-made citation to include when using this text")


class DocumentPages(BaseModel):
    symbol: str
    language: str
    total_pages: int
    pages: list[Page]
    next_page: int | None = Field(
        description="First page not returned yet; pass it as start_page to read on. "
        "null when the end of the document is reached."
    )
    note: str | None = None
    source: Source


class DocumentService:
    def __init__(
        self,
        client: OdsClient | None = None,
        page_loader: Callable = load_pages,
    ) -> None:
        self._client = client
        self._page_loader = page_loader
        # One document at a time, as agreed with the Library. This also stops two
        # parallel calls from downloading the same document twice.
        self._lock = threading.Lock()

    @property
    def client(self) -> OdsClient:
        if self._client is None:
            self._client = OdsClient()
        return self._client

    def get_pages(
        self,
        symbol: str,
        language: str = "en",
        start_page: int = 1,
        max_pages: int = DEFAULT_PAGES,
    ) -> DocumentPages:
        with self._lock:
            fetched = self.client.fetch_pdf(symbol, language)
            all_pages: list[str] = self._page_loader(fetched.path)

        total = len(all_pages)
        if total == 0:
            raise DocumentRequestError(f"{fetched.symbol} has no pages with text.")
        if start_page < 1 or start_page > total:
            raise DocumentRequestError(
                f"{fetched.symbol} has {total} pages, so start_page must be between 1 and {total}."
            )
        max_pages = max(1, min(max_pages, MAX_PAGES_PER_CALL))

        pages: list[Page] = []
        used = 0
        note = None
        for number in range(start_page, min(total, start_page + max_pages - 1) + 1):
            text = all_pages[number - 1]
            if pages and used + len(text) > MAX_CHARS_PER_CALL:
                note = "Stopped early to keep the answer short; continue with next_page."
                break
            if not pages and len(text) > MAX_CHARS_PER_CALL:
                text = text[:MAX_CHARS_PER_CALL] + " [...]"
                note = f"Page {number} was cut off because it is very long."
            pages.append(Page(page=number, text=text))
            used += len(text)

        last = pages[-1].page
        next_page = last + 1 if last < total else None
        date = fetched.fetched_at[:10]
        citation = (
            f"United Nations, {fetched.symbol}, Official Document System, "
            f"{fetched.source_url}, accessed {date}."
        )
        return DocumentPages(
            symbol=fetched.symbol,
            language=fetched.language,
            total_pages=total,
            pages=pages,
            next_page=next_page,
            note=note,
            source=Source(
                symbol=fetched.symbol,
                language=fetched.language,
                url=fetched.source_url,
                downloaded_at=fetched.fetched_at,
                citation=citation,
            ),
        )
