"""A tiny calendar of conferences and meetings, as a PDF, for the meetings tests.

The entries below are copied from the 2026 calendar (A/AC.172/2026/2) and laid out the
way that PDF is: landscape pages, a ruled table header, entry numbers in the first
column, and footnote letters in a smaller, raised font, written here as "^s". It also
has the awkward bits of the real PDF: text printed sideways, a stray "1." near the top
of the number column, an entry that runs on to the next page, and footnotes below the
table. Cells are lists of lines, as they are printed.
"""

from __future__ import annotations

import re
from pathlib import Path

from unspeaks.ods_client import FetchedPdf

SYMBOL = "A/AC.172/2026/2"
PDF_URL = "https://documents.un.org/doc/undoc/gen/n26/019/67/pdf/n2601967.pdf"

# (header text, left edge, right edge), as in the real PDF
COLUMNS_A = [
    ("", 57.6, 80.2), ("Organ", 80.7, 191.8), ("Mandate", 192.3, 303.7),
    ("Meeting title/session", 304.2, 381.7), ("Dates (2026)", 382.2, 453.7),
    ("Location", 454.2, 509.9), ("Membership", 510.4, 554.6), ("Servicing^a", 555.0, 635.2),
    ("Periodicity", 635.7, 720.2),
]
COLUMNS_B = [
    ("", 56.9, 75.6), ("Organ", 76.3, 394.9), ("Meeting title/session number", 395.6, 493.6),
    ("Dates (2026)", 494.3, 604.0), ("Location", 604.7, 720.2),
]

COVER = [
    "United Nations A/AC.172/2026/2",
    "General Assembly Distr.: General 2 February 2026",
    "Calendar of conferences and meetings of the United Nations",
    "for 2026",
]

HEADING_A = ["A. Calendar of conferences and meetings of the United Nations, 2026",
             "(As at 2 February 2026)"]
PAGE_A1 = [
    ("292.", ["Conference on the", "establishment of a Middle", "East zone free of nuclear",
              "weapons and other weapons", "of mass destruction"],
     ["General Assembly decision", "73/546"], ["Seventh session"], ["16–20 November^s"],
     ["New York"], [], ["I", "(ACEFRS)"], ["One session per year"]),
    ("296.", ["WFP, Executive Board^b"],
     ["Economic and Social Council", "decision 1995/227 and", "General Assembly resolution", "50/8"],
     ["Second regular", "session"], ["16–20 November"], ["Rome"], ["36 G"], ["I", "(ACEFRS)"],
     ["Three sessions per", "year"]),
    ("298.", ["Committee on the Exercise", "of the Inalienable Rights of", "the Palestinian People"],
     ["General Assembly", "resolutions 32/40 B and", "33/28"],
     ["Special meeting in", "observance of the", "International Day", "of Solidarity with",
      "the Palestinian", "People"],
     ["23 November^s", "(to be confirmed)"], ["New York"], ["26 G"], ["I", "(ACEFRS)"],
     ["One session per year"]),
    ("300.", ["Human Rights Council,", "Forum on Business and", "Human Rights"],
     ["Human Rights Council", "resolutions 17/4 and 26/22"], ["Fifteenth session"],
     ["23–25 November^q"], ["Geneva"], ["193 G"], ["I", "(ACEFRS)"], ["One session per year"]),
    ("302.", ["Committee on the", "Elimination of Racial", "Discrimination^c"],
     ["General Assembly", "resolutions 2106 A (XX) and", "68/268"], ["119th session"],
     ["23 November–", "11 December^q"], ["Geneva"], ["18 E"], ["I"], ["Three sessions"]),
]
# Page 2 starts with the rest of entry 302, which ran on from page 1.
CONTINUED_A2 = [[], [], [], [], [], [], [], ["per year"]]
PAGE_A2 = [
    ("314.", ["Investments Committee"], ["General Assembly resolution", "155 (II)"],
     ["292nd meeting"], ["November"], ["New York"], ["9 E"], ["–"], []),
    ("336.", ["Security Council"], ["Charter"], [], ["As required"], ["New York"], ["15 G"],
     ["I", "(ACEFRS)"], ["As required"]),
    ("337.", ["Security Council Ad Hoc", "Working Group on Conflict", "Prevention and Resolution in",
              "Africa"], ["S/2002/207"], [], ["As required"], ["New York"], ["15 G"], ["I"],
     ["As required"]),
    ("338.", ["Security Council Committee", "established pursuant to", "resolution 1373 (2001)",
              "concerning counter", "-terrorism"],
     ["Security Council resolution", "1373 (2001)"], [], ["As required"], ["New York"], ["15 G"],
     ["I"], ["As required"]),
    ("385.", ["UNU, Council"], ["General Assembly", "resolutions 3081 (XXVIII)", "and 68/236"], [],
     ["To be determined", "(one week)"], ["Tokyo"], ["12 E"], ["I", "(EF)"], ["One session per year"]),
]
FOOTNOTES_A = [
    "^a The languages in which interpretation will be provided are indicated.",
    "^s Subject to the approval of the General Assembly.",
]

HEADING_B = [
    "B. Calendar of conferences and meetings of the principal organs of the specialized agencies, the",
    "International Atomic Energy Agency and treaty bodies established under the auspices of the",
    "United Nations, 2026",
    "(As at 2 February 2026)",
]
PAGE_B = [
    ("68.", ["IAEA, Board of Governors"], [], ["18 November"], ["Vienna"]),
    ("70.", ["Conference of the States Parties to the Convention on the Prohibition of",
             "the Development, Production, Stockpiling and Use of Chemical Weapons",
             "and on Their Destruction"],
     ["Thirty-first session"], ["23–27 November"], ["The Hague, Netherlands", "(Kingdom of the)"]),
    ("77.", ["UN Tourism, Executive Council"], ["127th session"], ["Second semester"],
     ["To be determined"]),
]


def calendar_pdf() -> bytes:
    """The whole tiny calendar: a cover page, two pages of part A and one of part B."""
    cover = _Page()
    for index, line in enumerate(COVER):
        cover.text(72, 560 - 20 * index, line, size=12)
    pages = [
        cover,
        _table_page(COLUMNS_A, PAGE_A1, heading=HEADING_A),
        _table_page(COLUMNS_A, PAGE_A2, continued=CONTINUED_A2, stray_one=True,
                    footnotes=FOOTNOTES_A),
        _table_page(COLUMNS_B, PAGE_B, heading=HEADING_B, footnotes=[]),
    ]
    return _pdf(pages)


def write_calendar_pdf(folder: Path) -> Path:
    path = Path(folder) / "A_AC.172_2026_2.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(calendar_pdf())
    return path


def calendar_fetcher(pdf_path: Path):
    """Stands in for DocumentService.fetch_pdf; records what it was asked for."""

    def fetch(symbol: str, language: str = "en") -> FetchedPdf:
        fetch.calls.append((symbol, language))
        return FetchedPdf(symbol, language, Path(pdf_path), PDF_URL, "2026-11-05T09:47:00+00:00", True)

    fetch.calls = []
    return fetch


# --- Laying out pages ----------------------------------------------------------------

BODY_SIZE, NOTE_SIZE, HEADER_SIZE, LINE = 8.4, 5.5, 7.0, 10.5


def _table_page(columns, rows, *, heading=(), continued=None, stray_one=False, footnotes=None):
    page = _Page()
    for index, line in enumerate(heading):
        page.text(57.6, 595 - 12 * index, line, size=10.1)
    page.rule(columns, 552.0, 0.5)
    for name, left, _ in columns:
        page.text(left + 1.5, 535.0, name, size=HEADER_SIZE)
    page.rule(columns, 526.3, 1.4)
    # The document symbol, printed sideways inside the table area.
    page.rotated(715.0, 300.0, SYMBOL)

    y = 512.0
    if continued:
        y = page.cells(columns, y, continued)
    if stray_one:
        page.text(columns[0][1] + 1.0, y + 3.6, "1.")
    for number, *cells in rows:
        page.text(columns[0][1] + 0.4, y, number)
        y = page.cells(columns, y, cells)
    if footnotes is not None:  # the table ends here, with a rule
        page.rule(columns, y + 4.0, 1.4)
        for index, note in enumerate(footnotes):
            page.text(65.4, y - 12.0 - LINE * index, note)
    return page


class _Page:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def text(self, x: float, y: float, line: str, size: float = BODY_SIZE) -> None:
        """A line of text; '^q' prints footnote letter q smaller and raised."""
        ops = [f"BT /F1 {size} Tf {x:.1f} {y:.1f} Td"]
        for index, part in enumerate(re.split(r"\^([a-z](?:,[a-z])*)", line)):
            if index % 2:
                ops.append(f"/F1 {NOTE_SIZE} Tf 3 Ts {_string(part)} Tj /F1 {size} Tf 0 Ts")
            elif part:
                ops.append(f"{_string(part)} Tj")
        ops.append("ET")
        self.ops.append(" ".join(ops))

    def rotated(self, x: float, y: float, line: str) -> None:
        self.ops.append(f"BT /F1 {BODY_SIZE} Tf 0 1 -1 0 {x:.1f} {y:.1f} Tm {_string(line)} Tj ET")

    def rule(self, columns, y: float, thickness: float) -> None:
        for _, left, right in columns:
            self.ops.append(f"{left:.1f} {y:.1f} {right - left:.1f} {thickness:.1f} re f")

    def cells(self, columns, y: float, cells) -> float:
        """Print one row of cells (lists of lines) from y down; return where the next row starts."""
        for (_, left, _), lines in zip(columns[1:], cells):
            for index, line in enumerate(lines):
                self.text(left + 1.5, y - LINE * index, line)
        return y - LINE * max([len(lines) for lines in cells] + [1]) - 6.0


def _string(text: str) -> str:
    raw = text.encode("cp1252")
    return "(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").decode("latin-1") + ")"


def _pdf(pages: list[_Page]) -> bytes:
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for page in pages:
        stream = "\n".join(page.ops).encode("latin-1")
        page_number, content_number = len(objects) + 1, len(objects) + 2
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] "
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
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)
