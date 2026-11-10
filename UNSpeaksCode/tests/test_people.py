"""Tests for search_people and the people datasets: Permanent Representatives, Security
Council representatives and presidents, and general debate speeches.

They use the tiny datasets from votes_fixtures.py and people_fixtures.py (see there for
what each made-up person tests).
"""

from __future__ import annotations

import sqlite3

import pytest
from mcp import Client

from people_fixtures import SPEECH_FILE, write_people_files
from unspeaks import server
from unspeaks.build_db import build
from unspeaks.sources.undl import _list_text, find_description, find_file, read_source_info
from unspeaks.votes.service import VotingLookupError, VotingService
from unspeaks.votes.store import DataNotLoadedError, VoteStore
from votes_fixtures import write_raw_dir

SPEECHES_TITLE = "United Nations General debate speeches"
SC_TITLE = "United Nations Security Council representatives and presidents"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    raw = write_people_files(write_raw_dir(tmp_path_factory.mktemp("raw")))
    path = tmp_path_factory.mktemp("db") / "unspeaks.sqlite"
    messages: list[str] = []
    summary = build(raw, path, log=messages.append)
    return VotingService(VoteStore(path)), summary, messages


@pytest.fixture
def service(built):
    return built[0]


def _names(result):
    return [person.name for person in result.people]


# --- building -----------------------------------------------------------------------


def test_build_loads_the_people_datasets(built):
    _, summary, messages = built
    assert (summary["representatives"], summary["sc_representatives"], summary["speeches"]) == (3, 5, 6)
    assert any("Skipped 1 duplicate rows" in message for message in messages)
    assert any("Linked 2 of 6 speeches" in message for message in messages)
    assert any("Jansen, Pieter (United States)" in message for message in messages)  # not linked
    assert any("Holy See (1)" in message for message in messages)  # kept, not a member
    assert any("Atlantis" in message for message in messages)  # an unknown member: skipped


def test_the_speeches_file_keeps_the_library_name(tmp_path):
    for name in ("GA_debate_speech_dataset_20250901.csv", SPEECH_FILE, "2025_10_01_general_debate_speeches.csv"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert find_file(tmp_path, "general_debate_speeches").name == SPEECH_FILE  # the newest date
    (tmp_path / "2026_01_29_other.md").write_text("## Title\n\nSomething else\n", encoding="utf-8")
    (tmp_path / "2026_01_29_general_debate_speeches.md").write_text(
        f"## Title\n\n{SPEECHES_TITLE}\n", encoding="utf-8")
    found = find_description(tmp_path / SPEECH_FILE, SPEECHES_TITLE)
    assert found.name == "2026_01_29_general_debate_speeches.md"  # same date, same title


def test_the_wrong_citation_of_the_speeches_is_corrected(tmp_path):
    raw = write_people_files(write_raw_dir(tmp_path))
    messages: list[str] = []
    info = read_source_info("general_debate_speeches", raw / SPEECH_FILE, messages.append)
    assert info["citation"] == (
        "United Nations Dag Hammarskjöld Library, United Nations General debate speeches, United Nations, "
        "2025, downloaded from https://digitallibrary.un.org/record/4067189, 2026-09-25")
    assert info["version"] == "Version 3 (Jan. 2026)"
    assert len(messages) == 3  # 'Verison', the link and the title
    assert any("Security Council Representatives" in message for message in messages)


def test_speeches_are_as_recent_as_the_newest_speech(service):
    (source,) = [s for s in service.search_people(name="Parolin").sources if s.title == SPEECHES_TITLE]
    assert source.data_until == "2024-09-28"  # not the description's publication date, 2024-01-25
    assert source.version == "Version 3 (Jan. 2026)"
    assert "record/4067189, 2026-09-25" in source.citation


def test_list_text():
    assert _list_text("['A', 'B']") == ["A", "B"]
    assert _list_text("A|B") == ["A", "B"]
    assert _list_text("[not a list") == ["[not a list"]
    assert _list_text("") is None


# --- the three kinds of questions from the README ------------------------------------


def test_who_spoke_for_a_member_in_a_session(service):
    result = service.search_people(member="Netherlands", session="79")
    assert result.member == "Netherlands (Kingdom of the) (NLD)"
    (smit,) = result.people
    assert (smit.name, smit.salutation, smit.record_url) == ("Smit, Anna", "Ms.", None)
    (speech,) = smit.roles
    assert (speech.role, speech.member, speech.code, speech.session, speech.date, speech.document) == (
        "General debate speaker", "Netherlands", "NLD", "79", "2024-09-26", "A/79/PV.12")
    assert speech.record_url == "https://digitallibrary.un.org/record/500005"
    assert speech.matched_by is None
    assert smit.roles_not_shown == 1  # the speech in session 78
    assert "sessions 3 to 79" in result.roles[0].note
    assert [s.title for s in result.sources] == ["United Nations Member States", SPEECHES_TITLE]


def test_a_person_found_by_name_in_any_order_and_without_accents(service):
    for name in ("Daniel Patrick Moynihan", "moynihan daniel", "MOYNIHAN"):
        assert _names(service.search_people(name=name)) == ["Moynihan, Daniel Patrick"]
    assert _names(service.search_people(name="Karel van Oosterom")) == ["Oosterom, Karel Jan Gustaaf van"]


def test_a_person_in_both_datasets_is_one_person(service):
    (moynihan,) = service.search_people(name="Moynihan").people
    assert [(r.role, r.code, r.matched_by) for r in moynihan.roles] == [
        ("Permanent Representative", "USA", None),
        ("Security Council representative", "USA", None),
        ("Security Council president", "USA", None),
    ]
    assert moynihan.functions == [
        "Ambassador", "Security Council President (Feb. 1976)", "Security Council Representative"]
    assert moynihan.other_names == ["Moynihan, Daniel Patrick, 1927-2003"]
    assert moynihan.record_url == "https://digitallibrary.un.org/record/1027012"


def test_security_council_representatives_of_a_member(service):
    result = service.search_people(member="Netherlands", role="Security Council representative")
    assert _names(result) == ["Jansen, Pieter", "Kleffens, Eelco Nicolaas van", "Oosterom, Karel Jan Gustaaf van"]
    oosterom = result.people[2]
    assert oosterom.roles[0].member == "Netherlands (Kingdom of the)"  # as recorded
    assert oosterom.roles_not_shown == 2  # Permanent Representative, president
    assert [s.title for s in result.sources] == ["United Nations Member States", SC_TITLE]


def test_security_council_presidents(service):
    result = service.search_people(role="security council president")  # any case
    assert _names(result) == ["Moynihan, Daniel Patrick", "Oosterom, Karel Jan Gustaaf van"]


# --- linking speeches to people -------------------------------------------------------


def test_a_speech_is_linked_by_name_and_member(service):
    (kleffens,) = service.search_people(name="Kleffens").people
    assert [(r.role, r.matched_by) for r in kleffens.roles] == [
        ("Security Council representative", None), ("General debate speaker", "name and Member State")]
    assert kleffens.record_url == "https://digitallibrary.un.org/record/2000001"


def test_a_former_name_of_the_same_member_still_links(service):
    (sanders,) = service.search_people(name="Ann Sanders").people
    record, speech = sanders.roles
    assert (record.member, speech.member, record.code, speech.code) == ("Turkey", "Türkiye", "TUR", "TUR")
    assert speech.matched_by == "name and Member State"
    assert speech.details == {"agenda_items": [
        "UN. GENERAL ASSEMBLY (79TH SESS. : 2024-2025)--GENERAL DEBATE",
        "UN. GENERAL ASSEMBLY (79TH SESS. : 2024-2025)--SPECIAL STATEMENTS"]}


def test_the_same_name_for_another_member_is_not_linked(service):
    speaker, record = service.search_people(name="Pieter Jansen").people  # speakers first
    assert [(r.role, r.code) for r in speaker.roles] == [("General debate speaker", "USA")]
    assert speaker.record_url is None and speaker.roles[0].matched_by is None
    assert [(r.role, r.code) for r in record.roles] == [("Security Council representative", "NLD")]


def test_speeches_of_one_speaker_are_one_person(service):
    (smit,) = service.search_people(name="Smit").people
    assert [r.session for r in smit.roles] == ["79", "78"]  # newest first


def test_duplicate_rows_are_left_out(service):
    (sanders,) = service.search_people(name="Sanders", role="General debate speaker").people
    assert len(sanders.roles) == 1


def test_speeches_for_observers_are_kept(service):
    result = service.search_people(member="Holy See")
    assert "not a member in the data" in result.member
    (parolin,) = result.people
    assert (parolin.roles[0].member, parolin.roles[0].code) == ("Holy See", None)
    assert "Parolin, Pietro" in _names(service.search_people(session="79"))


# --- ordering, paging, notes and errors ---------------------------------------------


def test_speakers_newest_first_then_others_by_name(service):
    result = service.search_people(member="Netherlands")
    assert _names(result) == [
        "Smit, Anna", "Kleffens, Eelco Nicolaas van", "Gregoire-Van-Haaren, Lise", "Jansen, Pieter",
        "Oosterom, Karel Jan Gustaaf van"]


def test_paging(service):
    first = service.search_people(member="Netherlands", limit=2)
    second = service.search_people(member="Netherlands", limit=2, page=3)
    assert (first.total, first.has_more, len(first.people)) == (5, True, 2)
    assert (second.has_more, _names(second)) == (False, ["Oosterom, Karel Jan Gustaaf van"])


def test_never_presented_as_current(service):
    result = service.search_people(name="Moynihan")
    assert "never present anyone as the current holder" in result.note
    assert all("no dates" in role.note or "does not say who" in role.note for role in result.roles)


def test_nobody_found_still_says_what_was_searched(service):
    result = service.search_people(member="Netherlands", session="80")
    assert result.total == 0 and "Nobody found" in result.note
    assert SPEECHES_TITLE in [s.title for s in result.sources]
    assert any("sessions 3 to 79" in (role.note or "") for role in result.roles)


@pytest.mark.parametrize("arguments, message", [
    ({}, "at least one"),
    ({"role": "Ambassador"}, "Unknown role"),
    ({"member": "Atlantis"}, "No member matches"),
    ({"name": "-- --"}, "letter or digit"),
])
def test_errors(service, arguments, message):
    with pytest.raises(VotingLookupError, match=message):
        service.search_people(**arguments)


def test_old_database_asks_for_a_rebuild(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
                           "INSERT INTO meta VALUES ('schema_version', '3');")
    for call in (lambda s: s.search_people(name="Moynihan"), lambda s: s.get_member("Netherlands")):
        with pytest.raises(DataNotLoadedError, match="unspeaks-build-db"):
            call(VotingService(VoteStore(path)))


# --- get_member_state ---------------------------------------------------------------


def test_member_state_lists_its_permanent_representatives_and_counts_the_others(service):
    member = service.get_member("Netherlands")
    (group,) = member.representatives
    assert group.role == "Permanent Representative"
    assert [p.name for p in group.people] == ["Gregoire-Van-Haaren, Lise", "Oosterom, Karel Jan Gustaaf van"]
    assert group.people[1].roles == [  # its functions in the Permanent Representatives dataset
        "Ambassador", "Security Council Representative", "Security Council President (Mar. 2018)"]
    assert [(c.role, c.people, c.entries) for c in member.other_people] == [
        ("Security Council representative", 3, 3), ("Security Council president", 1, 1),
        ("General debate speaker", 2, 3)]
    assert [s.title for s in member.sources][-2:] == [SC_TITLE, SPEECHES_TITLE]
    assert service.get_member("NLD", include_representatives=False).other_people is None


def test_without_the_people_datasets_only_their_roles_are_missing(tmp_path):
    path = tmp_path / "unspeaks.sqlite"
    build(write_raw_dir(tmp_path / "raw"), path, log=lambda message: None)
    service = VotingService(VoteStore(path))
    assert service.get_member("Netherlands").other_people == []
    assert _names(service.search_people(name="Moynihan")) == ["Moynihan, Daniel Patrick"]
    with pytest.raises(VotingLookupError, match="roles in the data are: Permanent Representative\\."):
        service.search_people(role="General debate speaker")


# --- the MCP tool -------------------------------------------------------------------


@pytest.fixture
def people_server(service):
    server.set_voting(service)
    yield
    server.set_voting(None)


@pytest.mark.anyio
async def test_search_people_tool(people_server):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        found = await client.call_tool("search_people", {"member": "Netherlands", "session": "79"})
        nothing = await client.call_tool("search_people", {})
        bad_session = await client.call_tool("search_people", {"session": "79th"})
    tool = tools["search_people"]
    assert "who holds it now" in tool.description and "never present anyone" in tool.description
    assert tool.input_schema.get("required", []) == []
    assert tool.annotations.read_only_hint is True and tool.output_schema is not None
    assert found.is_error is False
    data = found.structured_content
    assert data["people"][0]["roles"][0]["document"] == "A/79/PV.12"
    assert data["sources"][-1]["citation"].endswith("record/4067189, 2026-09-25")
    assert nothing.is_error is True and "at least one" in nothing.content[0].text
    assert bad_session.is_error is True
