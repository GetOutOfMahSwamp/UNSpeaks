"""Read the table in the calendar of conferences and meetings from its PDF.

The calendar (e.g. A/AC.172/2026/2) is one long table. Its plain text, as
get_document returns it, runs the columns together ("UNCITRAL General Assembly
resolution") and glues footnote letters to words ("23 Novembers", "Racial
Discriminationc"). So this module reads the PDF itself, character by character,
using where each character is printed and how big it is:

- the column edges come from the ruling line at the top of each table header,
  and each column is named after the header word in it ("Organ", "Dates", ...);
- an entry starts at its number ("292.") in the first column and runs down to
  the next number;
- footnote letters are printed smaller than the table text, so characters in a
  smaller font are left out; so is rotated text (the symbol along the page edge);
- the table ends at a ruling line below its last entry, above the footnotes.

Nothing here knows about dates or meetings: it only turns the table into cells.
`load_calendar_table` caches the result as JSON next to the PDF, so each PDF is
read only once.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pydantic import BaseModel

from unspeaks.meetings.dates import MONTHS

# Bump this when the reading logic changes, so cached results are read again.
PARSER_VERSION = 2

# First word of a header cell -> the name we use for that column.
HEADER_WORDS = {
    "organ": "organ",
    "mandate": "mandate",
    "meeting": "title",
    "dates": "dates",
    "location": "location",
    "membership": "membership",
    "servicing": "servicing",
    "periodicity": "periodicity",
}
SMALL_FONT = 0.8  # characters smaller than this share of the table text are footnote letters
MIN_RULE_WIDTH = 5.0  # a ruling-line segment is a flat path at least this wide...
MAX_RULE_HEIGHT = 3.0  # ...and at most this high (in points)

_SECTION_HEADING = re.compile(r"(?m)^([A-Z])\. (Calendar of conferences and meetings\b.*)$")
_AS_AT = re.compile(r"\(As at (\d{1,2} [A-Z][a-z]+ \d{4})\)")
_ENTRY_NUMBER = re.compile(r"(\d{1,4})\.?")


# --- What this module returns ------------------------------------------------------


class TableEntry(BaseModel):
    section: str  # "A" (United Nations) or "B" (specialized agencies, IAEA, treaty bodies)
    number: int  # the entry number in the calendar, e.g. 292
    page: int  # the PDF page where the entry starts
    cells: dict[str, str]  # column name -> text, e.g. {"organ": "WFP, Executive Board", ...}


class TableSection(BaseModel):
    letter: str
    heading: str  # e.g. "Calendar of conferences and meetings of the United Nations, 2026"
    as_at: date | None  # "(As at 2 February 2026)"


class CalendarTable(BaseModel):
    parser_version: int = PARSER_VERSION
    sections: list[TableSection]
    entries: list[TableEntry]
    warnings: list[str] = []


# --- Reading -----------------------------------------------------------------------


def load_calendar_table(pdf_path: Path) -> CalendarTable:
    """Like read_calendar_table, but caches the result next to the PDF (<name>.calendar.json)."""
    pdf_path = Path(pdf_path)
    cache = pdf_path.with_name(pdf_path.stem + ".calendar.json")
    if cache.exists() and cache.stat().st_mtime >= pdf_path.stat().st_mtime:
        try:
            table = CalendarTable.model_validate_json(cache.read_text(encoding="utf-8"))
        except ValueError:
            table = None  # damaged or from an older version: read the PDF again
        if table is not None and table.parser_version == PARSER_VERSION:
            return table
    table = read_calendar_table(pdf_path)
    tmp = cache.with_name(cache.name + ".tmp")
    tmp.write_text(table.model_dump_json(), encoding="utf-8")
    tmp.replace(cache)
    return table


def read_calendar_table(pdf: bytes | Path) -> CalendarTable:
    """Read every table entry of a calendar PDF (PDF bytes or a path to a PDF file)."""
    document = pdfium.PdfDocument(pdf if isinstance(pdf, bytes) else str(pdf))
    reader = _Reader()
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                reader.read_page(index + 1, _page_chars(page), _page_rules(page))
            finally:
                page.close()
    finally:
        document.close()
    return reader.result()


# --- Internals ---------------------------------------------------------------------


@dataclass
class _Char:
    text: str
    left: float
    bottom: float
    right: float
    top: float
    size: float
    angle: float

    @property
    def x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def y(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def is_space(self) -> bool:
        return self.text.isspace()


@dataclass
class _Rule:
    """A horizontal ruling line, made of segments that end at the column edges."""

    y: float
    segments: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class _Column:
    name: str
    left: float
    right: float


def _page_chars(page: pdfium.PdfPage) -> list[_Char]:
    textpage = page.get_textpage()
    try:
        chars = []
        for i in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(textpage.raw, i)
            if code == 0:
                continue
            left, bottom, right, top = textpage.get_charbox(i)
            chars.append(
                _Char(
                    chr(code), left, bottom, right, top,
                    pdfium_c.FPDFText_GetFontSize(textpage.raw, i),
                    pdfium_c.FPDFText_GetCharAngle(textpage.raw, i),
                )
            )
        return chars
    finally:
        textpage.close()


def _page_rules(page: pdfium.PdfPage) -> list[_Rule]:
    """Horizontal ruling lines on the page, from top to bottom."""
    segments = []
    for obj in page.get_objects():
        if obj.type != pdfium_c.FPDF_PAGEOBJ_PATH:
            continue
        left, bottom, right, top = obj.get_bounds()
        if right - left >= MIN_RULE_WIDTH and top - bottom <= MAX_RULE_HEIGHT:
            segments.append(((bottom + top) / 2, left, right))
    rules: list[_Rule] = []
    for y, left, right in sorted(segments, key=lambda s: (-s[0], s[1])):
        if rules and abs(rules[-1].y - y) <= 1.0:
            rules[-1].segments.append((left, right))
        else:
            rules.append(_Rule(y, [(left, right)]))
    return rules


def _words(chars: list[_Char]) -> list[tuple[str, float]]:
    """Words (split on spaces) with the x position of their middle."""
    words, current = [], []
    for char in chars + [_Char(" ", 0, 0, 0, 0, 0, 0)]:
        if char.is_space:
            if current:
                text = "".join(c.text for c in current)
                words.append((text, (current[0].left + current[-1].right) / 2))
                current = []
        else:
            current.append(char)
    return words


def _clean(text: str) -> str:
    # pdfium marks a hyphen at the end of a line with U+0002 (U+FFFE in its plain text)
    text = text.replace("\x02", "-").replace("￾", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"(?<=\w) -(?=\w)", "-", text)  # "counter\n-terrorism" -> "counter-terrorism"


class _Reader:
    def __init__(self) -> None:
        self.sections: list[TableSection] = []
        self.entries: list[TableEntry] = []
        self.warnings: list[str] = []
        self.section: str | None = None
        self.last_number = 0

    def result(self) -> CalendarTable:
        if not self.entries:
            self.warnings.append("No table entries found: is this a calendar of conferences and meetings?")
        return CalendarTable(sections=self.sections, entries=self.entries, warnings=self.warnings)

    def read_page(self, page_number: int, chars: list[_Char], rules: list[_Rule]) -> None:
        upright = [c for c in chars if abs(c.angle) < 0.01 or c.is_space]
        text = "".join(c.text for c in upright).replace("\r\n", "\n").replace("\r", "\n")
        for match in _SECTION_HEADING.finditer(text):
            self._start_section(match.group(1), match.group(2), text[match.end():])

        header = self._find_header(upright, rules)
        if header is None or self.section is None:
            return
        columns, header_bottom, table_bottom = header

        body = [c for c in upright if not c.is_space and table_bottom < c.y < header_bottom]
        if not body:
            return
        body_size = Counter(round(c.size, 1) for c in body).most_common(1)[0][0]
        number_column = columns[0]

        # Where each entry starts: its number in the first column, higher than the last one.
        # (Each page also has a stray "1." near the top of that column; it is never higher.)
        starts: list[tuple[int, float]] = []
        band = [c for c in upright if c.is_space or table_bottom < c.y < header_bottom]
        for token, top in self._number_tokens(band, number_column, body_size):
            match = _ENTRY_NUMBER.fullmatch(token)
            if match and int(match.group(1)) > self.last_number:
                self.last_number = number = int(match.group(1))
                starts.append((number, top + 2.0))

        # Text above the first entry on a page continues the entry from the previous page.
        bands = [(header_bottom, None)] + [(top, number) for number, top in starts]
        cells: dict[tuple[int | None, str], str] = {}
        current: tuple[int | None, str] | None = None
        for char in upright:
            if char.is_space or char.size < 1.5:  # spaces, including the ones pdfium adds
                if current:
                    cells[current] = cells.get(current, "") + " "
                continue
            if char.size < SMALL_FONT * body_size or not (table_bottom < char.y < header_bottom):
                continue  # a footnote letter, or outside the table
            column = next((col for col in columns if col.left <= char.x < col.right), None)
            if column is None or column is number_column:
                current = None
                continue
            entry = next(number for top, number in reversed(bands) if char.y <= top)
            current = (entry, column.name)
            cells[current] = cells.get(current, "") + char.text

        continued = {name: _clean(value) for (entry, name), value in cells.items() if entry is None}
        if any(continued.values()):
            if self.entries and self.entries[-1].section == self.section:
                previous = self.entries[-1].cells
                for name, value in continued.items():
                    previous[name] = _clean(f"{previous.get(name, '')} {value}")
            else:
                self.warnings.append(f"Page {page_number}: text above the first entry was ignored.")

        for number, _ in starts:
            entry_cells = {name: _clean(value) for (entry, name), value in cells.items()
                           if entry == number and not name.startswith("column ")}
            if "dates" in entry_cells:
                entry_cells["dates"] = re.sub(r"\s*([–-])\s*", r"\1", entry_cells["dates"])
            self.entries.append(TableEntry(section=self.section, number=number,
                                           page=page_number, cells=entry_cells))

    def _start_section(self, letter: str, heading_line: str, rest: str) -> None:
        # The heading can wrap onto the next lines; it ends at "(As at ...)".
        as_at_match = _AS_AT.search(rest[:400])
        heading = heading_line
        if as_at_match:
            heading = _clean(heading_line + " " + rest[: as_at_match.start()])
        as_at = None
        if as_at_match:
            day, month, year = as_at_match.group(1).split()
            try:
                as_at = date(int(year), MONTHS[month], int(day))
            except (KeyError, ValueError):
                self.warnings.append(f"Section {letter}: could not read '{as_at_match.group(0)}'.")
        else:
            self.warnings.append(f"Section {letter}: no '(As at ...)' date found.")
        self.sections.append(TableSection(letter=letter, heading=heading, as_at=as_at))
        self.section = letter
        self.last_number = 0

    @staticmethod
    def _find_header(chars: list[_Char], rules: list[_Rule]):
        """The table header: the band between two ruling lines that holds the word "Organ"."""
        for upper, lower in zip(rules, rules[1:]):
            inside = [c for c in chars if lower.y < c.y < upper.y]
            words = _words(inside)
            if not any(word.lower().startswith("organ") for word, _ in words):
                continue
            edges = sorted(upper.segments)
            columns = []
            for index, (left, right) in enumerate(edges):
                names = [HEADER_WORDS[key] for word, x in words if left <= x < right
                         for key in HEADER_WORDS if word.lower().startswith(key)]
                columns.append(_Column(names[0] if names else f"column {index}", left, right))
            columns[0].name = "number"
            below = [rule.y for rule in rules if rule.y < lower.y - 1.0]
            table_bottom = max(below) if below else 0.0
            return columns, lower.y, table_bottom
        return None

    @staticmethod
    def _number_tokens(chars: list[_Char], column: _Column, body_size: float):
        """Words in the number column, with the top of each word."""
        run: list[_Char] = []
        for char in chars + [_Char(" ", 0, 0, 0, 0, 0, 0)]:
            inside = (not char.is_space and column.left <= char.x < column.right
                      and char.size >= SMALL_FONT * body_size)
            if inside and run and abs(char.bottom - run[-1].bottom) > 2.0:
                yield "".join(c.text for c in run), max(c.top for c in run)
                run = []
            if inside:
                run.append(char)
            elif run:
                yield "".join(c.text for c in run), max(c.top for c in run)
                run = []
