"""Loader for the UN Dag Hammarskjöld Library datasets.

Reads the files you downloaded by hand into data/raw/ (we never download them
automatically: see the README, "Terms of use"). For each dataset the newest file
is used; file names start with their date, e.g. 2026_02_06_ga_voting.csv.

- *_ga_outcomes.csv  General Assembly resolutions (one row per resolution,
                     including those adopted without a vote)
- *_ga_voting.csv    General Assembly voting data (one row per Member State per vote)
- *_sc_voting.csv    Security Council voting data (one row per member per resolution)
- *_unms_names.csv   UN Member States, all their names, with dates and codes: used for
                     get_member_state, and to recognise a country however it's written
                     ('Netherlands', 'Pays-Bas', 'NLD', ...)
- *_ambassadors.csv  Permanent Representatives: heads of the Member States' missions

The Library's description files (saved next to the CSVs, see find_description) are read
for the version, the publication date and the exact citation. When you download a newer
version, rebuild the database and the citations update automatically.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

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
    "ambassadors": Dataset("ambassadors", "United Nations Permanent Representatives", "https://digitallibrary.un.org/record/4091498"),
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


def find_description(csv_path: Path, title: str) -> Path | None:
    """The Library's description file, saved next to the CSV. Its name varies:
    '<csv name>_md.md', '<csv name>_1.md', or a name of its own with the same date, such as
    2026_08_17_UN_member_states.md for 2026_08_17_unms_names.csv. In that last case the
    title inside the file must be the dataset's title."""
    folder, stem = csv_path.parent, csv_path.stem
    if (folder / f"{stem}_md.md").exists():
        return folder / f"{stem}_md.md"
    named = sorted(folder.glob(f"{stem}_*.md"))
    if named:
        return named[0]
    day = re.match(r"\d{4}_\d{2}_\d{2}_", stem)
    for candidate in sorted(folder.glob(f"{day.group(0)}*.md")) if day else []:
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
            info["version"] = re.sub(r"^current version:\s*", "Version ", sections["version"][0], flags=re.I)
        if sections.get("date of publication"):
            info["published"] = _parse_date(sections["date of publication"][0])
        if sections.get("citation"):
            citation = re.sub(r"\\?\[download date\\?\]", downloaded_on, sections["citation"][0])
            url = re.search(r"https://digitallibrary\.un\.org/(?:record/)?\d+", citation)
            if url and url.group(0) != dataset.record_url:
                # The Permanent Representatives description cites record 4047618, which is the
                # Security Council representatives dataset. Cite the dataset's own record.
                log(f"  {md_path.name} cites {url.group(0)}; citing {dataset.record_url} instead.")
                citation = citation.replace(url.group(0), dataset.record_url)
            info["citation"] = citation

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
            info = read_source_info(kind, path, log)
            writer.add_source(
                f"undl:{kind}", title=info["title"], citation=info["citation"], publisher=PUBLISHER,
                version=info["version"], record_url=info["record_url"], file_name=path.name,
                downloaded_on=info["downloaded_on"], terms=TERMS, data_until=info["published"],
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
        aliases = _load_members(writer, names, files["unms_names"], log)
        summary["members"] = len(names.all)
        if files["ambassadors"]:
            log(f"Reading {files['ambassadors'].name} ...")
            summary["representatives"] = _load_representatives(writer, files["ambassadors"], aliases, log)
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


def _load_representatives(writer: VoteWriter, path: Path, aliases: _Aliases,
                          log: Callable[[str], None]) -> int:
    """The Permanent Representatives dataset: one row per person, with the name(s) of the
    Member State(s) they represented ('Slovakia|Czechoslovakia')."""
    writer.add_representative_role(PR_ROLE, PR_NOTES, "undl:ambassadors")
    count = 0
    unknown: set[str] = set()
    for row in _rows(path):
        recorded: dict[str, list[str]] = {}
        for name in _split(row.get("member state")) or []:
            code = aliases.resolve(name)
            if code:
                recorded.setdefault(code, []).append(name)
            else:
                unknown.add(name)
        for code, member_names in recorded.items():
            writer.add_representative(
                code, PR_ROLE, row["name"].strip(),
                salutation=(row.get("salutation") or "").strip() or None,
                other_names=_split(row.get("alternative names")),
                recorded_as=member_names,
                notes=_split(row.get("notes")),
                record_url=row.get("undl_link") or None,
            )
            count += 1
    if unknown:
        log("  Not matched to a member (skipped): " + ", ".join(sorted(unknown)))
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
