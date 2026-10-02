"""Shared test helpers. The tests never contact real UN servers."""

from __future__ import annotations

import pytest

from unspeaks.rate_limiter import RateLimiter


class FakeClock:
    """A clock that only moves when something "sleeps", so tests run instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> RateLimiter:
    """The real limits (100 per 5 minutes, 3 s apart) on a fake clock."""
    return RateLimiter(100, 300.0, 3.0, clock=clock, sleep=clock.sleep)


def _make_pdf(pages: list[str]) -> bytes:
    """Build a small, valid PDF with one text page per item (lines split on \\n)."""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in pages:
        ops = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
        for i, line in enumerate(text.split("\n")):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(("" if i == 0 else "T* ") + f"({escaped}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        page_number, content_number = len(objects) + 1, len(objects) + 2
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_number} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(f"{page_number} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def make_pdf():
    return _make_pdf
