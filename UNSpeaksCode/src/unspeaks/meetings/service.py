"""Find meetings of UN bodies in a period: the logic behind the `search_meetings` tool.

A `MeetingSource` is anywhere meetings come from. There is one kind now,
`CalendarSource`: the calendar of conferences and meetings of one year (an ODS
document, set per year in config.MEETING_CALENDARS). Another kind, such as the
Journal of the United Nations, can be added later by writing a class with the same
two methods; `MeetingService` combines the answers of all sources.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Protocol

from unspeaks import config
from unspeaks.meetings.calendar_pdf import CalendarTable, load_calendar_table
from unspeaks.meetings.dates import MONTHS, CalendarDates, parse_dates
from unspeaks.meetings.models import Meeting, MeetingSourceInfo, SearchMeetingsResult
from unspeaks.ods_client import FetchedPdf, OdsClient
from unspeaks.votes.store import normalize_name

DEFAULT_DAYS = 14  # without date_to: from date_from for two weeks
MAX_UNDATED = 50  # the Security Council and its subsidiary bodies are 24 entries
MAX_LATER = 3  # how many later sessions to suggest when a body has none in the period

FetchPdf = Callable[[str, str], FetchedPdf]
_MONTH_NAMES = list(MONTHS)


class MeetingLookupError(Exception):
    """The question can't be answered as asked, e.g. date_to is before date_from."""


# --- Sources -------------------------------------------------------------------------


@dataclass(frozen=True)
class MeetingQuery:
    first: date
    last: date
    body_words: tuple[str, ...] = ()
    location_words: tuple[str, ...] = ()

    def matches(self, body_words: list[str], location_words: list[str]) -> bool:
        return _all_match(self.body_words, body_words) and _all_match(self.location_words, location_words)


@dataclass
class SourceAnswer:
    info: MeetingSourceInfo
    meetings: list[Meeting]  # with dates in the period
    undated: list[Meeting]  # without dates
    later: list[Meeting]  # the first ones after the period (only filled when asked)
    limitations: list[str]
    dated_matches: int = 0  # matching entries with dates, in any period


class MeetingSource(Protocol):
    years: tuple[int, ...]  # the years this source has meetings for

    def covers(self, first: date, last: date) -> bool:
        """Could this source have meetings between first and last?"""

    def find(self, query: MeetingQuery, *, later: bool = False) -> SourceAnswer:
        """Matching meetings in the period, and matching bodies without dates."""


@dataclass
class _Entry:
    meeting: Meeting
    dates: CalendarDates
    body_words: list[str]
    location_words: list[str]


@dataclass
class _Calendar:
    entries: list[_Entry]
    info: MeetingSourceInfo
    warnings: list[str] = field(default_factory=list)


class CalendarSource:
    """The calendar of conferences and meetings of one year, e.g. A/AC.172/2026/2."""

    def __init__(
        self,
        year: int,
        symbol: str,
        fetch_pdf: FetchPdf,
        table_loader: Callable[..., CalendarTable] = load_calendar_table,
        language: str = "en",
    ) -> None:
        self.year = year
        self.years = (year,)
        self.symbol = symbol
        self.language = language
        self._fetch_pdf = fetch_pdf
        self._table_loader = table_loader
        self._calendar: _Calendar | None = None
        self._lock = threading.Lock()

    def covers(self, first: date, last: date) -> bool:
        # (No session in the 2026 calendar runs into 2027; the next year's calendar would list one.)
        return first.year <= self.year <= last.year

    def find(self, query: MeetingQuery, *, later: bool = False) -> SourceAnswer:
        calendar = self._load()
        matching = [e for e in calendar.entries if query.matches(e.body_words, e.location_words)]
        dated = [e for e in matching if e.dates.kind == "dated"]
        in_period = [e.meeting for e in dated if e.dates.overlaps(query.first, query.last)]
        undated = [e.meeting for e in matching if e.dates.kind != "dated"]
        after = []
        if later:
            after = sorted((e for e in dated if e.dates.start > query.last), key=_order)
            after = [e.meeting for e in after[:MAX_LATER]]
        return SourceAnswer(calendar.info, in_period, undated, after, self._limitations(calendar.info),
                            dated_matches=len(dated))

    def _load(self) -> _Calendar:
        """Download (or reuse) the PDF and read its table once; afterwards it is kept in memory."""
        with self._lock:
            if self._calendar is None:
                fetched = self._fetch_pdf(self.symbol, self.language)
                table = self._table_loader(fetched.path)
                self._calendar = self._build(table, fetched)
            return self._calendar

    def _build(self, table: CalendarTable, fetched: FetchedPdf) -> _Calendar:
        as_at = min((s.as_at for s in table.sections if s.as_at), default=None)
        title = f"Calendar of conferences and meetings of the United Nations for {self.year}"
        as_at_text = f", as at {_day_text(as_at)}" if as_at else ""
        citation = (
            f"United Nations, {title} ({fetched.symbol}){as_at_text}, Official Document System, "
            f"{fetched.source_url}, accessed {fetched.fetched_at[:10]}."
        )
        info = MeetingSourceInfo(
            symbol=fetched.symbol, title=title, url=fetched.source_url, as_at=as_at,
            downloaded_at=fetched.fetched_at, citation=citation,
        )
        entries = []
        for row in table.entries:
            cells = row.cells
            dates = parse_dates(cells.get("dates", ""), self.year)
            meeting = Meeting(
                body=cells.get("organ", ""),
                title=cells.get("title") or None,
                dates=dates.text,
                start=dates.start,
                end=dates.end,
                date_precision=dates.precision,
                to_be_confirmed=dates.to_be_confirmed,
                date_note=dates.note,
                location=cells.get("location") or None,
                periodicity=cells.get("periodicity") or None,
                section=row.section if row.section in ("A", "B") else None,
                entry=row.number,
                page=row.page,
                source=fetched.symbol,
            )
            entries.append(_Entry(meeting, dates, _words(meeting.body), _words(meeting.location)))
        return _Calendar(entries, info, list(table.warnings))

    def _limitations(self, info: MeetingSourceInfo) -> list[str]:
        as_at = f"as at {_day_text(info.as_at)}" if info.as_at else "from early in the year"
        return [
            f"The calendar for {self.year} ({info.symbol}) is {as_at}: changes after that date are "
            "missing. The Journal of the United Nations (journal.un.org) has the current programme.",
            "It lists sessions (the period in which a body meets), not individual meetings: "
            "no agendas, times or rooms.",
            "Bodies that meet 'as required', such as the Security Council and its committees, "
            "have no dates in the calendar.",
            "Dates marked 'to be confirmed', and places 'to be determined', can still change.",
        ]


# --- The service -----------------------------------------------------------------------


class MeetingService:
    def __init__(
        self,
        sources: list[MeetingSource] | None = None,
        *,
        fetch_pdf: FetchPdf | None = None,
        calendars: dict[int, str] | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        if sources is None:
            if fetch_pdf is None:
                fetch_pdf = OdsClient().fetch_pdf
            calendars = config.MEETING_CALENDARS if calendars is None else calendars
            sources = [CalendarSource(year, symbol, fetch_pdf) for year, symbol in sorted(calendars.items())]
        self.sources = sources
        self._today = today

    def search(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        body: str | None = None,
        location: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> SearchMeetingsResult:
        today = self._today()
        first = _read_day(date_from, "date_from", first=True) if date_from else today
        if date_to:
            last = _read_day(date_to, "date_to", first=False)
        elif date_from and len(date_from.strip()) < 10:  # a month or year: all of it
            last = _read_day(date_from, "date_from", first=False)
        else:
            last = first + timedelta(days=DEFAULT_DAYS - 1)
        if last < first:
            raise MeetingLookupError(f"date_to ({last}) is before date_from ({first}).")
        limit, page = max(1, min(limit, 50)), max(1, page)
        query = MeetingQuery(first, last, tuple(_words(body)), tuple(_words(location)))

        answers = [s.find(query, later=bool(body)) for s in self.sources if s.covers(first, last)]
        notes: list[str] = []
        have = {year for source in self.sources for year in source.years}
        missing = [year for year in range(first.year, last.year + 1) if year not in have]
        if missing:
            years = ", ".join(str(year) for year in missing)
            notes.append(f"UNSpeaks has no meeting calendar for {years}, so meetings in {years} are missing.")

        meetings = sorted((m for a in answers for m in a.meetings), key=_meeting_order)
        undated = sorted((m for a in answers for m in a.undated), key=lambda m: (m.section or "", m.entry or 0))
        total = len(meetings)
        offset = (page - 1) * limit
        shown = meetings[offset: offset + limit]
        if offset and not shown and total:
            notes.append(f"Page {page} is past the end: there are {total} results.")

        if body:
            listed = undated[:MAX_UNDATED]
            if len(undated) > MAX_UNDATED:
                notes.append(f"Only the first {MAX_UNDATED} of {len(undated)} bodies without dates are listed.")
            if not meetings:
                later = sorted((m for a in answers for m in a.later), key=_meeting_order)[:MAX_LATER]
                if later:
                    notes.append("No matching session in this period. The next ones in the calendar: "
                                 + "; ".join(_describe(m) for m in later) + ".")
                elif any(a.dated_matches for a in answers):
                    notes.append("No matching session in this period or later in the calendar; "
                                 "use an earlier date_from to see earlier ones.")
                elif not undated:
                    notes.append("No body in the calendar matches these words. Use words from the "
                                 "body's name as the calendar writes it; agencies go by their "
                                 "abbreviation, e.g. 'WFP', 'UNICEF', 'IAEA'.")
        else:
            listed = []
            if undated:
                example = next((m.body for m in undated if m.body == "Security Council"), undated[0].body)
                notes.append(
                    f"{len(undated)} matching bodies have no dates in the calendar ('As required' or "
                    f"'To be determined'), such as the {example}. Search with `body` to list them."
                )

        limitations = list(dict.fromkeys(text for a in answers for text in a.limitations))
        return SearchMeetingsResult(
            date_from=first, date_to=last, today=today, total=total, page=page,
            next_page=page + 1 if offset + limit < total else None,
            meetings=shown, undated_total=len(undated), undated=listed, notes=notes,
            limitations=limitations, sources=[a.info for a in answers],
        )


# --- helpers -------------------------------------------------------------------------


def _words(text: str | None) -> list[str]:
    return normalize_name(text or "").split()


def _all_match(wanted: tuple[str, ...], words: list[str]) -> bool:
    """Every wanted word is the beginning of one of the words (as in search_votes)."""
    return all(any(word.startswith(w) for word in words) for w in wanted)


def _order(entry: _Entry):
    return _meeting_order(entry.meeting)


def _meeting_order(meeting: Meeting):
    # By start date; entries known only by half year ("Second semester") go last.
    return (meeting.date_precision == "half-year", meeting.start or date.max,
            meeting.section or "", meeting.entry or 0)


def _day_text(day: date) -> str:
    return f"{day.day} {_MONTH_NAMES[day.month - 1]} {day.year}"


def _describe(meeting: Meeting) -> str:
    parts = [meeting.body, meeting.title, meeting.dates, meeting.location]
    return ", ".join(p for p in parts if p) + f" (entry {meeting.section} {meeting.entry})"


def _read_day(text: str, name: str, *, first: bool) -> date:
    """'2026-11-16' -> that day; '2026-11' or '2026' -> its first (or last) day."""
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", (text or "").strip())
    try:
        if not match:
            raise ValueError
        year, month, day = (int(g) if g else None for g in match.groups())
        if day:
            return date(year, month, day)
        if month:
            start = date(year, month, 1)  # also checks the month
            return start if first else date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
        return date(year, 1, 1) if first else date(year, 12, 31)
    except ValueError:
        raise MeetingLookupError(f"{name} '{text}' is not a valid date. Use YYYY-MM-DD, YYYY-MM or YYYY.") from None
