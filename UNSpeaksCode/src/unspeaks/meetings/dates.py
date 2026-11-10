"""Turn the "Dates" column of the calendar into real dates.

The calendar writes dates the way people do: "16–20 November", "23 November–
11 December", "16 and 17 November", "26–30 January, and 4–6 and 20 February",
"February (one meeting)", "As required", "To be determined (three days)",
"First semester". `parse_dates` turns such text into one or more periods and says
how precise they are. The year is not in the text: it is the year of the calendar.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

# English month names, written out so they don't depend on the computer's language settings.
MONTHS = {
    name: number
    for number, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"],
        start=1,
    )
}

Kind = Literal["dated", "as_required", "to_be_determined", "unparsed"]
Precision = Literal["day", "month", "half-year"]


@dataclass(frozen=True)
class CalendarDates:
    text: str  # as printed, tidied up
    kind: Kind
    periods: tuple[tuple[date, date], ...] = ()  # first and last day of each part
    precision: Precision | None = None  # "month": only the month is known, e.g. "November"
    to_be_confirmed: bool = False
    note: str | None = None  # remarks such as "one meeting" or "three days"

    @property
    def start(self) -> date | None:
        return min(first for first, _ in self.periods) if self.periods else None

    @property
    def end(self) -> date | None:
        return max(last for _, last in self.periods) if self.periods else None

    def overlaps(self, first: date, last: date) -> bool:
        """True if any part falls (partly) between first and last, both included."""
        return any(start <= last and end >= first for start, end in self.periods)


_MONTH = "|".join(MONTHS)
# A footnote letter glued to a month: "23 Novembers" (footnote s), "17 Aprile,f,g".
_FOOTNOTE_AFTER_MONTH = re.compile(rf"\b({_MONTH})[a-z]+(?:,[a-z])*\b")
_REMARK = re.compile(r"\s*\(([^)]*)\)")
_TOKEN = re.compile(rf"\s*(\d{{1,2}}|{_MONTH}|[–-]|,|and\b)")
_RECURRING = re.compile(rf"^(\d{{1,2}}) ({_MONTH}) and once every (week|fortnight) thereafter$")
_STEPS = {"week": 7, "fortnight": 14}
_SEMESTERS = {"first semester": ((1, 1), (6, 30)), "second semester": ((7, 1), (12, 31))}
_ONE_DAY_OUT_OF = re.compile(r"(?i)^one day out of ")


def clean_dates_text(text: str) -> str:
    """One space between words, no footnote letters after month names, no spaces around dashes."""
    text = re.sub(r"\s+", " ", text or "").strip()
    text = _FOOTNOTE_AFTER_MONTH.sub(r"\1", text)
    return re.sub(r"\s*([–-])\s*", r"\1", text)


def parse_dates(text: str, year: int) -> CalendarDates:
    """Read the dates of one calendar entry, e.g. parse_dates("16–20 November", 2026)."""
    cleaned = clean_dates_text(text)
    remarks = [remark.strip() for remark in _REMARK.findall(cleaned)]
    to_be_confirmed = any("to be confirmed" in remark.lower() for remark in remarks)
    notes = [remark for remark in remarks if remark.lower() != "to be confirmed"]
    core = _REMARK.sub("", cleaned).strip()
    lowered = core.lower()

    def result(kind: Kind, periods=(), precision=None, extra_note=None) -> CalendarDates:
        note = "; ".join(([extra_note] if extra_note else []) + notes) or None
        return CalendarDates(cleaned, kind, tuple(periods), precision, to_be_confirmed, note)

    if lowered.startswith("as required"):
        return result("as_required")
    if lowered.startswith("to be determined"):
        return result("to_be_determined")
    if lowered in _SEMESTERS:
        (first_month, first_day), (last_month, last_day) = _SEMESTERS[lowered]
        return result("dated", [(date(year, first_month, first_day), date(year, last_month, last_day))],
                      "half-year")

    recurring = _RECURRING.match(core)
    if recurring:  # "9 January and once every fortnight thereafter"
        day = date(year, MONTHS[recurring.group(2)], int(recurring.group(1)))
        step = timedelta(days=_STEPS[recurring.group(3)])
        days = []
        while day.year == year:
            days.append((day, day))
            day += step
        return result("dated", days, "day")

    extra_note = None
    one_day = _ONE_DAY_OUT_OF.match(core)
    if one_day:  # "One day out of 2–6 November (exact date to be confirmed)"
        core, extra_note = core[one_day.end():], "one day in this period"

    parsed = _parse_periods(core, year)
    if parsed is None:
        return result("unparsed")
    periods, precision = parsed
    return result("dated", periods, precision, extra_note)


def _parse_periods(text: str, year: int):
    """'26–30 January, and 4–6 and 20 February' -> three periods. None if not understood."""
    tokens, position = [], 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            return None
        tokens.append(match.group(1))
        position = match.end()

    # Parts are separated by "," and "and"; each part is "day [month]" or "month",
    # optionally followed by a dash and a second one.
    parts: list[list[list[int | None]]] = []  # part -> points -> [day, month]
    current: list[str] = []
    for token in tokens + [","]:
        if token not in (",", "and"):
            current.append(token)
            continue
        if not current:
            continue
        points, words = [], []
        for word in current + ["–"]:
            if word not in "–-":
                words.append(word)
                continue
            if words == [] or len(points) == 2:
                return None
            if len(words) == 2 and words[0].isdigit() and words[1] in MONTHS:
                points.append([int(words[0]), MONTHS[words[1]]])
            elif len(words) == 1 and words[0].isdigit():
                points.append([int(words[0]), None])
            elif len(words) == 1 and words[0] in MONTHS:
                points.append([None, MONTHS[words[0]]])
            else:
                return None
            words = []
        parts.append(points)
        current = []
    if not parts:
        return None

    # A day without a month takes the next month mentioned: "16–20 November", "18–22 and 28–29 May".
    next_month = None
    for points in reversed(parts):
        for point in reversed(points):
            if point[1] is None:
                if next_month is None:
                    return None
                point[1] = next_month
            next_month = point[1]

    periods, precision = [], "day"
    for points in parts:
        (first_day, first_month), (last_day, last_month) = points[0], points[-1]
        if first_day is None or last_day is None:
            precision = "month"
        try:
            start = date(year, first_month, first_day or 1)
            end_year = year if (last_month, last_day or 31) >= (first_month, first_day or 1) else year + 1
            end = date(end_year, last_month, last_day or calendar.monthrange(end_year, last_month)[1])
        except ValueError:  # e.g. "31 February"
            return None
        periods.append((start, end))
    return periods, precision
