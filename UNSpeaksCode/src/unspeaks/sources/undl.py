"""Loader for the UN Dag Hammarskjöld Library datasets.

Reads the files you downloaded by hand into data/raw/ (we never download them
automatically: see the README, "Terms of use"). For each dataset the newest file
is used; file names start with their date, e.g. 2026_02_06_ga_voting.csv.

- *_ga_outcomes.csv  General Assembly resolutions (one row per resolution,
                     including those adopted without a vote)
- *_ga_voting.csv    General Assembly voting data (one row per Member State per vote)
- *_sc_voting.csv    Security Council voting data (one row per member per resolution)
- *_unms_names.csv   UN Member States, all their names: used to recognise a country
                     however it's written ('Netherlands', 'Pays-Bas', 'NLD', ...)

The Library's description files (<same name>_md.md, saved next to the CSVs) are read
for the version and the exact citation. When you download a newer version, rebuild
the database and the citations update automatically.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from unspeaks.votes.store import VoteWriter

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
            "Individual votes exist only for resolutions adopted by recorded vote. Drafts that "
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


DATASETS = {
    "ga_outcomes": Dataset("ga_outcomes", "General Assembly resolutions", "https://digitallibrary.un.org/record/4060945"),
    "ga_voting": Dataset("ga_voting", "General Assembly Voting Data", "https://digitallibrary.un.org/record/4060887"),
    "sc_voting": Dataset("sc_voting", "Security Council Voting Data", "https://digitallibrary.un.org/record/4055387"),
    "unms_names": Dataset("unms_names", "United Nations Member States", "https://digitallibrary.un.org/record/4082085"),
}

VOTES = {"Y": "yes", "N": "no", "A": "abstain", "X": "non_voting"}
GA_METHODS = {
    "vote, recorded": "recorded vote",
    "vote, non-recorded": "non-recorded vote",
    "without a vote": "without a vote",
}
SC_METHODS = {"vote": "recorded vote", "without vote": "without a vote"}

BATCH = 50_000


def find_file(raw_dir: Path, kind: str) -> Path | None:
    """The newest file for a dataset, e.g. 2026_02_06_ga_voting.csv (names start with a date)."""
    candidates = sorted(Path(raw_dir).glob(f"*_{kind}.csv"))
    return candidates[-1] if candidates else None


def read_source_info(kind: str, csv_path: Path) -> dict:
    """Title, version and citation, read from the Library's description file if present."""
    dataset = DATASETS[kind]
    downloaded_on = date.fromtimestamp(csv_path.stat().st_mtime).isoformat()
    info = dict(title=dataset.title, version=None, record_url=dataset.record_url, citation=None)

    md_path = csv_path.with_name(csv_path.stem + "_md.md")
    if md_path.exists():
        sections = _markdown_sections(md_path.read_text(encoding="utf-8-sig"))
        if sections.get("version"):
            info["version"] = sections["version"][0]
        if sections.get("citation"):
            citation = re.sub(r"\\?\[download date\\?\]", downloaded_on, sections["citation"][0])
            info["citation"] = citation
            url = re.search(r"https://digitallibrary\.un\.org/(?:record/)?\d+", citation)
            if url:
                info["record_url"] = url.group(0)

    if not info["citation"]:
        version = f", {info['version']}" if info["version"] else ""
        info["citation"] = (
            f"{PUBLISHER}, {info['title']}, United Nations{version}, "
            f"downloaded from {info['record_url']}, {downloaded_on}"
        )
    info["downloaded_on"] = downloaded_on
    return info


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
    """Load every UN dataset found in raw_dir. Returns counts per dataset."""
    raw_dir = Path(raw_dir)
    summary: dict[str, int] = {}
    files = {kind: find_file(raw_dir, kind) for kind in DATASETS}

    for kind, path in files.items():
        if path:
            info = read_source_info(kind, path)
            writer.add_source(
                f"undl:{kind}", title=info["title"], citation=info["citation"], publisher=PUBLISHER,
                version=info["version"], record_url=info["record_url"], file_name=path.name,
                downloaded_on=info["downloaded_on"], terms=TERMS,
            )

    names = _Names()
    if files["ga_outcomes"] or files["ga_voting"]:
        writer.add_body(GA, **BODIES[GA])
        decision_ids: dict[str, int] = {}
        if files["ga_outcomes"]:
            log(f"Reading {files['ga_outcomes'].name} ...")
            summary["ga_resolutions"] = _load_ga_resolutions(writer, files["ga_outcomes"], decision_ids)
        if files["ga_voting"]:
            log(f"Reading {files['ga_voting'].name} (large file, this takes a little while) ...")
            summary["ga_votes"] = _load_ga_votes(writer, files["ga_voting"], decision_ids, names)

    if files["sc_voting"]:
        writer.add_body(SC, **BODIES[SC])
        log(f"Reading {files['sc_voting'].name} ...")
        summary["sc_resolutions"], summary["sc_votes"] = _load_sc(writer, files["sc_voting"], names)

    if names.all:
        summary["members"] = _load_member_names(writer, names, files["unms_names"], log)
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


# --- Member names -------------------------------------------------------------------


def _load_member_names(writer: VoteWriter, names: _Names, member_states: Path | None,
                       log: Callable[[str], None]) -> int:
    """Names to show and names to recognise, for every member that appears in the votes."""
    display = {code: name for code, (_, name) in names.latest.items()}
    aliases: dict[str, set[str]] = {code: set() for code in names.all}

    if member_states:
        log(f"Reading {member_states.name} ...")
        for row in _rows(member_states):
            code = (row.get("iso") or "").strip()
            if code not in aliases:
                continue  # only members that appear in the voting data
            for column in ("member_state", "french", "spanish", "geographic_term"):
                if row.get(column):
                    aliases[code].add(row[column])
            for column in ("other_names", "earlier_names", "later_names"):
                aliases[code].update(_split(row.get(column)) or [])
            if (row.get("name_status") or "").strip() == "ms":  # the current name
                display[code] = row["member_state"].strip()
        writer.add_meta("member_names_source", "undl:unms_names")

    for code, name in display.items():
        writer.add_member_profile(code, name)
        writer.add_member_aliases(code, names.all[code], priority=1)  # names used in the votes
        writer.add_member_aliases(code, aliases[code] | {name}, priority=2)  # other known names
    return len(display)


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
