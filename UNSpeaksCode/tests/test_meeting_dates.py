"""Reading the "Dates" column of the calendar. Plain text in, dates out."""

from __future__ import annotations

from datetime import date

import pytest

from unspeaks.meetings.dates import clean_dates_text, parse_dates


def d(month: int, day: int, year: int = 2026) -> date:
    return date(year, month, day)


@pytest.mark.parametrize(
    "text, periods, precision",
    [
        ("16–20 November", [(d(11, 16), d(11, 20))], "day"),
        ("23 November–\n11 December", [(d(11, 23), d(12, 11))], "day"),
        ("16 and\n17 November", [(d(11, 16), d(11, 16)), (d(11, 17), d(11, 17))], "day"),
        ("2-6 November", [(d(11, 2), d(11, 6))], "day"),
        ("26–30 January,\nand 4–6 and\n20 February",
         [(d(1, 26), d(1, 30)), (d(2, 4), d(2, 6)), (d(2, 20), d(2, 20))], "day"),
        ("18–22 and 28–29 May and 5 June",
         [(d(5, 18), d(5, 22)), (d(5, 28), d(5, 29)), (d(6, 5), d(6, 5))], "day"),
        ("14 December–15 January", [(d(12, 14), d(1, 15, 2027))], "day"),
        ("November", [(d(11, 1), d(11, 30))], "month"),
        ("February–March", [(d(2, 1), d(3, 31))], "month"),
        ("8 September– December", [(d(9, 8), d(12, 31))], "month"),
        ("Second semester", [(d(7, 1), d(12, 31))], "half-year"),
    ],
)
def test_dates_become_periods(text, periods, precision):
    dates = parse_dates(text, 2026)
    assert dates.kind == "dated"
    assert list(dates.periods) == periods
    assert dates.precision == precision
    assert dates.start == periods[0][0] and dates.end == periods[-1][1]


@pytest.mark.parametrize(
    "text, expected, periods",
    [
        # Footnote letters glued to the month, as in the plain text of the PDF
        ("23 Novembers", "23 November", [(d(11, 23), d(11, 23))]),  # footnote s
        ("23–25 Novemberq", "23–25 November", [(d(11, 23), d(11, 25))]),  # footnote q
        ("12 January–\n17 Aprile,f,g", "12 January–17 April", [(d(1, 12), d(4, 17))]),  # e, f and g
        ("19 January–\n27 Marche,f", "19 January–27 March", [(d(1, 19), d(3, 27))]),
    ],
)
def test_footnote_letters_after_a_month_are_dropped(text, expected, periods):
    assert clean_dates_text(text) == expected
    dates = parse_dates(text, 2026)
    assert dates.text == expected
    assert list(dates.periods) == periods


def test_to_be_confirmed_and_remarks_are_kept_apart():
    dates = parse_dates("23 Novembers\n(to be confirmed)", 2026)
    assert dates.periods == ((d(11, 23), d(11, 23)),)
    assert dates.to_be_confirmed is True and dates.note is None
    assert dates.text == "23 November (to be confirmed)"

    one = parse_dates("February (one meeting)", 2026)
    assert one.precision == "month" and one.note == "one meeting" and not one.to_be_confirmed

    some_day = parse_dates("One day out of 2–6 November (exact date to be confirmed)", 2026)
    assert some_day.periods == ((d(11, 2), d(11, 6)),)
    assert some_day.to_be_confirmed is True
    assert some_day.note == "one day in this period; exact date to be confirmed"


@pytest.mark.parametrize(
    "text, kind, note",
    [
        ("As required", "as_required", None),
        ("As required (up to 30 meetings)", "as_required", "up to 30 meetings"),
        ("To be determined", "to_be_determined", None),
        ("To be determined\n(two to three days)", "to_be_determined", "two to three days"),
    ],
)
def test_bodies_without_dates(text, kind, note):
    dates = parse_dates(text, 2026)
    assert dates.kind == kind
    assert dates.periods == () and dates.start is None and dates.end is None
    assert dates.note == note
    assert not dates.overlaps(d(1, 1), d(12, 31))  # never in any period


def test_a_body_that_meets_every_fortnight():
    dates = parse_dates("9 January and\nonce every\nfortnight thereafter", 2026)  # Military Staff Committee
    days = [first for first, _ in dates.periods]
    assert days[:3] == [d(1, 9), d(1, 23), d(2, 6)]
    assert days[-1] == d(12, 25) and len(days) == 26
    assert dates.overlaps(d(11, 16), d(11, 22)) is False  # no meeting that week...
    assert dates.overlaps(d(11, 23), d(11, 29)) is True  # ...but one on Friday 27 November


def test_overlap_uses_each_part_of_a_date():
    dates = parse_dates("26–30 January, and 4–6 and 20 February", 2026)
    assert dates.overlaps(d(2, 5), d(2, 5))
    assert not dates.overlaps(d(2, 9), d(2, 13))  # between the parts
    assert dates.overlaps(d(1, 1), d(1, 26))  # touching the first day counts


@pytest.mark.parametrize("text", ["Soon", "31 February", "16–20", "", "16–20–24 November"])
def test_text_that_is_not_understood_is_marked_unparsed(text):
    dates = parse_dates(text, 2026)
    assert dates.kind == "unparsed" and dates.periods == ()
