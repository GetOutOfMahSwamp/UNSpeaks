"""What search_meetings returns.

The shape is not tied to the calendar: `kind` says what an item is. The calendar gives
"session" items; a later source such as the Journal of the United Nations could add
"meeting" items (single meetings, with times and agendas) without changing the shape.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Meeting(BaseModel):
    kind: Literal["session"] = Field(
        "session",
        description="'session': a period in which the body meets (it can hold many meetings)",
    )
    body: str = Field(description="Who meets, as written in the source")
    title: str | None = Field(None, description="Session title, e.g. 'Seventh session'")
    dates: str = Field(description="The dates as written in the source, e.g. '16–20 November' or 'As required'")
    start: date | None = Field(None, description="First day; null if the source gives no dates")
    end: date | None = Field(None, description="Last day; null if the source gives no dates")
    date_precision: Literal["day", "month", "half-year"] | None = Field(
        None, description="'month' or 'half-year': only the month or half of the year is known"
    )
    to_be_confirmed: bool = Field(False, description="The source marks the dates as to be confirmed")
    date_note: str | None = Field(None, description="e.g. 'one meeting', 'three days'")
    location: str | None = None
    periodicity: str | None = Field(None, description="How often the body meets, e.g. 'Two sessions per year'")
    section: Literal["A", "B"] | None = Field(
        None,
        description="Calendar section: 'A' = United Nations bodies; 'B' = specialized agencies, "
        "IAEA and treaty bodies",
    )
    entry: int | None = Field(None, description="Entry number in that section of the calendar")
    page: int | None = Field(None, description="PDF page of the entry (get_document start_page)")
    source: str = Field(description="Symbol of the source document; see `sources`")


class MeetingSourceInfo(BaseModel):
    symbol: str
    title: str
    url: str = Field(description="Where the PDF was downloaded from (Official Document System)")
    as_at: date | None = Field(description="The source is 'as at' this day: later changes are missing")
    downloaded_at: str = Field(description="When UNSpeaks downloaded it (UTC)")
    copyright: str = "© United Nations"
    citation: str = Field(description="Ready-made citation to include when using this data")


class SearchMeetingsResult(BaseModel):
    date_from: date
    date_to: date
    today: date = Field(description="Today's date on the UNSpeaks server")
    total: int = Field(description="Number of matching sessions with dates in the period")
    page: int
    next_page: int | None = Field(description="Pass as `page` for more; null when there are no more")
    meetings: list[Meeting] = Field(description="Sessions in the period, by start date")
    undated_total: int = Field(
        description="Number of matching bodies without dates in the source ('As required' or "
        "'To be determined'), such as the Security Council"
    )
    undated: list[Meeting] = Field(description="Those bodies; only listed when `body` is given")
    notes: list[str]
    limitations: list[str] = Field(description="Mention these in your answer")
    sources: list[MeetingSourceInfo]
