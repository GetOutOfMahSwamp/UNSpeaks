"""Tests for building the voting data from the Library's weekly MARCXML archives.

They use tiny archives (marc_fixtures.py) next to the tiny CSV datasets (votes_fixtures.py),
so they run offline in a second.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime

import pytest

from marc_fixtures import GA_ARCHIVE, SC_ARCHIVE, write_archives
from unspeaks.build_db import build, main
from unspeaks.sources.undl import ARCHIVES, find_archive
from unspeaks.votes.service import VotingLookupError, VotingService
from unspeaks.votes.store import VoteStore
from votes_fixtures import write_raw_dir

GA_TITLE = "General Assembly voting data (weekly MARCXML export)"
SC_TITLE = "Security Council voting data (weekly MARCXML export)"
GA_URL = "https://digitallibrary.un.org/export/marcxml/all_voting_data_general_assembly.xml.gz"


def _build(raw, path):
    messages: list[str] = []
    summary = build(raw, path, log=messages.append)
    return VotingService(VoteStore(path)), summary, messages


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    # The CSV voting datasets are in the folder too: the archives replace them.
    raw = write_archives(write_raw_dir(tmp_path_factory.mktemp("raw")))
    return _build(raw, tmp_path_factory.mktemp("db") / "unspeaks.sqlite")


@pytest.fixture
def service(built):
    return built[0]


# --- building the database ------------------------------------------------------


def test_archives_replace_the_csv_voting_datasets(built):
    _, summary, messages = built
    assert summary == {
        "ga_resolutions": 5, "ga_votes": 8, "sc_resolutions": 4, "sc_votes": 9, "members": 4,
        "representatives": 3,
    }
    assert f"Not using 2026_02_06_ga_voting.csv: {GA_ARCHIVE} replaces it." in messages
    assert f"Not using 2026_02_06_sc_voting.csv: {SC_ARCHIVE} replaces it." in messages


def test_the_build_never_uses_the_network(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the build tried to use the network")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    raw = write_archives(write_raw_dir(tmp_path / "raw"))
    assert build(raw, tmp_path / "unspeaks.sqlite", log=lambda message: None)["ga_resolutions"] == 5


def test_csv_datasets_are_used_for_a_body_without_its_archive(tmp_path):
    raw = write_archives(write_raw_dir(tmp_path / "raw"), ga=False)  # only the Security Council archive
    service, summary, _ = _build(raw, tmp_path / "unspeaks.sqlite")
    assert (summary["ga_resolutions"], summary["ga_votes"]) == (5, 12)  # the CSV datasets
    assert [s.title for s in service.get_record("A/RES/80/10").sources] == [
        "General Assembly resolutions", "General Assembly Voting Data"]
    assert [s.title for s in service.get_record("S/RES/2720(2023)").sources] == [SC_TITLE]


def test_the_downloaded_gz_file_is_read_without_unzipping(tmp_path):
    raw = write_archives(tmp_path / "raw", sc=False, gz=True)
    service, summary, _ = _build(raw, tmp_path / "unspeaks.sqlite")
    assert summary == {"ga_resolutions": 5, "ga_votes": 8, "members": 4}
    assert service.get_record("A/RES/ES-11/1").sources[0].citation.endswith(", 2026-10-27")


def test_the_newest_of_the_unzipped_and_downloaded_archive_is_used(tmp_path):
    write_archives(tmp_path, sc=False)
    write_archives(tmp_path, sc=False, gz=True)
    earlier = datetime(2026, 10, 20, 12, 0).timestamp()
    os.utime(tmp_path / GA_ARCHIVE, (earlier, earlier))
    assert find_archive(tmp_path, ARCHIVES["ga_marcxml"]).name == f"{GA_ARCHIVE}.gz"
    assert find_archive(tmp_path, ARCHIVES["sc_marcxml"]) is None


def test_an_incomplete_archive_stops_the_build_and_keeps_the_database(tmp_path, capsys):
    raw = write_archives(write_raw_dir(tmp_path / "raw"))
    output = tmp_path / "unspeaks.sqlite"
    build(raw, output, log=lambda message: None)
    before = output.read_bytes()
    archive = raw / GA_ARCHIVE
    archive.write_bytes(archive.read_bytes()[:2000])  # e.g. an interrupted download

    with pytest.raises(ValueError, match="not a complete MARCXML file"):
        build(raw, output, log=lambda message: None)
    assert main(["--raw-dir", str(raw), "--output", str(output)]) == 1
    assert "Download it again by hand" in capsys.readouterr().err
    assert output.read_bytes() == before
    assert not (tmp_path / "unspeaks.sqlite.building").exists()


# --- General Assembly -----------------------------------------------------------


def test_recorded_vote_from_the_archive(service):
    record = service.get_record("A/RES/ES-11/1")
    assert record.adoption_method == "recorded vote"
    assert record.title == "Aggression against Ukraine"  # without ': resolution / adopted by ...'
    assert (record.date, record.session) == ("2022-03-02", "11emsp")
    assert record.votes == {
        "yes": ["NETHERLANDS (NLD)", "UNITED STATES (USA)"],
        "abstain": ["TURKEY (TUR)"],
        "non_voting": ["REPUBLIC OF KOREA (KOR)"],  # 967 without $d
    }
    assert record.totals.model_dump() == dict(yes=2, no=0, abstain=1, non_voting=1, members=4)
    assert record.details == {
        "undl_id": "3959039",
        "draft": ["A/ES-11/L.1", "A/ES-11/L.1/Add.1"],
        "meeting": ["A/ES-11/PV.5"],
        "agenda_items": ["Letter dated 28 February 2014 from the Permanent Representative of Ukraine (S/2014/136)."],
        "subjects": ["UKRAINE--POLITICAL CONDITIONS"],
    }
    assert record.record_url == "https://digitallibrary.un.org/record/3959039"


def test_non_recorded_vote_keeps_its_totals(service):
    record = service.get_record("A/RES/43/62")
    assert record.adoption_method == "non-recorded vote"
    assert record.votes is None
    assert record.totals.model_dump() == dict(yes=149, no=0, abstain=5, non_voting=5, members=159)
    assert record.details["committee_report"] == ["A/43/830"] and "draft" not in record.details


def test_without_a_vote_from_the_archive(service):
    record = service.get_record("A/RES/80/2", member="Netherlands")
    assert record.adoption_method == "without a vote"
    assert record.votes is None and record.totals is None
    assert record.member_vote.vote is None and "no individual votes" in record.member_vote.note
    assert record.details["draft"] == ["A/C.5/80/L.2"]
    assert record.details["committee_report"] == ["A/80/401"]
    assert record.details["subjects"] == ["UN--BUDGET CONTRIBUTIONS"]


def test_the_date_comes_from_992_and_a_different_269_is_noted(service):
    record = service.get_record("A/RES/49/249A")
    assert record.date == "1995-07-20"
    assert "1993-10-13" in record.details["date_note"]
    assert "date_note" not in service.get_record("A/RES/81/6").details  # new records have no 269
    record = service.get_record("S/RES/1470(2003)")
    assert record.date == "2003-03-28" and "date_note" not in record.details  # 269 is only '2003-03'


def test_a_divided_resolution_is_suggested_for_its_old_symbol(service):
    assert service.get_record("A/RES/49/249A").details["other_symbols"] == ["A/RES/49/249"]
    with pytest.raises(VotingLookupError, match=r"Did you mean: A/RES/49/249A\?"):
        service.get_record("A/RES/49/249")


def test_newer_resolutions_have_subjects_too(service):
    assert [r.identifier for r in service.search(query="IAEA").results] == ["A/RES/81/6"]
    assert service.get_record("A/RES/81/6").totals.abstain == 0  # left out of 996


def test_search_by_session_and_by_member(service):
    assert [r.identifier for r in service.search(session="11emsp").results] == ["A/RES/ES-11/1"]
    result = service.search(member="USA", body_id="UNGA")
    assert [(r.identifier, r.member_vote) for r in result.results] == [
        ("A/RES/81/6", "no"), ("A/RES/ES-11/1", "yes")]


# --- Security Council -------------------------------------------------------------


def test_security_council_permanent_members_are_marked(service):
    record = service.get_record("S/RES/2720")
    assert record.votes == {
        "yes": ["NETHERLANDS (KINGDOM OF THE) (NLD)", "TÜRKIYE (TUR)"],
        "abstain": ["UNITED STATES (USA, permanent member)"],
    }
    assert record.totals.model_dump() == dict(yes=2, no=0, abstain=1, non_voting=0, members=3)
    assert record.session is None
    assert record.details["subjects"] == ["MIDDLE EAST SITUATION", "PALESTINE QUESTION"]
    assert record.details["agenda_items"] == ["The situation in the Middle East, including the Palestinian question."]


@pytest.mark.parametrize("symbol", ["S/RES/2830 (2026)", "S/RES/2830(2026)", "s/res/2830"])
def test_a_symbol_with_a_space_is_normalised(service, symbol):
    assert service.get_record(symbol).identifier == "S/RES/2830(2026)"


def test_security_council_without_a_vote_from_the_archive(service):
    record = service.get_record("S/RES/331(1973)")
    assert record.adoption_method == "without a vote"
    assert record.votes is None  # the archive lists every member as 'X'
    assert record.totals.model_dump() == dict(yes=None, no=None, abstain=None, non_voting=None, members=3)
    assert record.note == "Adopted without vote"


# --- sources ----------------------------------------------------------------------


def test_answers_cite_the_archive_and_its_download_date(service):
    record = service.get_record("A/RES/ES-11/1")
    assert [s.title for s in record.sources] == [GA_TITLE]
    source = record.sources[0]
    assert source.citation == (
        f"United Nations Dag Hammarskjöld Library, {GA_TITLE}, United Nations, downloaded from {GA_URL}, 2026-10-27")
    assert source.url == GA_URL
    assert source.data_until == "2026-10-23"  # the newest resolution in the archive
    assert service.get_record("S/RES/331(1973)").sources[0].citation.endswith(
        "all_voting_data_security_council.xml.gz, 2026-11-03")


def test_member_profiles_use_the_archive_votes(service):
    member = service.get_member("United States", include_representatives=False)
    council = next(p for p in member.participation if p.body_id == "UNSC")
    assert council.labels == ["permanent member"] and council.recorded_votes == 3
    assert [s.title for s in member.sources] == ["United Nations Member States", GA_TITLE, SC_TITLE]
