"""Turn a PDF into text, one string per page, so page numbers are kept.

(OpenTK squashed whole documents into a single line, which broke its paging.
Here every page stays separate and line breaks are kept.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pypdfium2 as pdfium


def extract_pages(pdf: bytes | Path) -> list[str]:
    """Return the text of each page of `pdf` (PDF bytes or a path to a PDF file)."""
    document = pdfium.PdfDocument(pdf if isinstance(pdf, bytes) else str(pdf))
    try:
        pages: list[str] = []
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                pages.append(_clean(textpage.get_text_range()))
            finally:
                textpage.close()
                page.close()
        return pages
    finally:
        document.close()


def load_pages(pdf_path: Path) -> list[str]:
    """Like extract_pages, but caches the result next to the PDF (<name>.pages.json)."""
    pdf_path = Path(pdf_path)
    cache = pdf_path.with_name(pdf_path.stem + ".pages.json")
    if cache.exists() and cache.stat().st_mtime >= pdf_path.stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))
    pages = extract_pages(pdf_path)
    tmp = cache.with_name(cache.name + ".tmp")
    tmp.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache)
    return pages


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)  # at most one empty line in a row
    return text.strip()
