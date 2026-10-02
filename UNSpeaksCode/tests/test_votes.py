"""Tests for the voting database, the UN loader and the voting service.

They use tiny versions of the UN Library files (votes_fixtures.py) with the real
column names, so they run offline in a second.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from unspeaks.build_db import build
from unspeaks.sources.undl import _clean_ga_title, read_source_info
from unspeaks.votes.service import VotingLookupError, VotingService
from unspeaks.votes.store import DataNotLoadedError, VoteStore, normalize_name
from votes_fixtures import write_raw_dir


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    raw = write_raw_dir(tmp_path_factory.mktemp("raw"))
    path = tmp_path_factory.mktemp("db") / "unspeaks.sqlite"
    summary = build(raw, path, log=lambda message: None)
    return path, summary


@pytest.fixture
def service(database):
    return VotingService(VoteStore(database[0]))


# --- building the database ------------------------------------------------------


def test_build_loads_every_dataset(database):
    _, summary = database
    assert summary == {
        "ga_resolutions": 5, "ga_votes": 12, "sc_resolutions": 2, "sc_votes": 3, "members": 4,
    }


def test_build_without_datasets_does_nothing(tmp_path):
    output = tmp_path / "unspeaks.sqlite"
    assert build(tmp_path, output, log=lambda m: None) == {}
    assert not output.exists()


@pytest.mark.parametrize("raw, clean", [
    ("Question of Palestine : resolution / adopted by the General Assembly", "Question of Palestine"),
    ("Trust Territories :P resolution / adopted by the General Assembly", "Trust Territories"),
    ("Nuclear-weapon-free zone : resolution / adopted by the General Assemly", "Nuclear-weapon-free zone"),
    ("Admission of Jamaica  resolution / adopted by the General Assembly", "Admission of Jamaica"),
    ("Resolution adopted by the General Assembly at its 2093rd plenary meeting",
     "Resolution adopted by the General Assembly at its 2093rd plenary meeting"),
])
def test_library_suffix_is_removed_from_titles(raw, clean):
    assert _clean_ga_title(raw) == clean


def test_citation_comes_from_the_library_description(tmp_path):
    csv_path = write_raw_dir(tmp_path) / "2026_02_06_ga_voting.csv"
    (tmp_path / "2026_02_06_ga_voting_md.md").write_text(
        "# GA voting\n## Citation\nUnited Nations Dag Hammarskjöld Library, General Assembly Voting "
        "Data, United Nations, version 5 (February 2026), 2026, downloaded from "
        "https://digitallibrary.un.org/record/4060887, [download date]\n## Version\n"
        "Version 5 (February 2026)\n",
        encoding="utf-8",
    )
    stamp = datetime(2026, 9, 25, 12, 0).timestamp()
    os.utime(csv_path, (stamp, stamp))
    info = read_source_info("ga_voting", csv_path)
    assert info["version"] == "Version 5 (February 2026)"
    assert info["citation"].endswith("record/4060887, 2026-09-25")


def test_citation_without_description_file(tmp_path):
    csv_path = write_raw_dir(tmp_path) / "2026_02_06_sc_voting.csv"
    info = read_source_info("sc_voting", csv_path)
    assert info["citation"].startswith("United Nations Dag Hammarskjöld Library, Security Council Voting Data")
    assert "https://digitallibrary.un.org/record/4055387" in info["citation"]


# --- one voting record ----------------------------------------------------------


def test_recorded_vote_lists_every_member(service):
    record = service.get_record("A/RES/80/10")
    assert record.body == "United Nations General Assembly"
    assert record.adoption_method == "recorded vote"
    assert record.votes == {
        "yes": ["NETHERLANDS (KINGDOM OF THE) (NLD)", "TÜRKIYE (TUR)"],
        "no": ["UNITED STATES (USA)"],
        "non_voting": ["REPUBLIC OF KOREA (KOR)"],
    }
    assert record.totals.yes == 2 and record.totals.members == 4
    assert record.details["subjects"] == ["INDIGENOUS PEOPLES", "WOMEN"]
    assert record.record_url == "https://digitallibrary.un.org/record/1"


def test_every_record_names_its_sources(service):
    record = service.get_record("A/RES/80/10")
    titles = [source.title for source in record.sources]
    assert titles == ["General Assembly resolutions", "General Assembly Voting Data"]
    assert record.sources[0].data_until == "2025-10-20"
    assert "United Nations" in record.sources[1].citation


@pytest.mark.parametrize("symbol", ["A/RES/62/223A", "A/RES/62/223 A", "a/res/62/223 a"])
def test_symbols_are_found_however_they_are_written(service, symbol):
    assert service.get_record(symbol).identifier == "A/RES/62/223 A"


def test_without_a_vote_is_explained_not_treated_as_missing(service):
    record = service.get_record("A/RES/80/2")
    assert record.adoption_method == "without a vote"
    assert record.votes is None and record.totals is None
    assert "not missing data" in record.explanation


def test_non_recorded_vote_has_no_member_list(service):
    record = service.get_record("A/RES/43/62")
    assert record.adoption_method == "non-recorded vote"
    assert record.votes is None
    assert "not recorded" in record.explanation


def test_security_council_marks_permanent_members(service):
    record = service.get_record("S/RES/2720")  # without the year
    assert record.identifier == "S/RES/2720(2023)"
    assert record.votes["abstain"] == ["UNITED STATES (USA, permanent member)"]


def test_security_council_without_a_vote(service):
    record = service.get_record("S/RES/331(1973)", member="Netherlands")
    assert record.votes is None
    assert record.totals.yes is None and record.totals.members == 3
    assert record.member_vote.vote is None
    assert "no individual votes" in record.member_vote.note


def test_highlights_one_members_vote(service):
    record = service.get_record("A/RES/80/10", member="usa")
    assert record.member_vote.vote == "no"
    assert record.member_vote.name == "UNITED STATES"
    assert record.sources[-1].title == "United Nations Member States"


def test_only_totals_when_member_lists_are_not_wanted(service):
    record = service.get_record("A/RES/80/10", include_votes=False)
    assert record.votes is None and record.totals.yes == 2


def test_unknown_symbol_explains_coverage_and_suggests(service):
    with pytest.raises(VotingLookupError) as error:
        service.get_record("resolution 2720")
    message = str(error.value)
    assert "UNGA (United Nations General Assembly): 1988-12-07 to 2025-10-20" in message
    assert "vetoed" in message
    assert "S/RES/2720(2023)" in message


# --- members ------------------------------------------------------------------------


@pytest.mark.parametrize("text, code", [
    ("Netherlands", "NLD"), ("Pays-Bas (Royaume des)", "NLD"), ("NLD", "NLD"),
    ("Turkey", "TUR"), ("turkiye", "TUR"), ("United States of America", "USA"),
    ("South Korea", "KOR"), ("Korea", "KOR"),
])
def test_members_are_recognised_by_any_name(service, text, code):
    assert service._resolve_member(text)[0] == code


def test_members_without_votes_are_not_matched(service):
    with pytest.raises(VotingLookupError, match="No member matches"):
        service._resolve_member("North Korea")  # in the names file, but never voted here


def test_normalize_name():
    assert normalize_name("Côte d'Ivoire") == "cote d ivoire"
    assert normalize_name("TÜRKİYE") == "turkiye"


# --- search -------------------------------------------------------------------------


def test_search_by_words(service):
    result = service.search(query="weapon", body_id="UNGA")  # word beginnings match
    assert [r.identifier for r in result.results] == ["A/RES/62/223B", "A/RES/62/223 A"]


def test_search_how_a_member_voted(service):
    result = service.search(member="United States")
    assert result.member.code == "USA"
    assert [(r.identifier, r.member_vote) for r in result.results] == [
        ("A/RES/80/10", "no"), ("S/RES/2720(2023)", "abstain"),  # newest first
        ("A/RES/62/223B", "yes"), ("A/RES/62/223 A", "abstain"),
    ]
    assert "without a vote" in result.note


def test_search_by_position(service):
    result = service.search(member="USA", vote="abstain", body_id="UNGA")
    assert [r.identifier for r in result.results] == ["A/RES/62/223 A"]


def test_search_by_dates_and_method(service):
    assert service.search(date_from="2025").total == 2
    assert service.search(date_to="1990").total == 2  # A/RES/43/62 and S/RES/331(1973)
    result = service.search(adoption_method="without a vote")
    assert [r.identifier for r in result.results] == ["A/RES/80/2", "S/RES/331(1973)"]


def test_search_pages(service):
    first = service.search(body_id="UNGA", limit=2)
    second = service.search(body_id="UNGA", limit=2, page=2)
    assert first.total == 5 and first.has_more
    assert {r.identifier for r in first.results}.isdisjoint(r.identifier for r in second.results)


def test_search_with_no_results_still_shows_sources(service):
    result = service.search(query="zzzz")
    assert result.total == 0 and "Nothing found" in result.note
    assert result.sources  # so the AI knows which data (and up to when) was searched


def test_position_needs_a_member(service):
    with pytest.raises(VotingLookupError, match="member"):
        service.search(vote="no")


def test_missing_database_says_how_to_build_it(tmp_path):
    with pytest.raises(DataNotLoadedError, match="unspeaks-build-db"):
        VotingService(VoteStore(tmp_path / "missing.sqlite")).get_record("A/RES/80/10")
