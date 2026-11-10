"""Tiny versions of the Library's people datasets (Security Council representatives and
general debate speeches), with the real column and file names, and their description files.
The names are made up or public figures; the rows are not real records.

Together with the Permanent Representatives in votes_fixtures.py they cover:
- a person in two datasets (same record id): Moynihan, Van Oosterom
- a speech linked to a person's record by name and Member State: Van Kleffens; Sanders,
  whose record says 'Turkey' and whose speech says 'Türkiye' (the same member)
- the same name with another Member State, not linked: Jansen
- a speaker known only from speeches, with two speeches: Smit
- a speech for an observer: Parolin (Holy See)
- a duplicate row, a list written as text in Agenda Items, an unknown member (Atlantis)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

SC_REP_COLS = ["undl_id", "name", "member_states", "salutation", "alternative_names", "sc_president", "notes",
               "undl_link"]
SPEECH_COLS = ["", "Name", "Salutation", "Member State", "GA Session", "Meeting Date", "Meeting Symbol",
               "Agenda Items", "UNDL ID", "UNDL Link"]

SC_FILE = "2026_09_03_unms_sc_representatives.csv"
SPEECH_FILE = "GA_debate_speech_dataset_20260129.csv"  # the Library's own name: no date at the start
SPEECH_DOWNLOADED = datetime(2026, 9, 25, 12, 0)


def _sc(undl, name, member_states, salutation, other, president, notes):
    return dict(zip(SC_REP_COLS, [undl, name, member_states, salutation, other, president, notes,
                                  f"https://digitallibrary.un.org/record/{undl}"]))


SC_REPRESENTATIVES = [
    _sc("1027012", "Moynihan, Daniel Patrick", "United States", "Mr.", "Moynihan, Daniel Patrick, 1927-2003",
        "True", "Ambassador|Security Council Representative|Security Council President (Feb. 1976)"),
    _sc("1252718", "Oosterom, Karel Jan Gustaaf van", "Netherlands (Kingdom of the)", "Mr.",
        "Van Oosterom, Karel|Oosterom, Karel van", "True",
        "Security Council Representative|Security Council President (Mar. 2018)"),
    _sc("2000001", "Kleffens, Eelco Nicolaas van", "Netherlands", "Mr.", "", "False",
        "Security Council Representative|UNGA General Debate Speaker"),
    _sc("2000002", "Sanders, Ann", "Turkey", "Ms.", "", "False",
        "Security Council Representative|UNGA General Debate Speaker"),
    _sc("2000003", "Jansen, Pieter", "Netherlands", "Mr.", "", "False", "Security Council Representative"),
    _sc("2000004", "Byrne, Tom", "Atlantis", "Mr.", "", "False", "Security Council Representative"),  # skipped
]

def _speech(index, undl, name, salutation, member, session, day, symbol, agenda=None):
    agenda = agenda or f"UN. GENERAL ASSEMBLY (SESSION {session})--GENERAL DEBATE"
    return dict(zip(SPEECH_COLS, [str(index), name, salutation, member, session, day, symbol, agenda, undl,
                                  f"https://digitallibrary.un.org/record/{undl}"]))


TWO_ITEMS = ("['UN. GENERAL ASSEMBLY (79TH SESS. : 2024-2025)--GENERAL DEBATE', "
             "'UN. GENERAL ASSEMBLY (79TH SESS. : 2024-2025)--SPECIAL STATEMENTS']")
SPEECHES = [
    _speech(0, "500001", "Kleffens, Eelco Nicolaas van", "Mr.", "Netherlands", "3", "1948-09-25", "A/PV.140"),
    _speech(1, "500002", "Sanders, Ann", "Ms.", "Türkiye", "79", "2024-09-25", "A/79/PV.9", TWO_ITEMS),
    _speech(2, "500002", "Sanders, Ann", "Ms.", "Türkiye", "79", "2024-09-25", "A/79/PV.9", TWO_ITEMS),  # duplicate
    _speech(3, "500003", "Jansen, Pieter", "Mr.", "United States", "62", "2007-09-27", "A/62/PV.9"),
    _speech(4, "500004", "Parolin, Pietro", "Mr.", "Holy See", "79", "2024-09-28", "A/79/PV.17"),
    _speech(5, "500005", "Smit, Anna", "Ms.", "Netherlands", "79", "2024-09-26", "A/79/PV.12"),
    _speech(6, "500006", "Smit, Anna", "Ms.", "Netherlands", "78", "2023-09-23", "A/78/PV.10"),
]

SC_DESCRIPTION = """\
# United Nations Security Council representatives and presidents : description and terms of use

## Title

United Nations Security Council representatives and presidents

## Date of publication

03 Sep. 2026

## Version

Current version: 3 (03 Sep. 2026)
Dataset updated with new representatives

## Citation

United Nations Dag Hammarskjöld Library, United Nations Security Council representatives and presidents, \
United Nations, 2026, downloaded from https://digitallibrary.un.org/record/4047618, [download date]
"""

# With the errors of the real description: another dataset's title, a link without
# '/record/', 'Verison', and a publication date older than the speeches.
SPEECH_DESCRIPTION = """\
# UN\\_General debate speeches : description and terms of use

## Title

United Nations General debate speeches

## Date of publication

2024-01-25

## Citation

United Nations Dag Hammarskjöld Library, Security Council Representatives, United Nations, 2025, \
downloaded from https://digitallibrary.un.org/4067189, \\[download date]

## Version

Verison 3 (Jan. 2026)

Older versions: Version 1 (Nov. 2024), Version 2 (Sept. 2025)
"""


def write_people_files(folder: Path) -> Path:
    """Add the people datasets and their description files to a folder made by write_raw_dir."""
    for name, columns, rows in ((SC_FILE, SC_REP_COLS, SC_REPRESENTATIVES),
                                (SPEECH_FILE, SPEECH_COLS, SPEECHES)):
        with open(folder / name, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    (folder / "2026_09_03_unms_sc_representatives_1.md").write_text(SC_DESCRIPTION, encoding="utf-8")
    (folder / "2026_01_29_general_debate_speeches.md").write_text(SPEECH_DESCRIPTION, encoding="utf-8")
    stamp = SPEECH_DOWNLOADED.timestamp()
    os.utime(folder / SPEECH_FILE, (stamp, stamp))
    return folder
