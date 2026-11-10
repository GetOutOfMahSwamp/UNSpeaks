"""The meetings package: reading the calendar PDF, and searching it. Never online."""

from __future__ import annotations

import json
from datetime import date

import pytest

from unspeaks import config
from unspeaks.meetings import calendar_pdf
from unspeaks.meetings.calendar_pdf import PARSER_VERSION, load_calendar_table, read_calendar_table
from unspeaks.meetings.service import CalendarSource, MeetingLookupError, MeetingService

from meetings_fixtures import PDF_URL, SYMBOL, calendar_fetcher, calendar_pdf as fixture_pdf, write_calendar_pdf


@pytest.fixture(scope="module")
def table():
    return read_calendar_table(fixture_pdf())


def entry(table, section, number):
    return next(e for e in table.entries if e.section == section and e.number == number)


# --- Reading the PDF ---------------------------------------------------------------


def test_every_entry_is_found_with_its_section_number_and_page(table):
    assert [(e.section, e.number, e.page) for e in table.entries] == [
        ("A", 292, 2), ("A", 296, 2), ("A", 298, 2), ("A", 300, 2), ("A", 302, 2),
        ("A", 314, 3), ("A", 336, 3), ("A", 337, 3), ("A", 338, 3), ("A", 385, 3),
        ("B", 68, 4), ("B", 70, 4), ("B", 77, 4),
    ]
    assert table.warnings == []


def test_sections_and_their_as_at_dates(table):
    assert [(s.letter, s.as_at) for s in table.sections] == [("A", date(2026, 2, 2)), ("B", date(2026, 2, 2))]
    assert table.sections[0].heading == "Calendar of conferences and meetings of the United Nations, 2026"
    assert table.sections[1].heading.endswith("treaty bodies established under the auspices of the United Nations, 2026")


def test_columns_are_kept_apart(table):
    cells = entry(table, "A", 292).cells
    assert cells["organ"].lower() == (
        "conference on the establishment of a middle east zone free of nuclear weapons "
        "and other weapons of mass destruction"
    )
    assert cells["mandate"] == "General Assembly decision 73/546"
    assert cells["title"] == "Seventh session"
    assert cells["location"] == "New York"
    assert cells["periodicity"] == "One session per year"

    security_council = entry(table, "A", 336).cells
    assert security_council["organ"] == "Security Council"
    assert security_council["mandate"] == "Charter"
    assert security_council["dates"] == "As required"
    assert "title" not in security_council


def test_footnote_letters_are_left_out_of_names_and_dates(table):
    wfp = entry(table, "A", 296).cells
    assert wfp["organ"] == "WFP, Executive Board"  # not "Boardb"
    assert (wfp["dates"], wfp["location"]) == ("16–20 November", "Rome")
    assert entry(table, "A", 292).cells["dates"] == "16–20 November"  # not "Novembers"
    racial = entry(table, "A", 302).cells
    assert racial["organ"] == "Committee on the Elimination of Racial Discrimination"  # not "...Discriminationc"
    assert racial["dates"] == "23 November–11 December"  # not "Decemberq"
    assert racial["title"] == "119th session" and racial["location"] == "Geneva"


def test_an_entry_continued_on_the_next_page_is_joined(table):
    assert entry(table, "A", 302).cells["periodicity"] == "Three sessions per year"


def test_a_hyphen_at_the_start_of_a_line_is_joined(table):
    assert entry(table, "A", 338).cells["organ"].endswith("concerning counter-terrorism")


def test_sideways_text_and_footnotes_below_the_table_are_ignored(table):
    text = json.dumps([e.cells for e in table.entries])
    assert "A/AC.172" not in text  # the symbol printed along the page
    assert "languages" not in text and "Subject to the approval" not in text  # footnotes
    assert entry(table, "A", 385).cells["dates"] == "To be determined (one week)"


def test_part_b_has_its_own_columns(table):
    assert entry(table, "B", 70).cells == {
        "organ": "Conference of the States Parties to the Convention on the Prohibition of the Development, "
                 "Production, Stockpiling and Use of Chemical Weapons and on Their Destruction",
        "title": "Thirty-first session",
        "dates": "23–27 November",
        "location": "The Hague, Netherlands (Kingdom of the)",
    }


def test_a_pdf_without_a_calendar_gives_a_warning(make_pdf):
    result = read_calendar_table(make_pdf(["Just a letter.", "Nothing to see here."]))
    assert result.entries == [] and result.warnings


def test_the_result_is_cached_next_to_the_pdf(tmp_path, monkeypatch):
    pdf = write_calendar_pdf(tmp_path)
    first = load_calendar_table(pdf)
    cache = tmp_path / "A_AC.172_2026_2.calendar.json"
    assert cache.exists()

    def must_not_read(_):
        raise AssertionError("the PDF should not be read again")

    monkeypatch.setattr(calendar_pdf, "read_calendar_table", must_not_read)
    assert load_calendar_table(pdf) == first

    # A cache from an older version of the reader is read again.
    old = json.loads(cache.read_text(encoding="utf-8"))
    old["parser_version"] = PARSER_VERSION - 1
    cache.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.undo()
    assert load_calendar_table(pdf).parser_version == PARSER_VERSION


# --- Searching ---------------------------------------------------------------------


@pytest.fixture
def fetch(tmp_path):
    return calendar_fetcher(write_calendar_pdf(tmp_path))


@pytest.fixture
def service(fetch):
    return MeetingService(fetch_pdf=fetch, calendars={2026: SYMBOL}, today=lambda: date(2026, 11, 10))


def entries(result):
    return [(m.section, m.entry) for m in result.meetings]


def test_next_week_in_new_york(service):
    result = service.search(date_from="2026-11-16", date_to="2026-11-22", location="New York")
    assert entries(result) == [("A", 314), ("A", 292)]  # by start date: "November" starts on the 1st
    first, middle_east = result.meetings
    assert (first.dates, first.date_precision) == ("November", "month")
    assert middle_east.model_dump(exclude={"body"}) == {
        "kind": "session", "title": "Seventh session", "dates": "16–20 November",
        "start": date(2026, 11, 16), "end": date(2026, 11, 20), "date_precision": "day",
        "to_be_confirmed": False, "date_note": None, "location": "New York",
        "periodicity": "One session per year", "section": "A", "entry": 292, "page": 2, "source": SYMBOL,
    }
    # Bodies without dates are counted, not listed.
    assert result.undated_total == 3 and result.undated == []
    assert any("Security Council" in note for note in result.notes)


def test_every_answer_has_a_citation_the_as_at_date_and_the_limits(service):
    result = service.search(date_from="2026-11-16", date_to="2026-11-22")
    source = result.sources[0]
    assert (source.symbol, source.url, source.as_at) == (SYMBOL, PDF_URL, date(2026, 2, 2))
    assert SYMBOL in source.citation and PDF_URL in source.citation
    assert "as at 2 February 2026" in source.citation
    limits = " ".join(result.limitations)
    assert "as at 2 February 2026" in limits and "changes after that date are missing" in limits
    assert "sessions" in limits and "not individual meetings" in limits
    assert "Security Council" in limits


def test_a_session_counts_when_it_overlaps_the_period(service):
    result = service.search(date_from="2026-12-01", date_to="2026-12-05")
    # 302: 23 November–11 December; 77: "Second semester" (July–December), so it goes last
    assert entries(result) == [("A", 302), ("B", 77)]
    assert result.meetings[1].date_precision == "half-year"


def test_body_filter_lists_bodies_without_dates(service):
    result = service.search(date_from="2026-11-16", date_to="2026-11-22", body="security council")
    assert result.meetings == []
    assert [(m.entry, m.dates, m.start) for m in result.undated] == [
        (336, "As required", None), (337, "As required", None), (338, "As required", None),
    ]
    assert result.undated_total == 3


def test_body_words_match_word_beginnings_and_ignore_case_and_accents(service):
    result = service.search(date_from="2026", body="Raciál discrim")
    assert entries(result) == [("A", 302)]


def test_part_b_is_included_and_marked(service):
    result = service.search(date_from="2026-11-16", date_to="2026-11-22", location="Vienna")
    assert [(m.section, m.entry, m.body, m.periodicity) for m in result.meetings] == [
        ("B", 68, "IAEA, Board of Governors", None),
    ]


def test_to_be_confirmed_dates_and_remarks(service):
    result = service.search(date_from="2026-11-23", date_to="2026-11-23", location="New York")
    palestinian = next(m for m in result.meetings if m.entry == 298)
    assert palestinian.to_be_confirmed is True and palestinian.dates == "23 November (to be confirmed)"


def test_a_body_with_nothing_in_the_period_gets_its_next_sessions(service):
    result = service.search(date_from="2026-11-01", date_to="2026-11-10", body="Racial Discrimination")
    assert result.meetings == []
    assert any("next ones" in note and "119th session" in note for note in result.notes)


def test_an_unknown_body_gets_a_hint(service):
    result = service.search(body="Atlantis")
    assert result.total == 0 and any("No body in the calendar matches" in note for note in result.notes)


def test_default_period_is_two_weeks_from_today(service):
    result = service.search()
    assert (result.today, result.date_from, result.date_to) == (date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 23))


def test_a_month_or_year_means_all_of_it(service):
    november = service.search(date_from="2026-11")
    assert (november.date_from, november.date_to) == (date(2026, 11, 1), date(2026, 11, 30))
    year = service.search(date_from="2026", date_to="2026")
    assert (year.date_from, year.date_to) == (date(2026, 1, 1), date(2026, 12, 31))
    assert year.total == 9  # every entry with dates, the semester one included


def test_paging(service):
    first = service.search(date_from="2026", limit=4)
    last = service.search(date_from="2026", limit=4, page=3)
    assert (first.total, first.next_page, len(first.meetings)) == (9, 2, 4)
    assert (last.next_page, len(last.meetings)) == (None, 1)
    assert "Page 4 is past the end: there are 9 results." in service.search(date_from="2026", limit=4, page=4).notes


@pytest.mark.parametrize(
    "date_from, date_to, message",
    [("2026-11-20", "2026-11-10", "before date_from"), ("2026-13", None, "not a valid date"),
     ("2026-02-30", None, "not a valid date"), ("next week", None, "not a valid date")],
)
def test_bad_dates_are_explained(service, date_from, date_to, message):
    with pytest.raises(MeetingLookupError, match=message):
        service.search(date_from=date_from, date_to=date_to)


def test_a_year_without_a_calendar_is_mentioned(service):
    result = service.search(date_from="2027-03-01", date_to="2027-03-31")
    assert result.total == 0 and result.sources == []
    assert result.notes == ["UNSpeaks has no meeting calendar for 2027, so meetings in 2027 are missing."]


def test_the_calendar_is_fetched_and_read_once(fetch, monkeypatch):
    reads = []
    original = calendar_pdf.read_calendar_table
    monkeypatch.setattr(calendar_pdf, "read_calendar_table", lambda pdf: reads.append(pdf) or original(pdf))
    service = MeetingService(fetch_pdf=fetch, calendars={2026: SYMBOL})
    service.search(date_from="2026-11")
    service.search(date_from="2026-12", location="Geneva")
    assert fetch.calls == [(SYMBOL, "en")] and len(reads) == 1


def test_the_calendar_symbol_comes_from_config(fetch, monkeypatch):
    monkeypatch.setattr(config, "MEETING_CALENDARS", {2026: "A/AC.172/2026/9"})
    MeetingService(fetch_pdf=fetch).search(date_from="2026-11")
    assert fetch.calls == [("A/AC.172/2026/9", "en")]


def test_a_source_only_covers_its_own_year(fetch):
    source = CalendarSource(2026, SYMBOL, fetch)
    assert source.covers(date(2026, 1, 1), date(2026, 1, 1))
    assert source.covers(date(2025, 12, 20), date(2026, 1, 5))
    assert not source.covers(date(2025, 12, 1), date(2025, 12, 31))
    assert not source.covers(date(2027, 1, 1), date(2027, 1, 31))
    assert fetch.calls == []  # deciding that needs no download


# --- The real calendar, if it has been downloaded ----------------------------------

REAL_CALENDAR = config.data_dir() / "cache" / "ods" / "en" / "A_AC.172_2026_2.pdf"


@pytest.mark.skipif(not REAL_CALENDAR.exists(), reason="A/AC.172/2026/2 has not been downloaded (data/cache)")
def test_the_real_2026_calendar():
    real = read_calendar_table(REAL_CALENDAR)  # read only: the cache is not touched
    assert real.warnings == []
    for section, count in (("A", 386), ("B", 77)):
        numbers = [e.number for e in real.entries if e.section == section]
        assert numbers == list(range(1, count + 1))

    def cells(number):
        return entry(real, "A", number).cells

    assert cells(292)["organ"].lower().startswith("conference on the establishment of a middle east zone")
    assert (cells(292)["title"], cells(292)["dates"], cells(292)["location"]) == (
        "Seventh session", "16–20 November", "New York")
    assert (cells(296)["organ"], cells(296)["title"], cells(296)["dates"], cells(296)["location"]) == (
        "WFP, Executive Board", "Second regular session", "16–20 November", "Rome")
    assert (cells(302)["organ"], cells(302)["title"], cells(302)["dates"], cells(302)["location"]) == (
        "Committee on the Elimination of Racial Discrimination", "119th session",
        "23 November–11 December", "Geneva")
    assert (cells(336)["organ"], cells(336)["dates"], cells(336)["location"]) == (
        "Security Council", "As required", "New York")
