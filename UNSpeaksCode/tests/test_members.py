"""Tests for get_member_state: member profiles, name history, related members,
participation in votes and Permanent Representatives.

They use the tiny datasets from votes_fixtures.py, plus a few extra rows for former
members (USSR, West Germany) and a representative of two members.
"""

from __future__ import annotations

import sqlite3

import pytest

from unspeaks.build_db import build
from unspeaks.sources.undl import _parse_date, read_source_info
from unspeaks.votes.service import VotingLookupError, VotingService, _year_ranges
from unspeaks.votes.store import DataNotLoadedError, VoteStore
from votes_fixtures import _amb, _ga_votes, _ms, write_raw_dir

EXTRA = {
    "2026_02_06_ga_voting.csv": (
        _ga_votes("20", "A/RES/45/1", "45", "1990-09-20", [
            ("SUN", "USSR", "Y"), ("GER", "GERMANY, FEDERAL REPUBLIC OF", "Y"), ("NLD", "NETHERLANDS", "Y")])
        + _ga_votes("21", "A/RES/47/1", "47", "1992-09-22", [
            ("RUS", "RUSSIAN FEDERATION", "N"), ("DEU", "GERMANY", "Y"), ("NLD", "NETHERLANDS", "Y"),
            ("PRK", "DEMOCRATIC PEOPLE'S REPUBLIC OF KOREA", "A")])
        + _ga_votes("1", "A/RES/80/10", "80", "2025-10-20", [("TLS", "TIMOR-LESTE", "Y")])
    ),
    "2026_08_17_unms_names.csv": [
        _ms("SUN", "USSR", "fs", "Soviet Union", coverage_periods="1945-10-24:1991-12-23",
            later_names="Russian Federation", founding_member="True"),
        _ms("RUS", "Russian Federation", "ms", "Russia", coverage_periods="1991-12-24:", earlier_names="USSR"),
        # The Member States dataset gives West Germany the code DEU; its votes use GER.
        _ms("DEU", "Germany, Federal Republic of", "fs", "Federal Republic of Germany|West Germany",
            coverage_periods="1973-09-18:1990-10-02", later_names="Germany"),
        _ms("DEU", "Germany", "ms", "Federal Republic of Germany", coverage_periods="1990-10-03:",
            earlier_names="Germany, Federal Republic of"),
        _ms("TLS", "Timor-Leste", "ms", coverage_periods="2002-09-27:", earlier_names="East Timor",
            membership_resolution="A/RES/57/3"),
    ],
    "2026_01_06_ambassadors.csv": [
        _amb("1068000", "Vorontsov, Yuli M.", "USSR|Russian Federation", "Mr.", "", "Ambassador"),
    ],
}


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    raw = write_raw_dir(tmp_path_factory.mktemp("raw"), extra=EXTRA)
    path = tmp_path_factory.mktemp("db") / "unspeaks.sqlite"
    build(raw, path, log=lambda message: None)
    return VotingService(VoteStore(path))


# --- who a member is ----------------------------------------------------------------


def test_profile_of_a_current_member(service):
    member = service.get_member("Netherlands")
    assert (member.code, member.name, member.status) == ("NLD", "Netherlands (Kingdom of the)", "current member")
    assert (member.member_since, member.member_until) == ("1945-10-24", None)
    assert [(n.name, n.current, n.periods) for n in member.names] == [
        ("Netherlands", False, ["1945-10-24 to 2023-03-02"]),
        ("Netherlands (Kingdom of the)", True, ["since 2023-03-03"]),
    ]
    assert "short name" in member.names[0].note
    assert member.related == []
    assert member.details["founding_member"] is True  # recorded on its earlier name only
    assert member.details["names_in_other_languages"] == {"fr": "Pays-Bas (Royaume des)"}
    assert member.details["thesaurus_term"] == "NETHERLANDS (KINGDOM OF THE)"
    assert member.record_url == "https://digitallibrary.un.org/record/4006039"
    assert [s.title for s in member.sources] == [
        "United Nations Member States", "General Assembly Voting Data", "Security Council Voting Data",
        "United Nations Permanent Representatives",
    ]


def test_found_by_a_former_name(service):
    member = service.get_member("Turkey")
    assert member.code == "TUR" and member.name == "Türkiye"
    assert member.names[0].periods == ["1945-10-24 to 2022-05-25"]


def test_admission_resolution(service):
    assert service.get_member("South Korea").details["membership_resolutions"] == ["A/RES/46/1"]


def test_names_from_before_membership_are_recognised(service):
    assert service.get_member("East Timor").code == "TLS"


def test_former_member_and_its_successor(service):
    ussr = service.get_member("Soviet Union")
    assert (ussr.code, ussr.status, ussr.member_until) == ("SUN", "former member", "1991-12-23")
    assert [(r.code, r.name, r.relation) for r in ussr.related] == [("RUS", "Russian Federation", "later")]
    russia = service.get_member("Russia")
    assert [(r.code, r.name, r.relation) for r in russia.related] == [("SUN", "USSR", "earlier")]
    assert russia.details["founding_member"] is False  # as recorded: the USSR was


def test_a_former_name_with_its_own_code_in_the_votes(service):
    west = service.get_member("West Germany")
    assert (west.code, west.name, west.status) == ("GER", "Germany, Federal Republic of", "former member")
    assert west.participation[0].names_used == ["GERMANY, FEDERAL REPUBLIC OF"]
    assert [(r.code, r.relation) for r in west.related] == [("DEU", "later")]
    germany = service.get_member("Germany")
    assert germany.code == "DEU" and [(r.code, r.relation) for r in germany.related] == [("GER", "earlier")]


def test_a_name_of_a_current_and_a_former_member_means_the_current_one(service):
    assert service.get_member("Federal Republic of Germany").code == "DEU"


def test_unknown_and_ambiguous_members(service):
    with pytest.raises(VotingLookupError, match="No member matches"):
        service.get_member("Atlantis")
    with pytest.raises(VotingLookupError, match="several members"):
        service.get_member("Korea")  # both Koreas


# --- participation in votes ---------------------------------------------------------


def test_participation_per_body(service):
    general_assembly, security_council = service.get_member("NLD").participation
    assert general_assembly.body_id == "UNGA" and general_assembly.recorded_votes == 5
    assert general_assembly.votes == {"yes": 5}
    assert general_assembly.years == ["1990", "1992", "2007", "2025"]
    assert (general_assembly.first_vote, general_assembly.last_vote) == ("1990-09-20", "2025-10-20")
    assert general_assembly.names_used == ["NETHERLANDS", "NETHERLANDS (KINGDOM OF THE)"]
    assert security_council.body == "United Nations Security Council"
    assert security_council.years == ["2023"]  # S/RES/331(1973) was adopted without a vote
    assert security_council.labels == []


def test_permanent_members_are_marked(service):
    security_council = service.get_member("USA").participation[1]
    assert security_council.labels == ["permanent member"]
    assert security_council.votes == {"abstain": 1}


def test_year_ranges():
    assert _year_ranges({1946, 1951, 1952, 1953, 2018}) == ["1946", "1951-1953", "2018"]
    assert _year_ranges(set()) == []


# --- representatives ----------------------------------------------------------------


def test_permanent_representatives(service):
    (group,) = service.get_member("Netherlands").representatives
    assert (group.role, group.total) == ("Permanent Representative", 2)
    assert "no dates" in group.note
    lise, karel = group.people  # alphabetical, not by date
    assert lise.name == "Gregoire-Van-Haaren, Lise" and lise.salutation == "Ms."
    assert lise.recorded_as == ["Netherlands", "Netherlands (Kingdom of the)"]
    assert karel.roles[-1] == "Security Council President (Mar. 2018)"
    assert karel.other_names == ["Van Oosterom, Karel"]
    assert karel.record_url == "https://digitallibrary.un.org/record/1252718"


def test_recorded_as_only_when_the_member_had_several_names(service):
    (moynihan,) = service.get_member("USA").representatives[0].people
    assert moynihan.recorded_as is None


def test_a_representative_of_two_members(service):
    for name in ("USSR", "Russian Federation"):
        people = service.get_member(name).representatives[0].people
        assert [person.name for person in people] == ["Vorontsov, Yuli M."]


def test_members_without_representatives(service):
    assert service.get_member("KOR").representatives == []


def test_representatives_can_be_left_out(service):
    member = service.get_member("NLD", include_representatives=False)
    assert member.representatives is None
    assert "United Nations Permanent Representatives" not in [s.title for s in member.sources]


# --- building -----------------------------------------------------------------------


def test_build_reports_what_it_skipped(tmp_path):
    messages: list[str] = []
    build(write_raw_dir(tmp_path / "raw"), tmp_path / "unspeaks.sqlite", log=messages.append)
    assert any("Atlantis" in message for message in messages)  # an unknown representative's country
    assert any("Democratic People's Republic of Korea" in message for message in messages)  # no votes


def test_old_database_asks_for_a_rebuild(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
                           "INSERT INTO meta VALUES ('schema_version', '2');")
    with pytest.raises(DataNotLoadedError, match="unspeaks-build-db"):
        VotingService(VoteStore(path)).get_member("Netherlands")


def test_description_file_found_by_its_title(tmp_path):
    csv_path = write_raw_dir(tmp_path) / "2026_08_17_unms_names.csv"
    (tmp_path / "2026_08_17_other_dataset.md").write_text("## Title\n\nSomething else\n", encoding="utf-8")
    (tmp_path / "2026_08_17_UN_member_states.md").write_text(
        "# United Nations Member States : description\n\n## Title\n\nUnited Nations Member States\n\n"
        "## Date of publication\n\n17 Aug. 2026\n\n## Version\n\nCurrent version: 6 (17 Aug. 2026)\n"
        "Replaced start_date/end_date\n\n## Citation\n\nUnited Nations Dag Hammarskjöld Library, United "
        "Nations Member States, United Nations, 2026, downloaded from "
        "https://digitallibrary.un.org/record/4082085, [download date]\n",
        encoding="utf-8",
    )
    info = read_source_info("unms_names", csv_path)
    assert info["version"] == "Version 6 (17 Aug. 2026)"
    assert info["published"] == "2026-08-17"
    assert info["citation"].startswith("United Nations Dag Hammarskjöld Library, United Nations Member States")


def test_a_wrong_record_in_the_citation_is_corrected(tmp_path):
    csv_path = write_raw_dir(tmp_path) / "2026_01_06_ambassadors.csv"
    (tmp_path / "2026_01_06_ambassadors_1.md").write_text(
        "## Date of publication\n\n2026-01-06\n\n## Citation\n\nUnited Nations Dag Hammarskjöld Library, "
        "Permanent Representatives, United Nations, 2026, downloaded from "
        "https://digitallibrary.un.org/4047618, \\[download date]\n",
        encoding="utf-8",
    )
    messages: list[str] = []
    info = read_source_info("ambassadors", csv_path, messages.append)
    assert "downloaded from https://digitallibrary.un.org/record/4091498, " in info["citation"]
    assert "4047618" not in info["citation"] and "[download date]" not in info["citation"]
    assert info["published"] == "2026-01-06"
    assert messages and "4047618" in messages[0]


@pytest.mark.parametrize("text, expected", [
    ("17 Aug. 2026", "2026-08-17"), ("03 Sep. 2026", "2026-09-03"), ("3 Sept. 2026", "2026-09-03"),
    ("2026-01-06", "2026-01-06"), ("sometime in 2026", None),
])
def test_parse_date(text, expected):
    assert _parse_date(text) == expected
