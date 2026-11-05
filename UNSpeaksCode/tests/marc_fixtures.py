"""Tiny versions of the Library's weekly MARCXML voting archives.

Based on real records (symbols, dates and field layout), trimmed to the four members of
votes_fixtures.py. The fields are explained in sources/undl.py.
"""

from __future__ import annotations

import gzip
import os
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

GA_ARCHIVE = "all_voting_data_general_assembly.xml"
SC_ARCHIVE = "all_voting_data_security_council.xml"
GA_DOWNLOADED = datetime(2026, 10, 27, 12, 0)  # set as the file's modification date
SC_DOWNLOADED = datetime(2026, 11, 3, 12, 0)


def field(tag, *subfields, ind1=" ", ind2=" "):
    """A data field, e.g. field('791', ('a', 'A/RES/80/2'), ('c', '80'))."""
    return tag, ind1, ind2, subfields


def vote(number, code, name, value=None, seat=None):
    """One member's vote (967). Without a value the member did not vote: like the archive,
    the field then has no $d at all. `seat`: 'P' or 'R' in the Security Council."""
    subfields = [("a", number)] + ([("b", seat)] if seat else []) + [("c", code)]
    subfields += [("d", value)] if value else []
    return field("967", *subfields, ("e", name))


def record(record_id, *fields):
    lines = ["<record>", f'  <controlfield tag="001">{record_id}</controlfield>']
    for tag, ind1, ind2, subfields in fields:
        lines.append(f"  <datafield tag={quoteattr(tag)} ind1={quoteattr(ind1)} ind2={quoteattr(ind2)}>")
        lines += [f"    <subfield code={quoteattr(code)}>{escape(value)}</subfield>" for code, value in subfields]
        lines.append("  </datafield>")
    lines.append("</record>")
    return "\n".join(lines)


def collection(records):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<collection xmlns="http://www.loc.gov/MARC21/slim">\n' + "\n".join(records) + "\n</collection>\n")


GA_TITLE = (("b", "resolution /"), ("c", "adopted by the General Assembly"))

GA_RECORDS = [
    # A recorded vote. Korea did not vote (no $d), and 996 leaves out the 'no' count ($c): 0.
    record("3959039",
           field("245", ("a", "Aggression against Ukraine :"), *GA_TITLE, ind1="1", ind2="0"),
           field("269", ("a", "2022-03-02")),
           field("590", ("a", "Vote")),
           field("591", ("a", "RECORDED - No machine generated vote")),
           field("791", ("a", "A/RES/ES-11/1"), ("b", "A/"), ("c", "11emsp"), ("0", "(DHLAUTH)926991")),
           field("793", ("a", "PLENARY MEETING")),
           field("952", ("a", "A/ES-11/PV.5")),
           vote("1", "KOR", "REPUBLIC OF KOREA"),
           vote("2", "NLD", "NETHERLANDS", "Y"),
           vote("3", "TUR", "TURKEY", "A"),
           vote("4", "USA", "UNITED STATES", "Y"),
           field("991", ("a", "A/ES-11/2"), ("b", "5"),
                 ("c", "Letter dated 28 February 2014 from the Permanent Representative of Ukraine (S/2014/136)."),
                 ("d", "UKRAINE--POLITICAL CONDITIONS"), ("0", "(DHLAUTH)926990"), ind1="1"),
           field("992", ("a", "2022-03-02")),
           field("993", ("a", "A/ES-11/L.1"), ind1="2"),
           field("993", ("a", "A/ES-11/L.1/Add.1"), ind1="2"),
           field("996", ("b", "2"), ("d", "1"), ("e", "1"), ("f", "4"))),
    # A non-recorded vote: 'Vote' but no 967 fields. The totals are known.
    record("281405",
           field("245", ("a", "Implementation of General Assembly resolution 42/25 :"), *GA_TITLE, ind1="1", ind2="0"),
           field("269", ("a", "1988-12-07")),
           field("590", ("a", "Vote")),
           field("591", ("a", "NON-RECORDED based on A/43/PV.73 and voting Sheet No. 261, Meeting No. 73")),
           field("791", ("a", "A/RES/43/62"), ("b", "A/"), ("c", "43")),
           field("952", ("a", "A/43/PV.73")),
           field("991", ("a", "A/43/251"), ("b", "51"),
                 ("c", "Treaty for the Prohibition of Nuclear Weapons in Latin America."), ind1="1"),
           field("992", ("a", "1988-12-07")),
           field("993", ("a", "A/43/830"), ind1="3"),
           field("996", ("b", "149"), ("d", "5"), ("e", "5"), ("f", "159"))),
    # Adopted without a vote.
    record("4091270",
           field("245", ("a", "Scale of assessments for the apportionment of the expenses of the United Nations :"),
                 *GA_TITLE),
           field("269", ("a", "2025-10-14")),
           field("590", ("a", "Without Vote")),
           field("591", ("a", "ADOPTED WITHOUT VOTE")),
           field("791", ("a", "A/RES/80/2"), ("b", "A/"), ("c", "80")),
           field("952", ("a", "A/80/PV.18")),
           field("991", ("a", "A/80/251"), ("b", "140"),
                 ("c", "Scale of assessments for the apportionment of the expenses of the United Nations."),
                 ("d", "UN--BUDGET CONTRIBUTIONS"), ind1="1"),
           field("992", ("a", "2025-10-14")),
           field("993", ("a", "A/C.5/80/L.2"), ind1="2"),
           field("993", ("a", "A/80/401"), ind1="3")),
    # Part A of a divided resolution (a second 791 with $z), with two different dates.
    record("284058",
           field("245", ("a", "Administrative and budgetary aspects of the financing of the United Nations "
                              "peace-keeping operations :"), *GA_TITLE, ind1="1", ind2="0"),
           field("269", ("a", "1993-10-13")),
           field("590", ("a", "Without Vote")),
           field("591", ("a", "ADOPTED WITHOUT VOTE")),
           field("791", ("a", "A/RES/49/249A"), ("b", "A/"), ("c", "49")),
           field("791", ("z", "A/RES/49/249"), ("b", "***")),
           field("952", ("a", "A/49/PV.106")),
           field("992", ("a", "1995-07-20")),
           field("993", ("a", "A/49/947/Add.1"), ind1="3")),
    # A new record: no 269, and 996 leaves out the abstentions ($d): 0.
    record("4131011",
           field("245", ("a", "Report of the International Atomic Energy Agency :"), *GA_TITLE),
           field("590", ("a", "Vote")),
           field("791", ("a", "A/RES/81/6"), ("b", "A/"), ("c", "81")),
           field("952", ("a", "A/81/PV.25")),
           vote("1", "KOR", "REPUBLIC OF KOREA"),
           vote("2", "NLD", "NETHERLANDS (KINGDOM OF THE)", "Y"),
           vote("3", "TUR", "TÜRKIYE", "Y"),
           vote("4", "USA", "UNITED STATES", "N"),
           field("991", ("a", "A/81/251"), ("b", "91"), ("c", "Report of the International Atomic Energy Agency."),
                 ("d", "IAEA--REPORTS"), ind1="1"),
           field("992", ("a", "2026-10-23")),
           field("993", ("a", "A/81/L.7"), ind1="2"),
           field("996", ("b", "2"), ("c", "1"), ("e", "1"), ("f", "4"))),
]

SC_RECORDS = [
    # A recorded vote, with permanent (P) and elected (R) members and zero-padded totals.
    record("4031215",
           field("245", ("a", "Security Council resolution 2720 (2023) [on delivery of humanitarian relief "
                              "and appointment of a Senior Humanitarian Coordinator for Gaza]"), ind1="1", ind2="0"),
           field("269", ("a", "2023-12-22")),
           field("590", ("a", "Vote")),
           field("791", ("a", "S/RES/2720(2023)"), ("b", "S/"), ("c", "78")),
           field("952", ("a", "S/PV.9520")),
           vote("001", "NLD", "NETHERLANDS (KINGDOM OF THE)", "Y", seat="R"),
           vote("002", "TUR", "TÜRKIYE", "Y", seat="R"),
           vote("003", "USA", "UNITED STATES", "A", seat="P"),
           field("991", ("a", "S/78"), ("b", "[54]"), ("d", "MIDDLE EAST SITUATION"), ind1="3"),
           field("991", ("a", "S/78"), ("b", "[50]"), ("d", "PALESTINE QUESTION"), ind1="3"),
           field("991", ("a", "S/"), ("b", "X"),
                 ("c", "The situation in the Middle East, including the Palestinian question."), ind1="3"),
           field("992", ("a", "2023-12-22")),
           field("993", ("a", "S/2023/1029"), ind1="2"),
           field("996", ("b", "002"), ("c", "000"), ("d", "001"), ("e", "000"), ("f", "003"))),
    # Adopted without a vote: every member is 'X', and 996 $a has a remark.
    record("280314",
           field("245", ("a", "Security Council resolution 331 (1973) [on submitting a report on the situation "
                              "in the Middle East]"), ind1="1", ind2="0"),
           field("269", ("a", "1973-04-20")),
           field("590", ("a", "Without Vote")),
           field("591", ("a", "ADOPTED WITHOUT VOTE")),
           field("791", ("a", "S/RES/331(1973)"), ("b", "S/"), ("c", "28")),
           field("952", ("a", "S/PV.1710")),
           vote("001", "NLD", "NETHERLANDS", "X", seat="R"),
           vote("002", "TUR", "TURKEY", "X", seat="R"),
           vote("003", "USA", "UNITED STATES", "X", seat="P"),
           field("991", ("a", "S/"), ("b", "X"), ("c", "The situation in the Middle East."), ind1="3"),
           field("992", ("a", "1973-04-20")),
           field("993", ("a", "S/10918"), ind1="2"),
           field("996", ("a", "Adopted without vote"), ("b", "000"), ("c", "000"), ("d", "000"), ("e", "003"),
                 ("f", "003"))),
    # A symbol with a space, in a new record without 269.
    record("4130454",
           field("245", ("a", "Security Council resolution 2830 (2026) [on extension of the mandate of the "
                              "UN Panel of Experts on the Sudan until 11 Jan. 2027]")),
           field("590", ("a", "Vote")),
           field("791", ("a", "S/RES/2830 (2026)"), ("b", "S/"), ("c", "81")),
           field("952", ("a", "S/PV.10235")),
           vote("001", "NLD", "NETHERLANDS (KINGDOM OF THE)", "Y", seat="R"),
           vote("002", "TUR", "TÜRKIYE", "Y", seat="R"),
           vote("003", "USA", "UNITED STATES", "Y", seat="P"),
           field("991", ("a", "S/81"), ("b", "[160]"), ("d", "SUDAN--POLITICAL CONDITIONS"), ind1="3"),
           field("992", ("a", "2026-10-08")),
           field("993", ("a", "S/2026/788"), ind1="2"),
           field("996", ("b", "003"), ("c", "000"), ("d", "000"), ("e", "000"), ("f", "003"))),
    # 269 gives only the month: that is not a different date.
    record("491520",
           field("245", ("a", "Security Council resolution 1470 (2003) [on extension of the mandate of the "
                              "UN Mission in Sierra Leone]"), ind1="1", ind2="0"),
           field("269", ("a", "2003-03")),
           field("590", ("a", "Vote")),
           field("791", ("a", "S/RES/1470(2003)"), ("b", "S/"), ("c", "57")),
           field("952", ("a", "S/PV.4728")),
           vote("001", "NLD", "NETHERLANDS", "Y", seat="R"),
           vote("002", "TUR", "TURKEY", "Y", seat="R"),
           vote("003", "USA", "UNITED STATES", "Y", seat="P"),
           field("991", ("a", "S/57"), ("b", "[97]"), ("d", "SIERRA LEONE SITUATION"), ind1="3"),
           field("992", ("a", "2003-03-28")),
           field("996", ("b", "003"), ("c", "000"), ("d", "000"), ("e", "000"), ("f", "003"))),
]


def write_archives(folder: Path, *, ga: bool = True, sc: bool = True, gz: bool = False) -> Path:
    """Write the archives into folder (unzipped, or as downloaded with gz=True), with the
    modification dates of their downloads."""
    folder.mkdir(parents=True, exist_ok=True)
    for wanted, name, records, downloaded in ((ga, GA_ARCHIVE, GA_RECORDS, GA_DOWNLOADED),
                                              (sc, SC_ARCHIVE, SC_RECORDS, SC_DOWNLOADED)):
        if not wanted:
            continue
        data = collection(records).encode("utf-8")
        path = folder / (f"{name}.gz" if gz else name)
        path.write_bytes(gzip.compress(data, mtime=0) if gz else data)
        os.utime(path, (downloaded.timestamp(), downloaded.timestamp()))
    return folder
