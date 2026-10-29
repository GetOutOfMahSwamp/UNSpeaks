"""Tiny versions of the UN Library CSV files, with the real column names."""

from __future__ import annotations

import csv
from pathlib import Path

GA_OUT_COLS = ["undl_id", "resolution", "session", "date", "title", "modality", "draft", "committee_report",
               "meeting", "agenda_title", "subjects", "vote_note", "total_yes", "total_no",
               "total_abstentions", "total_non_voting", "total_ms", "undl_link"]
GA_VOTE_COLS = ["undl_id", "ms_code", "ms_name", "ms_vote", "date", "session", "resolution", "draft",
                "committee_report", "meeting", "title", "agenda_title", "subjects", "vote_note",
                "total_yes", "total_no", "total_abstentions", "total_non_voting", "total_ms", "undl_link"]
SC_COLS = ["undl_id", "ms_code", "ms_name", "permanent_member", "ms_vote", "date", "resolution", "draft",
           "meeting", "description", "agenda", "subjects", "vote_note", "total_yes", "total_no",
           "total_abstentions", "total_non_voting", "total_ms", "modality", "undl_link"]
UNMS_COLS = ["undl_id", "member_state", "name_status", "m49", "iso", "coverage_periods", "other_names",
             "earlier_names", "later_names", "geographic_term", "founding_member", "membership_resolution",
             "scope_note", "french", "spanish", "arabic", "chinese", "russian", "undl_link", "unms_ontology_link"]
AMB_COLS = ["undl_id", "name", "member state", "salutation", "alternative names", "notes", "undl_link"]


def _ga_res(undl, symbol, session, date, title, modality, totals=("", "", "", "", ""), subjects="", note=""):
    return dict(zip(GA_OUT_COLS, [undl, symbol, session, date, title, modality, "", "", f"A/{session}/PV.1",
                                  "Agenda item", subjects, note, *totals,
                                  f"https://digitallibrary.un.org/record/{undl}"]))


GA_RESOLUTIONS = [
    _ga_res("1", "A/RES/80/10", "80", "2025-10-20", "International Day of Indigenous Women", "Vote, recorded",
            ("2.0", "1.0", "0.0", "1.0", "4.0"), subjects="INDIGENOUS PEOPLES|WOMEN"),
    _ga_res("2", "A/RES/80/2", "80", "2025-09-30", "Protection of global climate", "Without a vote",
            subjects="CLIMATE"),
    _ga_res("3", "A/RES/62/223 A", "62", "2007-12-22", "Questions relating to weapons A", "Vote, recorded",
            ("3.0", "0.0", "1.0", "0.0", "4.0"), subjects="NUCLEAR WEAPONS"),
    _ga_res("4", "A/RES/62/223B", "62", "2007-12-22", "Questions relating to weapons B", "Vote, recorded",
            ("4.0", "0.0", "0.0", "0.0", "4.0"), subjects="NUCLEAR WEAPONS"),
    _ga_res("5", "A/RES/43/62", "43", "1988-12-07", "Old non-recorded vote", "Vote, non-recorded"),
]


def _ga_votes(undl, symbol, session, date, votes):
    rows = []
    for code, name, vote in votes:
        rows.append(dict(zip(GA_VOTE_COLS, [undl, code, name, vote, date, session, symbol] + [""] * 12
                             + [f"https://digitallibrary.un.org/record/{undl}"])))
    return rows


GA_VOTES = (
    _ga_votes("1", "A/RES/80/10", "80", "2025-10-20", [
        ("NLD", "NETHERLANDS (KINGDOM OF THE)", "Y"), ("USA", "UNITED STATES", "N"),
        ("TUR", "TÜRKIYE", "Y"), ("KOR", "REPUBLIC OF KOREA", "X")])
    + _ga_votes("3", "A/RES/62/223 A", "62", "2007-12-22", [
        ("NLD", "NETHERLANDS", "Y"), ("USA", "UNITED STATES", "A"),
        ("TUR", "TURKEY", "Y"), ("KOR", "REPUBLIC OF KOREA", "Y")])
    + _ga_votes("4", "A/RES/62/223B", "62", "2007-12-22", [
        ("NLD", "NETHERLANDS", "Y"), ("USA", "UNITED STATES", "Y"),
        ("TUR", "TURKEY", "Y"), ("KOR", "REPUBLIC OF KOREA", "Y")])
)


def _sc(undl, symbol, date, desc, modality, votes, note=""):
    totals = ["2", "0", "1", "0", "3"] if modality == "Vote" else ["0", "0", "0", "0", "3"]
    return [dict(zip(SC_COLS, [undl, code, name, perm, vote, date, symbol, "", "S/PV.1", desc, "Agenda",
                               "MIDDLE EAST SITUATION", note, *totals, modality,
                               f"https://digitallibrary.un.org/record/{undl}"]))
            for code, name, perm, vote in votes]


SC_VOTES = (
    _sc("10", "S/RES/2720(2023)", "2023-12-22", "Security Council resolution 2720 (2023) [on Gaza]", "Vote", [
        ("USA", "UNITED STATES", "True", "A"), ("NLD", "NETHERLANDS", "False", "Y"),
        ("TUR", "TÜRKIYE", "False", "Y")])
    + _sc("11", "S/RES/331(1973)", "1973-04-20", "Security Council resolution 331 (1973)", "Without Vote", [
        ("USA", "UNITED STATES", "True", "X"), ("NLD", "NETHERLANDS", "False", "X"),
        ("TUR", "TURKEY", "False", "X")], note="Adopted without vote")
)


def _ms(iso, name, status, other="", french="", **columns):
    row = dict.fromkeys(UNMS_COLS, "")
    row.update(iso=iso, member_state=name, name_status=status, other_names=other, french=french, **columns)
    return row


MEMBER_STATES = [
    _ms("NLD", "Netherlands", "fs", coverage_periods="1945-10-24:2023-03-02", m49="528",
        later_names="Netherlands (Kingdom of the)", founding_member="True",
        scope_note="The Kingdom of the Netherlands changed its short name from the Netherlands on 3 Mar. 2023"),
    _ms("NLD", "Netherlands (Kingdom of the)", "ms", "Kingdom of the Netherlands", "Pays-Bas (Royaume des)",
        coverage_periods="2023-03-03:", m49="528", earlier_names="Netherlands", founding_member="False",
        geographic_term="NETHERLANDS (KINGDOM OF THE)", undl_link="https://digitallibrary.un.org/record/4006039"),
    _ms("TUR", "Turkey", "fs", "Republic of Turkey", coverage_periods="1945-10-24:2022-05-25",
        later_names="Türkiye", founding_member="True"),
    _ms("TUR", "Türkiye", "ms", "Republic of Türkiye", coverage_periods="2022-05-26:", earlier_names="Turkey"),
    _ms("USA", "United States", "ms", "USA|U.S.A.|United States of America", coverage_periods="1945-10-24:",
        founding_member="True"),
    _ms("KOR", "Republic of Korea", "ms", "South Korea", coverage_periods="1991-09-17:",
        membership_resolution="A/RES/46/1"),
    _ms("PRK", "Democratic People's Republic of Korea", "ms", "North Korea", coverage_periods="1991-09-17:",
        membership_resolution="A/RES/46/1"),
]


def _amb(undl, name, member_states, salutation, other, notes):
    return dict(zip(AMB_COLS, [undl, name, member_states, salutation, other, notes,
                               f"https://digitallibrary.un.org/record/{undl}"]))


AMBASSADORS = [
    _amb("1252718", "Oosterom, Karel Jan Gustaaf van", "Netherlands", "Mr.", "Van Oosterom, Karel",
         "Ambassador|Security Council Representative|Security Council President (Mar. 2018)"),
    _amb("1320735", "Gregoire-Van-Haaren, Lise", "Netherlands|Netherlands (Kingdom of the)", "Ms.",
         "Van Haaren, Lise", "Ambassador"),
    _amb("1027012", "Moynihan, Daniel Patrick", "United States", "Mr.", "",
         "Ambassador|Security Council President (Feb. 1976)"),
    _amb("9", "Doe, Jane", "Atlantis", "Ms.", "", "Ambassador"),  # not a member: skipped
]

FILES = {
    "2026_02_06_ga_outcomes.csv": (GA_OUT_COLS, GA_RESOLUTIONS),
    "2026_02_06_ga_voting.csv": (GA_VOTE_COLS, GA_VOTES),
    "2026_02_06_sc_voting.csv": (SC_COLS, SC_VOTES),
    "2026_08_17_unms_names.csv": (UNMS_COLS, MEMBER_STATES),
    "2026_01_06_ambassadors.csv": (AMB_COLS, AMBASSADORS),
}


def write_raw_dir(folder: Path, extra: dict[str, list[dict]] | None = None) -> Path:
    """Write the tiny datasets; `extra` adds rows to some files, e.g. {file name: [rows]}."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, (columns, rows) in FILES.items():
        with open(folder / name, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows + (extra or {}).get(name, []))
    return folder
