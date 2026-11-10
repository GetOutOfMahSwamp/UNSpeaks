"""Loader for the UN Dag Hammarskjöld Library's voting data and datasets.

Reads the files you downloaded by hand into data/raw/ (we never download them
automatically: see the README, "Terms of use").

Voting data. For each body the Library's weekly MARCXML archive is used when it is in
data/raw/ (unzipped or still as .xml.gz); otherwise its CSV datasets:
- all_voting_data_general_assembly.xml  General Assembly: one record per resolution,
                                        with every Member State's vote for recorded votes
- all_voting_data_security_council.xml  Security Council: the same
- *_ga_outcomes.csv  General Assembly resolutions (one row per resolution,
                     including those adopted without a vote)
- *_ga_voting.csv    General Assembly voting data (one row per Member State per vote)
- *_sc_voting.csv    Security Council voting data (one row per member per resolution)

Members and people (always CSV datasets):
- *_unms_names.csv   UN Member States, all their names, with dates and codes: used for
                     get_member_state, and to recognise a country however it's written
                     ('Netherlands', 'Pays-Bas', 'NLD', ...)
- *_ambassadors.csv  Permanent Representatives: heads of the Member States' missions
- *_unms_sc_representatives.csv
                     Security Council representatives and presidents
- GA_debate_speech_dataset_YYYYMMDD.csv (the Library's name; *_general_debate_speeches.csv
                     also works)  General Assembly general debate: one row per speech

For each CSV dataset the newest file is used; file names start with their date, e.g.
2026_02_06_ga_voting.csv, or end with it, e.g. GA_debate_speech_dataset_20260129.csv. The
Library's description files (saved next to the CSVs, see find_description) are read for the
version, the publication date and the exact citation.
The archives keep the Library's file names, so their download date for the citation is
the file's modification date. When you download newer files, rebuild the database and the
citations update automatically.
"""

from __future__ import annotations

import ast
import csv
import gzip
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

from unspeaks.votes.store import VoteWriter, normalize_name

PUBLISHER = "United Nations Dag Hammarskjöld Library"
TERMS = (
    "Copyright United Nations. Non-commercial use with attribution. Provided as is. "
    "https://digitallibrary.un.org/pages/?ln=en&page=tos"
)

GA, SC = "UNGA", "UNSC"

BODIES = {
    GA: dict(
        name="United Nations General Assembly",
        member_term="Member State",
        notes=(
            "Covers resolutions adopted by the General Assembly in its regular, special and "
            "emergency special sessions. Most resolutions are adopted without a vote; for those "
            "there are no individual votes, which reflects how they were adopted, not missing data. "
            "Individual votes exist only for resolutions adopted by recorded vote; for a "
            "non-recorded vote there are at most the totals. Drafts that "
            "were not adopted and votes on separate paragraphs are not included. 'non_voting' "
            "means the Member State was recorded as not voting (for example because it was absent)."
        ),
    ),
    SC: dict(
        name="United Nations Security Council",
        member_term="Council member",
        notes=(
            "Covers resolutions adopted by the Security Council. Drafts that were not adopted, "
            "including vetoed drafts, are not included. Permanent members are marked. A few "
            "resolutions were adopted without a vote; for those there are no individual votes. "
            "'non_voting' means the member did not participate in the vote (for example because "
            "it was absent)."
        ),
    ),
}


@dataclass(frozen=True)
class Dataset:
    kind: str
    title: str
    record_url: str
    # The Library's own file name, when it doesn't start with a date (the date is at its end).
    library_glob: str | None = None


DATASETS = {
    "ga_outcomes": Dataset("ga_outcomes", "General Assembly resolutions", "https://digitallibrary.un.org/record/4060945"),
    "ga_voting": Dataset("ga_voting", "General Assembly Voting Data", "https://digitallibrary.un.org/record/4060887"),
    "sc_voting": Dataset("sc_voting", "Security Council Voting Data", "https://digitallibrary.un.org/record/4055387"),
    "unms_names": Dataset("unms_names", "United Nations Member States", "https://digitallibrary.un.org/record/4082085"),
    "ambassadors": Dataset("ambassadors", "United Nations Permanent Representatives", "https://digitallibrary.un.org/record/4091498"),
    "sc_representatives": Dataset("sc_representatives", "United Nations Security Council representatives and presidents",
                                  "https://digitallibrary.un.org/record/4047618"),
    "general_debate_speeches": Dataset("general_debate_speeches", "United Nations General debate speeches",
                                       "https://digitallibrary.un.org/record/4067189",
                                       library_glob="GA_debate_speech_dataset_*.csv"),
}


@dataclass(frozen=True)
class Archive:
    """A weekly MARCXML export of the Library's voting records for one body."""

    body_id: str
    title: str
    file_name: str  # as unzipped; the download itself has '.gz' added
    url: str  # where to download it by hand (bot protection: never automatically)
    replaces: tuple[str, ...]  # the CSV datasets it replaces


EXPORT_URL = "https://digitallibrary.un.org/export/marcxml/"
ARCHIVES = {
    "ga_marcxml": Archive(GA, "General Assembly voting data (weekly MARCXML export)",
                          "all_voting_data_general_assembly.xml",
                          EXPORT_URL + "all_voting_data_general_assembly.xml.gz", ("ga_outcomes", "ga_voting")),
    "sc_marcxml": Archive(SC, "Security Council voting data (weekly MARCXML export)",
                          "all_voting_data_security_council.xml",
                          EXPORT_URL + "all_voting_data_security_council.xml.gz", ("sc_voting",)),
}
RECORD_URL = "https://digitallibrary.un.org/record/{}"

VOTES = {"Y": "yes", "N": "no", "A": "abstain", "X": "non_voting"}
GA_METHODS = {
    "vote, recorded": "recorded vote",
    "vote, non-recorded": "non-recorded vote",
    "without a vote": "without a vote",
}
SC_METHODS = {"vote": "recorded vote", "without vote": "without a vote"}

BATCH = 50_000


def find_file(raw_dir: Path, kind: str) -> Path | None:
    """The newest file for a dataset, e.g. 2026_02_06_ga_voting.csv (names start with a date),
    or under the Library's own name if it has one, e.g. GA_debate_speech_dataset_20260129.csv."""
    folder = Path(raw_dir)
    candidates = set(folder.glob(f"*_{kind}.csv"))
    if DATASETS[kind].library_glob:
        candidates.update(folder.glob(DATASETS[kind].library_glob))
    return max(candidates, key=lambda path: (_file_date(path) or "", path.name)) if candidates else None


def _file_date(path: Path) -> str | None:
    """The date in a file name as 'YYYY_MM_DD': at its start (2026_02_06_ga_voting.csv) or
    at its end (GA_debate_speech_dataset_20260129.csv)."""
    match = re.match(r"(\d{4})_(\d{2})_(\d{2})_", path.stem) or re.search(r"_(\d{4})(\d{2})(\d{2})$", path.stem)
    return "_".join(match.groups()) if match else None


def find_description(csv_path: Path, title: str) -> Path | None:
    """The Library's description file, saved next to the CSV. Its name varies:
    '<csv name>_md.md', '<csv name>_1.md', or a name of its own with the same date, such as
    2026_08_17_UN_member_states.md for 2026_08_17_unms_names.csv, or
    2026_01_29_general_debate_speeches.md for GA_debate_speech_dataset_20260129.csv. In that
    last case the title inside the file must be the dataset's title."""
    folder, stem = csv_path.parent, csv_path.stem
    if (folder / f"{stem}_md.md").exists():
        return folder / f"{stem}_md.md"
    named = sorted(folder.glob(f"{stem}_*.md"))
    if named:
        return named[0]
    day = _file_date(csv_path)
    for candidate in sorted(folder.glob(f"{day}_*.md")) if day else []:
        sections = _markdown_sections(candidate.read_text(encoding="utf-8-sig"))
        if [line.lower() for line in sections.get("title", [])[:1]] == [title.lower()]:
            return candidate
    return None


def read_source_info(kind: str, csv_path: Path, log: Callable[[str], None] = lambda message: None) -> dict:
    """Title, version, publication date and citation, read from the Library's description
    file if present."""
    dataset = DATASETS[kind]
    downloaded_on = date.fromtimestamp(csv_path.stat().st_mtime).isoformat()
    info = dict(title=dataset.title, version=None, record_url=dataset.record_url, citation=None,
                published=None)

    md_path = find_description(csv_path, dataset.title)
    if md_path:
        sections = _markdown_sections(md_path.read_text(encoding="utf-8-sig"))
        if sections.get("version"):  # e.g. 'Current version: 6 (17 Aug. 2026)'
            version = sections["version"][0]
            # The speeches description misspells it: 'Verison 3 (Jan. 2026)'.
            word = re.match(r"(?:current\s+)?(ver(?:si|is)on)\b:?\s*", version, flags=re.I)
            if word:
                if word.group(1).lower() != "version":
                    log(f"  {md_path.name}: read '{word.group(1)}' in its version as 'Version'.")
                version = "Version " + version[word.end():]
            info["version"] = version
        if sections.get("date of publication"):
            info["published"] = _parse_date(sections["date of publication"][0])
        if sections.get("citation"):
            info["citation"] = _correct_citation(
                re.sub(r"\\?\[download date\\?\]", downloaded_on, sections["citation"][0]),
                dataset, md_path.name, log)

    if not info["citation"]:
        version = f", {info['version']}" if info["version"] else ""
        info["citation"] = (
            f"{PUBLISHER}, {info['title']}, United Nations{version}, "
            f"downloaded from {info['record_url']}, {downloaded_on}"
        )
    info["downloaded_on"] = downloaded_on
    return info


def _correct_citation(citation: str, dataset: Dataset, file_name: str, log: Callable[[str], None]) -> str:
    """Correct what is demonstrably wrong in a description's citation, and say so in the log:
    - a link to another record: the Permanent Representatives description cites record 4047618,
      which is the Security Council representatives dataset;
    - a link without '/record/': the speeches description links https://digitallibrary.un.org/4067189;
    - the title of another dataset: the speeches description cites 'Security Council Representatives'.
    The rest (such as the year) is kept as written."""
    url = re.search(r"https://digitallibrary\.un\.org/(?:record/)?\d+", citation)
    if url and url.group(0) != dataset.record_url:
        log(f"  {file_name} cites {url.group(0)}; citing {dataset.record_url} instead.")
        citation = citation.replace(url.group(0), dataset.record_url)
    # 'United Nations Dag Hammarskjöld Library, <title>, United Nations, ...'
    title = re.match(r"(.*?Library,\s*)([^,]+?)(\s*,\s*United Nations\b)", citation)
    if title and _plain_title(title.group(2)) != _plain_title(dataset.title):
        log(f"  {file_name} cites the title '{title.group(2)}'; citing '{dataset.title}' instead.")
        citation = title.group(1) + dataset.title + citation[title.end(2):]
    return citation


def _plain_title(title: str) -> str:
    """'United Nations Permanent Representatives' and 'Permanent Representatives' are the same title."""
    return re.sub(r"^united nations\s+", "", normalize_name(title))


def find_archive(raw_dir: Path, archive: Archive) -> Path | None:
    """The archive under its own name, unzipped (.xml) or as downloaded (.xml.gz). If both
    are there, the one modified last."""
    folder = Path(raw_dir)
    candidates = [path for path in (folder / archive.file_name, folder / f"{archive.file_name}.gz")
                  if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def archive_source_info(archive: Archive, path: Path) -> dict:
    """Title and citation of an archive. The Library accepts the archive's link plus the
    download date, which is the file's modification date (its name has no date)."""
    downloaded_on = date.fromtimestamp(path.stat().st_mtime).isoformat()
    return dict(
        title=archive.title,
        citation=f"{PUBLISHER}, {archive.title}, United Nations, downloaded from {archive.url}, {downloaded_on}",
        record_url=archive.url,
        downloaded_on=downloaded_on,
    )


class _Names:
    """Collects every name seen for each member code, and the most recent one."""

    def __init__(self) -> None:
        self.all: dict[str, set[str]] = {}
        self.latest: dict[str, tuple[str, str]] = {}  # code -> (date, name)

    def add(self, code: str, name: str, when: str) -> None:
        self.all.setdefault(code, set()).add(name)
        if code not in self.latest or when >= self.latest[code][0]:
            self.latest[code] = (when, name)


def load(writer: VoteWriter, raw_dir: Path, log: Callable[[str], None] = lambda message: None) -> dict:
    """Load every UN dataset found in raw_dir. Returns counts per dataset.

    The voting data of each body comes from its weekly archive if that is in raw_dir, and
    otherwise from its CSV datasets, so the General Assembly can come from the archive while
    the Security Council still comes from a CSV."""
    raw_dir = Path(raw_dir)
    summary: dict[str, int] = {}
    files = {kind: find_file(raw_dir, kind) for kind in DATASETS}
    archives = {kind: find_archive(raw_dir, archive) for kind, archive in ARCHIVES.items()}
    for kind, path in archives.items():
        for replaced in ARCHIVES[kind].replaces if path else ():
            if files[replaced]:
                log(f"Not using {files[replaced].name}: {path.name} replaces it.")
                files[replaced] = None

    for kind, path in archives.items():
        if path:
            info = archive_source_info(ARCHIVES[kind], path)
            writer.add_source(
                f"undl:{kind}", title=info["title"], citation=info["citation"], publisher=PUBLISHER,
                record_url=info["record_url"], file_name=path.name, downloaded_on=info["downloaded_on"],
                terms=TERMS,
            )
    for kind, path in files.items():
        if path:
            info = read_source_info(kind, path, log)
            writer.add_source(
                f"undl:{kind}", title=info["title"], citation=info["citation"], publisher=PUBLISHER,
                version=info["version"], record_url=info["record_url"], file_name=path.name,
                downloaded_on=info["downloaded_on"], terms=TERMS, data_until=info["published"],
            )

    names = _Names()
    if archives["ga_marcxml"]:
        writer.add_body(GA, **BODIES[GA])
        log(f"Reading {archives['ga_marcxml'].name} (large file, this takes a little while) ...")
        summary["ga_resolutions"], summary["ga_votes"] = _load_archive(
            writer, archives["ga_marcxml"], GA, "undl:ga_marcxml", names, log)
    elif files["ga_outcomes"] or files["ga_voting"]:
        writer.add_body(GA, **BODIES[GA])
        decision_ids: dict[str, int] = {}
        if files["ga_outcomes"]:
            log(f"Reading {files['ga_outcomes'].name} ...")
            summary["ga_resolutions"] = _load_ga_resolutions(writer, files["ga_outcomes"], decision_ids)
        if files["ga_voting"]:
            log(f"Reading {files['ga_voting'].name} (large file, this takes a little while) ...")
            summary["ga_votes"] = _load_ga_votes(writer, files["ga_voting"], decision_ids, names)

    if archives["sc_marcxml"]:
        writer.add_body(SC, **BODIES[SC])
        log(f"Reading {archives['sc_marcxml'].name} ...")
        summary["sc_resolutions"], summary["sc_votes"] = _load_archive(
            writer, archives["sc_marcxml"], SC, "undl:sc_marcxml", names, log)
    elif files["sc_voting"]:
        writer.add_body(SC, **BODIES[SC])
        log(f"Reading {files['sc_voting'].name} ...")
        summary["sc_resolutions"], summary["sc_votes"] = _load_sc(writer, files["sc_voting"], names)

    if names.all:
        aliases = _load_members(writer, names, files["unms_names"], log)
        summary["members"] = len(names.all)
        summary.update(_load_people(writer, files, aliases, log))
    return summary


# --- General Assembly ------------------------------------------------------------


def _ga_decision(writer: VoteWriter, row: dict, source_id: str, method: str | None) -> int:
    agenda = _split(row.get("agenda_title"))
    subjects = _split(row.get("subjects"))
    recorded = method == "recorded vote"
    return writer.add_decision(
        body_id=GA,
        identifier=row["resolution"].strip(),
        title=_clean_ga_title(row.get("title")),
        date=row.get("date") or None,
        session=row.get("session") or None,
        adoption_method=method,
        outcome="adopted",  # the dataset only contains adopted resolutions
        totals=_totals(row) if recorded else (None,) * 5,
        note=row.get("vote_note") or None,
        details={
            "undl_id": row.get("undl_id"),
            "draft": _split(row.get("draft")),
            "committee_report": _split(row.get("committee_report")),
            "meeting": _split(row.get("meeting")),
            "agenda_items": agenda,
            "subjects": subjects,
        },
        keywords=" ".join((agenda or []) + (subjects or [])),
        record_url=row.get("undl_link") or None,
        source_id=source_id,
    )


def _load_ga_resolutions(writer: VoteWriter, path: Path, decision_ids: dict[str, int]) -> int:
    count = 0
    for row in _rows(path):
        method = GA_METHODS.get((row.get("modality") or "").strip().lower())
        decision_ids[row["undl_id"]] = _ga_decision(writer, row, "undl:ga_outcomes", method)
        count += 1
    return count


def _load_ga_votes(writer: VoteWriter, path: Path, decision_ids: dict[str, int], names: _Names) -> int:
    count = 0
    batch: list[tuple] = []
    voted: set[int] = set()
    for row in _rows(path):
        decision_id = decision_ids.get(row["undl_id"])
        if decision_id is None:  # not in the resolutions file (e.g. a newer voting file)
            decision_id = _ga_decision(writer, row, "undl:ga_voting", "recorded vote")
            decision_ids[row["undl_id"]] = decision_id
        voted.add(decision_id)
        code, name = row["ms_code"].strip(), row["ms_name"].strip()
        names.add(code, name, row.get("date") or "")
        raw = row["ms_vote"].strip().upper()
        batch.append((decision_id, writer.member_id(GA, code, name), VOTES.get(raw, "non_voting"), raw, None))
        if len(batch) >= BATCH:
            writer.add_votes(batch)
            count += len(batch)
            batch.clear()
    writer.add_votes(batch)
    count += len(batch)
    writer.set_votes_source(voted, "undl:ga_voting")
    return count


def _clean_ga_title(title: str | None) -> str | None:
    """'Question of X : resolution / adopted by the General Assembly' -> 'Question of X'."""
    if not title:
        return None
    # The suffix has typos in places (':P resolution / adopted by the General Assemly'),
    # so match loosely.
    cleaned = re.sub(
        r"\s*(?::\s*[A-Za-z]?\s*)?\bresolutions?\s*/\s*adopted\b.*$",  # library catalogue suffix
        "", title.strip(), flags=re.IGNORECASE,
    )
    return cleaned or title.strip()


# --- Security Council ---------------------------------------------------------------


def _load_sc(writer: VoteWriter, path: Path, names: _Names) -> tuple[int, int]:
    decision_ids: dict[str, int] = {}
    without_vote: set[int] = set()
    batch: list[tuple] = []
    for row in _rows(path):
        code, name = row["ms_code"].strip(), row["ms_name"].strip()
        names.add(code, name, row.get("date") or "")
        decision_id = decision_ids.get(row["undl_id"])
        if decision_id is None:
            method = SC_METHODS.get((row.get("modality") or "").strip().lower())
            agenda = _split(row.get("agenda"))
            subjects = _split(row.get("subjects"))
            totals = _totals(row)
            decision_id = writer.add_decision(
                body_id=SC,
                identifier=row["resolution"].strip(),
                title=(row.get("description") or "").strip() or None,
                date=row.get("date") or None,
                adoption_method=method,
                outcome="adopted",
                # Without a vote the file has 0 yes / 0 no; keep only the number of members.
                totals=(None, None, None, None, totals[4]) if method == "without a vote" else totals,
                note=row.get("vote_note") or None,
                details={
                    "undl_id": row.get("undl_id"),
                    "draft": _split(row.get("draft")),
                    "meeting": _split(row.get("meeting")),
                    "agenda_items": agenda,
                    "subjects": subjects,
                },
                keywords=" ".join((agenda or []) + (subjects or [])),
                record_url=row.get("undl_link") or None,
                source_id="undl:sc_voting",
                votes_source_id="undl:sc_voting",
            )
            decision_ids[row["undl_id"]] = decision_id
            if method == "without a vote":
                without_vote.add(decision_id)
        if decision_id in without_vote:
            continue  # nobody voted; the file lists every member as 'X'
        raw = row["ms_vote"].strip().upper()
        label = "permanent member" if row.get("permanent_member", "").strip().lower() == "true" else None
        batch.append((decision_id, writer.member_id(SC, code, name), VOTES.get(raw, "non_voting"), raw, label))
    writer.add_votes(batch)
    return len(decision_ids), len(batch)


# --- Weekly MARCXML archives (General Assembly and Security Council) ----------------
#
# One MARC record per adopted resolution. The fields used were checked against the CSV
# datasets, which were made from the same records:
#   001      record id: https://digitallibrary.un.org/record/<id>
#   791      $a resolution symbol; $c General Assembly session ('80', '10emsp', '29sp');
#            $z on divided resolutions: the symbol before division (A/RES/38/35 for 38/35A)
#   245      title
#   992 $a   date. 269 $a is the same date in nearly every record, but not in all, and
#            newer records lack it; when it differs, details.date_note gives both.
#   590 $a   'Vote' or 'Without Vote'. A vote without 967 fields is a non-recorded vote.
#   967      one field per member: $c code, $e name, $d Y / N / A / X (blank: not voting);
#            Security Council: $b P = permanent member, R = elected member
#   996      totals: $b yes, $c no, $d abstentions, $e not voting, $f members ('013' in
#            the Security Council; a missing count is 0); $a a remark on the vote
#   952 $a   meeting record
#   993 $a   documents. General Assembly: first indicator 2 = draft, 3 = committee report;
#            Security Council: all drafts
#   991      agenda: $c the item's title, $d its subject
# Field 591 (free text about the vote) is not used, and neither is the nearly empty 650.

GA_DOCUMENTS = {"2": "draft", "3": "committee_report"}  # 993, first indicator
ARCHIVE_METHODS = {"vote": "recorded vote", "without vote": "without a vote"}  # 590 $a


class _MarcRecord:
    """One MARC record: its id (field 001) and its data fields,
    {tag: [(indicator 1, indicator 2, [(subfield code, value), ...]), ...]}."""

    __slots__ = ("id", "fields")

    def __init__(self, record_id: str | None, fields: dict[str, list[tuple[str, str, list[tuple[str, str]]]]]):
        self.id = record_id
        self.fields = fields

    def subfields(self, tag: str) -> Iterator[tuple[str, str]]:
        for _, _, subfields in self.fields.get(tag, []):
            yield from subfields

    def values(self, tag: str, code: str) -> list[str]:
        """Every non-empty value of one subfield, e.g. values('991', 'd') -> all subjects."""
        return [value.strip() for c, value in self.subfields(tag) if c == code and value.strip()]

    def first(self, tag: str, code: str) -> str | None:
        values = self.values(tag, code)
        return values[0] if values else None


def _marc_records(path: Path) -> Iterator[_MarcRecord]:
    """The records of a MARCXML file (.xml or .xml.gz), read one at a time, so the General
    Assembly archive (about 300 MB) needs little memory."""
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    try:
        with opener(path, "rb") as file:
            events = ET.iterparse(file, events=("start", "end"))
            _, root = next(events)
            for event, element in events:
                if event != "end" or _local_name(element.tag) != "record":
                    continue
                record_id, fields = None, {}
                for field in element:
                    kind, tag = _local_name(field.tag), field.get("tag")
                    if kind == "controlfield" and tag == "001":
                        record_id = (field.text or "").strip() or None
                    elif kind == "datafield":
                        fields.setdefault(tag, []).append((
                            field.get("ind1") or " ", field.get("ind2") or " ",
                            [(subfield.get("code"), subfield.text or "") for subfield in field],
                        ))
                yield _MarcRecord(record_id, fields)
                root.clear()  # forget the records already read
    except (ET.ParseError, OSError, EOFError, StopIteration) as exc:
        raise ValueError(
            f"{path.name} is not a complete MARCXML file ({exc}). Download it again by hand."
        ) from exc


def _local_name(tag: str) -> str:
    """'{http://www.loc.gov/MARC21/slim}record' -> 'record'"""
    return tag.rpartition("}")[2]


def _load_archive(writer: VoteWriter, path: Path, body_id: str, source_id: str, names: _Names,
                  log: Callable[[str], None]) -> tuple[int, int]:
    """One decision per record and, for recorded votes, one vote per member. Returns the
    number of decisions and of votes."""
    decisions = votes = 0
    skipped: list[str] = []
    batch: list[tuple] = []
    for record in _marc_records(path):
        if not record.first("791", "a"):
            skipped.append(record.id or "(no id)")
            continue
        decision = _archive_decision(record, body_id)
        # Without a vote the Security Council records list every member as 'X': nobody voted.
        members = [] if decision["adoption_method"] == "without a vote" else record.fields.get("967", [])
        decision_id = writer.add_decision(**decision, source_id=source_id,
                                          votes_source_id=source_id if members else None)
        decisions += 1
        for _, _, subfields in members:
            member = dict(subfields)
            code = (member.get("c") or "").strip()
            if not code:
                continue
            name = (member.get("e") or "").strip() or code
            names.add(code, name, decision["date"] or "")
            raw = (member.get("d") or "").strip().upper()
            label = "permanent member" if body_id == SC and (member.get("b") or "").strip() == "P" else None
            batch.append((decision_id, writer.member_id(body_id, code, name),
                          VOTES.get(raw, "non_voting"), raw or None, label))
        if len(batch) >= BATCH:
            writer.add_votes(batch)
            votes += len(batch)
            batch.clear()
    writer.add_votes(batch)
    votes += len(batch)
    if skipped:
        log(f"  Skipped {len(skipped)} records without a resolution symbol (791 $a): "
            + ", ".join(skipped[:10]) + (" ..." if len(skipped) > 10 else ""))
    return decisions, votes


def _archive_decision(record: _MarcRecord, body_id: str) -> dict:
    """The decision in one archive record, as arguments for VoteWriter.add_decision."""
    symbol = record.first("791", "a")
    # 'S/RES/2830 (2026)' -> 'S/RES/2830(2026)', like every other Security Council symbol;
    # General Assembly symbols keep their space, as in the CSV ('A/RES/62/223 A').
    identifier = re.sub(r"\s+", "", symbol) if body_id == SC else " ".join(symbol.split())
    method = ARCHIVE_METHODS.get((record.first("590", "a") or "").lower())
    if method == "recorded vote" and "967" not in record.fields:
        method = "non-recorded vote"

    title = " ".join(" ".join(value for code, value in record.subfields("245") if code in "abc").split())
    if body_id == GA:
        title = _clean_ga_title(title)

    vote_date, other_date = record.first("992", "a"), record.first("269", "a")
    date_note = None
    if vote_date and other_date and not vote_date.startswith(other_date):  # '2003-03' fits '2003-03-28'
        date_note = (
            f"The Library's record gives two dates: {vote_date} (field 992, shown as `date`) and "
            f"{other_date} (field 269). Check the meeting record if the exact day matters."
        )

    documents: dict[str, list[str]] = {"draft": [], "committee_report": []}
    for ind1, _, subfields in record.fields.get("993", []):
        kind = GA_DOCUMENTS.get(ind1) if body_id == GA else "draft"
        if kind:
            documents[kind] += [value.strip() for code, value in subfields if code == "a" and value.strip()]

    agenda = list(dict.fromkeys(record.values("991", "c")))
    subjects = list(dict.fromkeys(record.values("991", "d")))
    other_symbols = record.values("791", "z")
    return dict(
        body_id=body_id,
        identifier=identifier,
        title=title or None,
        date=vote_date or other_date,
        session=record.first("791", "c") if body_id == GA else None,
        adoption_method=method,
        outcome="adopted",  # the archives only contain adopted resolutions
        totals=_archive_totals(record, method),
        note=" ".join(record.values("996", "a")) or None,
        details={
            "undl_id": record.id,
            "draft": documents["draft"],
            "committee_report": documents["committee_report"],
            "meeting": record.values("952", "a"),
            "agenda_items": agenda,
            "subjects": subjects,
            "other_symbols": other_symbols,
            "date_note": date_note,
        },
        keywords=" ".join(agenda + subjects + other_symbols),
        record_url=RECORD_URL.format(record.id) if record.id else None,
    )


def _archive_totals(record: _MarcRecord, method: str | None) -> tuple:
    """(yes, no, abstain, non_voting, members) from field 996. A count that is left out is 0
    (the other counts add up to the number of members)."""
    counts = {code: _int(value) for code, value in record.subfields("996") if code in "bcdef"}
    if all(count is None for count in counts.values()):
        return (None,) * 5
    if method == "without a vote":  # the record says 0 yes, 0 no: keep only the number of members
        return (None, None, None, None, counts.get("f"))
    return tuple(counts.get(code) or 0 for code in "bcde") + (counts.get("f"),)


# --- Members ------------------------------------------------------------------------

PR_ROLE = "Permanent Representative"
PR_NOTES = (
    "Current and past heads of the Permanent Mission to the United Nations in New York, from the "
    "Library's Permanent Representatives dataset. The dataset has no dates, so it does not say who "
    "is in office now. Some roles carry a date (e.g. 'Security Council President (Mar. 2018)'), and "
    "`recorded_as` shows which of the member's names a person served under (see `names` for when "
    "each name was used). Early heads of mission had other titles; the Library marks them all "
    "'Ambassador'. The current head of mission is listed in the UN Protocol and Liaison Service's "
    "'Blue Book' of Permanent Missions."
)
LANGUAGES = (("fr", "french"), ("es", "spanish"), ("ar", "arabic"), ("zh", "chinese"), ("ru", "russian"))


class _Aliases:
    """Every name that refers to a member, with a priority. When a name fits several members,
    the lowest priority wins: 0 = the code itself, 1 = a name used in its votes, 2 = another
    name of a current member, 3 = another name of a former member, 4 = a name it had before
    or after ('East Timor', 'Transjordan'; often another member's name). So 'USSR' means the
    USSR, not the Russian Federation, and 'Federal Republic of Germany' today's Germany, not
    West Germany."""

    def __init__(self) -> None:
        self.by_code: dict[str, dict[str, int]] = {}  # code -> {name: priority}
        self._by_key: dict[str, dict[str, int]] = {}  # normalised name -> {code: priority}

    def add(self, code: str, names, priority: int) -> None:
        self._by_key.setdefault(normalize_name(code), {})[code] = 0
        known = self.by_code.setdefault(code, {})
        for name in names:
            name = (name or "").strip()
            key = normalize_name(name)
            if not key:
                continue
            known[name] = min(priority, known.get(name, priority))
            codes = self._by_key.setdefault(key, {})
            codes[code] = min(priority, codes.get(code, priority))

    def codes(self, name: str | None, max_priority: int = 3) -> set[str]:
        """All members this name could refer to."""
        codes = self._by_key.get(normalize_name(name or ""), {})
        return {code for code, priority in codes.items() if priority <= max_priority}

    def resolve(self, name: str | None) -> str | None:
        """The member a name refers to; None if it is unknown or ambiguous."""
        codes = self._by_key.get(normalize_name(name or ""))
        if not codes:
            return None
        best = min(codes.values())
        matches = [code for code, priority in codes.items() if priority == best]
        return matches[0] if len(matches) == 1 else None

    def write(self, writer: VoteWriter) -> None:
        for code, names in self.by_code.items():
            for priority in sorted(set(names.values())):  # the most important names first
                writer.add_member_aliases(code, [n for n, p in names.items() if p == priority], priority)


def _load_members(writer: VoteWriter, names: _Names, member_states: Path | None,
                  log: Callable[[str], None]) -> _Aliases:
    """A profile for every member that appears in the votes, and the names to recognise it by.

    With the Member States dataset, the profile also gets the name history, membership
    dates, codes and the members it came from or became (USSR -> Russian Federation).
    Every UN Member State, current or former, has voted in the General Assembly, so
    taking the members from the votes leaves none out.
    """
    aliases = _Aliases()
    for code, used in names.all.items():
        aliases.add(code, used, priority=1)

    rows: dict[str, list[dict]] = {code: [] for code in names.all}
    if member_states:
        log(f"Reading {member_states.name} ...")
        skipped = []
        for row in _rows(member_states):
            code = _code_for_row(row, aliases)
            if code:
                rows[code].append(row)
            else:
                skipped.append(row["member_state"])
        if skipped:
            log("  Not in the voting data (skipped): " + ", ".join(skipped))
        writer.add_meta("member_names_source", "undl:unms_names")

    profiles = {code: _profile(code, member_rows, names) for code, member_rows in rows.items()}
    for code, member_rows in rows.items():
        other = set()
        for row in member_rows:
            for column in ("member_state", "french", "spanish", "geographic_term"):
                other.add(row.get(column) or "")
            other.update(_split(row.get("other_names")) or [])
        aliases.add(code, other, priority=3 if profiles[code].get("is_current") is False else 2)
        for row in member_rows:
            aliases.add(code, (_split(row.get("earlier_names")) or []) + (_split(row.get("later_names")) or []), 4)

    display = {code: profile["name"] for code, profile in profiles.items()}
    for code, profile in profiles.items():
        writer.add_member_profile(code, related=_related(code, rows[code], aliases, display), **profile)
    aliases.write(writer)
    return aliases


def _code_for_row(row: dict, aliases: _Aliases) -> str | None:
    """Which member in the votes a row of the Member States dataset describes.

    Usually the row's ISO code, but the votes sometimes use another code for a former
    name: 'Germany, Federal Republic of' is DEU in the Member States dataset and GER in
    the votes, 'Upper Volta' is HVO there and BFA in the votes. So the name as used in
    the votes decides first, then the code.
    """
    iso = (row.get("iso") or "").strip()
    voted = iso in aliases.by_code
    by_name = aliases.codes(row.get("member_state"), max_priority=1)
    if iso in by_name or (voted and not by_name):
        return iso
    if len(by_name) == 1:
        return next(iter(by_name))
    return iso if voted else None


def _profile(code: str, rows: list[dict], names: _Names) -> dict:
    """The profile of one member, from its rows in the Member States dataset."""
    if not rows:
        return dict(name=names.latest[code][1])  # the name in its most recent vote

    history = sorted(
        (dict(name=row["member_state"].strip(),
              current=(row.get("name_status") or "").strip() == "ms",
              periods=_periods(row.get("coverage_periods")),
              note=" ".join(_split(row.get("scope_note")) or []) or None,
              record_url=row.get("undl_link") or None)
         for row in rows),
        key=lambda entry: min((start or "" for start, _ in entry["periods"]), default=""),
    )
    starts = [start for entry in history for start, _ in entry["periods"] if start]
    ends = [end for entry in history for _, end in entry["periods"]]
    is_current = any(entry["current"] for entry in history) or None in ends
    main = next((r for r in rows if (r.get("name_status") or "").strip() == "ms"), None) \
        or max(rows, key=_last_day)

    resolutions, other_names = [], []
    for row in sorted(rows, key=_last_day):
        if row.get("membership_resolution") and row["membership_resolution"] not in resolutions:
            resolutions.append(row["membership_resolution"].strip())
        for name in _split(row.get("other_names")) or []:
            if name not in other_names and all(name != entry["name"] for entry in history):
                other_names.append(name)

    return dict(
        name=main["member_state"].strip(),
        is_current=is_current,
        member_since=min(starts) if starts else None,
        member_until=None if is_current or not ends else max(end for end in ends if end),
        names=history,
        details={
            "iso_code": main.get("iso"),
            "m49_code": main.get("m49"),
            # On any of its names: the Netherlands is marked on 'Netherlands', not on its current name.
            "founding_member": any((r.get("founding_member") or "").strip().lower() == "true" for r in rows)
            if "founding_member" in rows[0] else None,  # the column is new in version 6
            "membership_resolutions": resolutions,
            "names_in_other_languages": {lang: main[column].strip()
                                         for lang, column in LANGUAGES if (main.get(column) or "").strip()},
            "other_names": other_names,
            "thesaurus_term": main.get("geographic_term"),
            "ontology_url": main.get("unms_ontology_link"),
        },
        record_url=main.get("undl_link") or None,
        source_id="undl:unms_names",
    )


def _related(code: str, rows: list[dict], aliases: _Aliases, display: dict[str, str]) -> list[dict]:
    """Members this one came from or became, e.g. USSR -> Russian Federation. The member's
    own earlier and later names (Turkey -> Türkiye) are not included: they are in `names`."""
    related: dict[tuple[str, str], dict] = {}
    for row in rows:
        for relation, column in (("earlier", "earlier_names"), ("later", "later_names")):
            for name in _split(row.get(column)) or []:
                other = aliases.resolve(name)
                if other and other != code and (other, relation) not in related:
                    related[(other, relation)] = dict(
                        code=other, name=display[other], relation=relation,
                        via=name if name != display[other] else None,
                    )
    return list(related.values())


# --- People: Permanent Representatives, Security Council, general debate --------------
#
# The Permanent Representatives and Security Council datasets have one row per person, with
# the person's record id (undl_id): a person in both is one person. The speeches dataset has
# one row per speech, with the speech's record id and the speaker's name, but no person id.
# A speech is linked to a person's record only when the name is exactly the same AND the
# Member State is the same member (Syria and Syrian Arab Republic are: same code). Otherwise
# the speaker is listed under the name as recorded, once per Member State.

SC_ROLE = "Security Council representative"
SC_NOTES = (
    "Representatives of Member States on the Security Council, from the Library's 'Security Council "
    "representatives and presidents' dataset. The dataset has no dates, so it does not say when someone "
    "sat on the Council, or who represents a member there now. Some functions carry a date (e.g. "
    "'Security Council President (Feb. 1976)'). The member's name is as given in the person's record, "
    "sometimes a former name ('Byelorussian SSR'). get_member_state shows the years a member had a seat."
)
SC_PRESIDENT_ROLE = "Security Council president"
SC_PRESIDENT_NOTES = (
    "People who presided over the Security Council, from the Library's 'Security Council representatives "
    "and presidents' dataset. The presidency rotates among the Council's members every month; the months a "
    "person presided are in their `functions`, e.g. 'Security Council President (Feb. 1976)'. The dataset "
    "does not say who presides now."
)
SPEAKER_ROLE = "General debate speaker"
SPEAKER_NOTES = (
    "Speeches in the General Assembly's general debate, sessions {first} to {last} ({start} to {end}), one "
    "entry per speech, from the Library's 'General debate speeches' dataset; later sessions are not in it. "
    "Each speech has its own record (`record_url`) and the symbol of the meeting record it is in "
    "(`document`; read it with get_document). The dataset has no person ids: a speech is linked to a "
    "person's record only when the name and the Member State are the same (`matched_by`). Otherwise the "
    "speaker is listed under the name as recorded, once per Member State, so one name can appear more than "
    "once. Entries without `code` are for delegations that are not Member States in the data, such as "
    "observers."
)
MATCHED_BY_NAME = "name and Member State"


@dataclass
class _Person:
    name: str
    salutation: str | None = None
    other_names: list[str] = field(default_factory=list)
    record_url: str | None = None
    roles: list[dict] = field(default_factory=list)  # arguments for VoteWriter.add_person_role

    def add_names(self, names) -> None:
        for name in names:
            if name and name != self.name and name not in self.other_names:
                self.other_names.append(name)


def _load_people(writer: VoteWriter, files: dict[str, Path | None], aliases: _Aliases,
                 log: Callable[[str], None]) -> dict:
    """Everyone in the people datasets that are in raw_dir. Returns counts per dataset."""
    summary: dict[str, int] = {}
    people: dict[str, _Person] = {}  # 'record:<id>' for a person's record, 'speaker:...' otherwise
    unknown: set[str] = set()
    if files["ambassadors"]:
        log(f"Reading {files['ambassadors'].name} ...")
        writer.add_role(PR_ROLE, PR_NOTES, "undl:ambassadors", listed_with_member=True)
        summary["representatives"] = _load_person_records(
            files["ambassadors"], people, aliases, unknown, "member state", "alternative names", PR_ROLE)
    if files["sc_representatives"]:
        log(f"Reading {files['sc_representatives'].name} ...")
        writer.add_role(SC_ROLE, SC_NOTES, "undl:sc_representatives")
        writer.add_role(SC_PRESIDENT_ROLE, SC_PRESIDENT_NOTES, "undl:sc_representatives")
        summary["sc_representatives"] = _load_person_records(
            files["sc_representatives"], people, aliases, unknown, "member_states", "alternative_names", SC_ROLE)
    if unknown:
        log("  Not matched to a member (skipped): " + ", ".join(sorted(unknown)))
    if files["general_debate_speeches"]:
        log(f"Reading {files['general_debate_speeches'].name} ...")
        summary["speeches"] = _load_speeches(writer, files["general_debate_speeches"], people, aliases, log)

    for person in people.values():
        if not person.roles:  # e.g. none of the member names they represented is known
            continue
        person_id = writer.add_person(person.name, salutation=person.salutation,
                                      other_names=person.other_names, record_url=person.record_url)
        for role in person.roles:
            writer.add_person_role(person_id, **role)
    return summary


def _load_person_records(path: Path, people: dict[str, _Person], aliases: _Aliases, unknown: set[str],
                         member_column: str, other_names_column: str, role: str) -> int:
    """A dataset with one row per person (Permanent Representatives, Security Council
    representatives), with the name(s) of the member(s) they represented
    ('Slovakia|Czechoslovakia'). Returns the number of roles added (one per person and member)."""
    count = 0
    for row in _rows(path):
        name = row["name"].strip()
        key = f"record:{(row.get('undl_id') or '').strip() or name}"
        person = people.get(key)
        if person is None:
            person = people[key] = _Person(name, record_url=(row.get("undl_link") or "").strip() or None)
        person.add_names([name, *(_split(row.get(other_names_column)) or [])])
        person.salutation = person.salutation or (row.get("salutation") or "").strip() or None

        recorded: dict[str, list[str]] = {}
        for member_name in _split(row.get(member_column)) or []:
            code = aliases.resolve(member_name)
            if code:
                recorded.setdefault(code, []).append(member_name)
            else:
                unknown.add(member_name)
        notes = _split(row.get("notes"))
        president = (row.get("sc_president") or "").strip().lower() == "true" or any(
            note.startswith("Security Council President") for note in notes or [])
        for code, member_names in recorded.items():
            person.roles.append(dict(role=role, code=code, recorded_as=member_names, notes=notes))
            count += 1
            if role == SC_ROLE and president:
                person.roles.append(dict(role=SC_PRESIDENT_ROLE, code=code, recorded_as=member_names))
    return count


def _load_speeches(writer: VoteWriter, path: Path, people: dict[str, _Person], aliases: _Aliases,
                   log: Callable[[str], None]) -> int:
    """The general debate dataset: one row per speech. Returns the number of speeches."""
    by_name: dict[str, list[str]] = {}  # name -> keys of people with a record
    codes: dict[str, set[str]] = {}  # key -> the members the person represented
    for key, person in people.items():
        by_name.setdefault(person.name, []).append(key)
        codes[key] = {role["code"] for role in person.roles}

    seen: set[tuple] = set()
    duplicates = linked = 0
    other_member: set[str] = set()  # speakers with the name of a record but another member
    ambiguous: set[str] = set()  # speakers whose name and member fit several records
    non_members: Counter = Counter()
    sessions: list[int] = []
    dates: list[str] = []
    for row in _rows(path):
        fields = tuple(value for column, value in row.items() if column)  # not the unnamed row number
        if fields in seen:
            duplicates += 1
            continue
        seen.add(fields)
        name = row["Name"].strip()
        member_name = row["Member State"].strip()
        code = aliases.resolve(member_name)
        if not code:
            non_members[member_name] += 1

        same = [key for key in by_name.get(name, []) if code in codes[key]] if code else []
        if len(same) == 1:
            key, matched_by = same[0], MATCHED_BY_NAME
            linked += 1
        else:
            if same:
                ambiguous.add(f"{name} ({member_name})")
            elif by_name.get(name):
                other_member.add(f"{name} ({member_name})")
            key, matched_by = f"speaker:{name}|{code or member_name}", None
            if key not in people:
                people[key] = _Person(name, salutation=(row.get("Salutation") or "").strip() or None)

        session = (row.get("GA Session") or "").strip() or None
        day = (row.get("Meeting Date") or "").strip() or None
        undl_id = (row.get("UNDL ID") or "").strip()
        people[key].roles.append(dict(
            role=SPEAKER_ROLE, code=code, recorded_as=[member_name], session=session, date=day,
            document=(row.get("Meeting Symbol") or "").strip() or None,
            details={"agenda_items": _list_text(row.get("Agenda Items"))},
            record_url=(row.get("UNDL Link") or "").strip() or (RECORD_URL.format(undl_id) if undl_id else None),
            matched_by=matched_by,
        ))
        if session and session.isdigit():
            sessions.append(int(session))
        if day:
            dates.append(day)

    count = len(seen)
    writer.add_role(SPEAKER_ROLE, SPEAKER_NOTES.format(
        first=min(sessions, default="?"), last=max(sessions, default="?"),
        start=min(dates, default="?"), end=max(dates, default="?")), "undl:general_debate_speeches")
    if duplicates:
        log(f"  Skipped {duplicates} duplicate rows (the same as another row apart from the row number).")
    log(f"  Linked {linked} of {count} speeches to a person's record by name and Member State.")
    if other_member:
        log(f"  Not linked, same name as a person's record but another Member State ({len(other_member)}): "
            + ", ".join(sorted(other_member)[:10]) + (" ..." if len(other_member) > 10 else ""))
    if ambiguous:
        log(f"  Not linked, name and Member State fit several people's records ({len(ambiguous)}): "
            + ", ".join(sorted(ambiguous)))
    if non_members:
        log("  Not a member in the data, kept under the name as recorded: "
            + ", ".join(f"{name} ({n})" for name, n in non_members.most_common()))
    return count


# --- helpers ------------------------------------------------------------------------


def _rows(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as file:
        yield from csv.DictReader(file)


def _int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _totals(row: dict) -> tuple:
    return (
        _int(row.get("total_yes")),
        _int(row.get("total_no")),
        _int(row.get("total_abstentions")),
        _int(row.get("total_non_voting")),
        _int(row.get("total_ms")),
    )


def _split(value: str | None) -> list[str] | None:
    parts = [part.strip() for part in (value or "").split("|") if part.strip()]
    return parts or None


def _list_text(value: str | None) -> list[str] | None:
    """"['A', 'B']" (a Python list written as text, as in some rows of the speeches dataset)
    or 'A|B' -> ['A', 'B']"""
    text = (value or "").strip()
    if text.startswith("["):
        try:
            items = ast.literal_eval(text)  # only reads literals; never runs code
        except (ValueError, SyntaxError):
            items = None
        if isinstance(items, list):
            return [str(item).strip() for item in items if str(item).strip()] or None
    return _split(text)


def _periods(value: str | None) -> list[list[str | None]]:
    """'1945-10-24:1958-02-21|1971-09-02:' -> [['1945-10-24', '1958-02-21'], ['1971-09-02', None]]"""
    periods = []
    for part in _split(value) or []:
        start, _, end = part.partition(":")
        periods.append([start.strip() or None, end.strip() or None])
    return periods


def _last_day(row: dict) -> str:
    """When a name stopped being used ('9999' while it is still in use), to find the latest."""
    return max((end or "9999" for _, end in _periods(row.get("coverage_periods"))), default="")


MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _parse_date(text: str) -> str | None:
    """'17 Aug. 2026' or '2026-01-06' -> '2026-08-17' or '2026-01-06'; None if it isn't a date."""
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})", text)
    if match and match.group(2)[:3].lower() in MONTHS:
        month = MONTHS.index(match.group(2)[:3].lower()) + 1
        return f"{match.group(3)}-{month:02d}-{int(match.group(1)):02d}"
    return None


def _markdown_sections(text: str) -> dict[str, list[str]]:
    """{'citation': [non-empty lines under '## Citation'], ...}"""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^#{2,}\s*(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip().lower()
            sections.setdefault(current, [])
        elif current and line.strip():
            sections[current].append(line.strip())
    return sections
