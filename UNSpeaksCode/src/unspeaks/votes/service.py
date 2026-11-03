"""Look up and search voting records. Generic: works for any body in the database."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter

from unspeaks import config
from unspeaks.votes.models import (
    DecisionSummary,
    MemberProfile,
    MemberVote,
    NameInUse,
    Participation,
    RelatedMember,
    Representative,
    RepresentativeGroup,
    SearchVotesResult,
    SourceInfo,
    VoteTotals,
    VotingRecord,
)
from unspeaks.votes.store import VOTE_VALUES, DataNotLoadedError, VoteStore

EXPLANATIONS = {
    "recorded vote": "Adopted by a recorded vote: how each {member} voted is listed in `votes`.",
    "non-recorded vote": (
        "Adopted by a vote in which individual votes were not recorded, so there is no "
        "list of how each {member} voted."
    ),
    "without a vote": (
        "Adopted without a vote (for example by consensus or acclamation). There are no "
        "individual votes: this is how it was adopted, not missing data."
    ),
}

# Set by a loader: which source provided the member names used to recognise members.
MEMBER_NAMES_SOURCE = "member_names_source"


class VotingLookupError(Exception):
    """A record or member can't be found, or the request is ambiguous. The message says why."""


class VotingService:
    def __init__(self, store: VoteStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> VoteStore:
        if self._store is None:
            self._store = VoteStore(config.database_path())
        return self._store

    # --- one record ----------------------------------------------------------------

    def get_record(self, identifier: str, body_id: str | None = None, member: str | None = None,
                   include_votes: bool = True) -> VotingRecord:
        rows = self.store.find_decisions(identifier, body_id)
        if not rows:
            raise VotingLookupError(self._not_found_message(identifier, body_id))
        if len(rows) > 1:
            bodies = ", ".join(sorted(row["body_id"] for row in rows))
            raise VotingLookupError(f"'{identifier}' exists in several bodies ({bodies}); pass `body`.")

        decision = rows[0]
        body = self.store.body(decision["body_id"])
        member_term = body["member_term"].lower() if body else "member"
        method = decision["adoption_method"]
        explanation = EXPLANATIONS.get(method, "How this was adopted is not recorded.").format(
            member=member_term
        )

        vote_rows = self.store.votes_for(decision["decision_id"])
        votes = None
        if include_votes and vote_rows:
            grouped: dict[str, list[str]] = {}
            for row in vote_rows:
                grouped.setdefault(row["vote"], []).append(_member_label(row))
            votes = {value: grouped[value] for value in VOTE_VALUES if value in grouped}

        member_vote = None
        source_ids = [decision["source_id"], decision["votes_source_id"]]
        if member:
            code, name = self._resolve_member(member)
            source_ids.append(self.store.meta(MEMBER_NAMES_SOURCE))
            match = next((row for row in vote_rows if row["code"] == code), None)
            if match:
                member_vote = MemberVote(code=code, name=match["name"], vote=match["vote"], label=match["label"])
            else:
                reason = (
                    "There were no individual votes."
                    if not vote_rows
                    else f"Not among the {member_term}s recorded for this vote "
                    "(for example because it was not a member at the time)."
                )
                member_vote = MemberVote(code=code, name=name, vote=None, note=reason)

        return VotingRecord(
            body_id=decision["body_id"],
            body=body["name"] if body else decision["body_id"],
            identifier=decision["identifier"],
            title=decision["title"],
            date=decision["date"],
            session=decision["session"],
            outcome=decision["outcome"],
            adoption_method=method,
            explanation=explanation,
            totals=_totals(decision),
            member_vote=member_vote,
            votes=votes,
            note=decision["note"],
            details=json.loads(decision["details"]) if decision["details"] else {},
            record_url=decision["record_url"],
            coverage=body["notes"] if body else None,
            sources=self._sources(source_ids),
        )

    # --- search -----------------------------------------------------------------------

    def search(self, *, query: str | None = None, body_id: str | None = None,
               member: str | None = None, vote: str | None = None,
               adoption_method: str | None = None, date_from: str | None = None,
               date_to: str | None = None, session: str | None = None,
               limit: int = 20, page: int = 1) -> SearchVotesResult:
        if vote and not member:
            raise VotingLookupError("`position` only works together with `member`.")
        member_info = None
        code = None
        if member:
            code, name = self._resolve_member(member)
            member_info = MemberVote(code=code, name=name)

        limit = max(1, min(limit, 50))
        page = max(1, page)
        total, rows = self.store.search(
            query=query, body_id=body_id, member_code=code, vote=vote,
            adoption_method=adoption_method, date_from=date_from, date_to=date_to,
            session=session, limit=limit, offset=(page - 1) * limit,
        )

        results = [
            DecisionSummary(
                body_id=row["body_id"],
                identifier=row["identifier"],
                title=_shorten(row["title"]),
                date=row["date"],
                session=row["session"],
                adoption_method=row["adoption_method"],
                totals=_totals(row),
                member_vote=row["member_vote"] if code else None,
                record_url=row["record_url"],
            )
            for row in rows
        ]

        note = None
        if code:
            note = (
                "Only decisions with individual votes are listed when filtering on a member; "
                "decisions adopted without a vote (most General Assembly resolutions) have none."
            )
        if total == 0:
            note = ((note + " ") if note else "") + (
                "Nothing found. Try fewer or shorter words, or other filters. "
                "Only adopted decisions are included."
            )

        source_ids: list[str | None] = []
        for row in rows:
            source_ids += [row["source_id"], row["votes_source_id"]]
        if code:
            source_ids.append(self.store.meta(MEMBER_NAMES_SOURCE))
        if not rows:  # still show which data was searched and how recent it is
            source_ids += [s["source_id"] for s in self.store.all_sources() if s["data_until"]]
        return SearchVotesResult(
            total=total,
            page=page,
            limit=limit,
            has_more=page * limit < total,
            member=member_info,
            results=results,
            note=note,
            sources=self._sources(source_ids),
        )

    # --- one member --------------------------------------------------------------------

    def get_member(self, member: str, include_representatives: bool = True) -> MemberProfile:
        """Who a member is: its names over time, membership dates, the members it came from
        or became, how it took part in recorded votes and, if wanted, who represented it."""
        if int(self.store.meta("schema_version") or 0) < 3:
            raise DataNotLoadedError(
                "The database was built by an older version of UNSpeaks and has no member profiles "
                "yet. Run `uv run unspeaks-build-db` in the UNSpeaksCode folder again."
            )
        code, _ = self._resolve_member(member)
        profile = self.store.member_profile(code)
        names = json.loads(profile["names"]) if profile["names"] else []
        source_ids: list[str | None] = [profile["source_id"]]
        participation = self._participation(code, source_ids)
        representatives = None
        if include_representatives:
            # Which of its names a person served under only says something if it had several.
            representatives = self._representatives(code, len(names) > 1, source_ids)

        return MemberProfile(
            code=code,
            name=profile["name"],
            status={1: "current member", 0: "former member"}.get(profile["is_current"]),
            member_since=profile["member_since"],
            member_until=profile["member_until"],
            names=[
                NameInUse(name=entry["name"], current=entry["current"],
                          periods=[_period(start, end) for start, end in entry["periods"]],
                          note=entry.get("note"))
                for entry in names
            ],
            related=[RelatedMember(**entry) for entry in json.loads(profile["related"] or "[]")],
            details=json.loads(profile["details"]) if profile["details"] else {},
            participation=participation,
            representatives=representatives,
            record_url=profile["record_url"],
            sources=self._sources(source_ids),
        )

    def _participation(self, code: str, source_ids: list[str | None]) -> list[Participation]:
        bodies: dict[str, dict] = {}
        for row in self.store.member_participation(code):
            body = bodies.setdefault(row["body_id"], dict(
                votes=Counter(), years=set(), names=set(), labels=set(), dates=[]))
            body["votes"][row["vote"]] += row["n"]
            if row["year"]:
                body["years"].add(int(row["year"]))
            body["names"].add(row["name"])
            if row["label"]:
                body["labels"].add(row["label"])
            body["dates"] += [row["first_date"], row["last_date"]]
            source_ids.append(row["votes_source_id"])

        result = []
        for body_id, body in bodies.items():
            info = self.store.body(body_id)
            dates = [d for d in body["dates"] if d]
            result.append(Participation(
                body_id=body_id,
                body=info["name"] if info else body_id,
                recorded_votes=sum(body["votes"].values()),
                votes={value: body["votes"][value] for value in VOTE_VALUES if body["votes"][value]},
                first_vote=min(dates, default=None),
                last_vote=max(dates, default=None),
                years=_year_ranges(body["years"]),
                names_used=sorted(body["names"]),
                labels=sorted(body["labels"]),
            ))
        return result

    def _representatives(self, code: str, show_recorded_as: bool,
                         source_ids: list[str | None]) -> list[RepresentativeGroup]:
        groups: dict[str, RepresentativeGroup] = {}
        for row in self.store.representatives(code):
            group = groups.get(row["role"])
            if group is None:
                group = groups[row["role"]] = RepresentativeGroup(
                    role=row["role"], total=0, people=[], note=row["role_notes"])
                source_ids.append(row["role_source_id"])
            group.people.append(Representative(
                name=row["name"],
                salutation=row["salutation"],
                roles=_json_list(row["notes"]),
                recorded_as=_json_list(row["recorded_as"]) if show_recorded_as else None,
                other_names=_json_list(row["other_names"]),
                record_url=row["record_url"],
            ))
            group.total += 1
        return list(groups.values())

    # --- helpers -----------------------------------------------------------------------

    def _resolve_member(self, text: str) -> tuple[str, str]:
        rows = self.store.resolve_member(text)
        if not rows:
            raise VotingLookupError(
                f"No member matches '{text}'. Use a name such as 'Netherlands' or a code such as 'NLD'."
            )
        if len(rows) > 1:
            options = ", ".join(f"{row['name']} ({row['code']})" for row in rows)
            raise VotingLookupError(f"'{text}' matches several members: {options}. Use the full name or code.")
        return rows[0]["code"], rows[0]["name"]

    def _sources(self, source_ids: list[str | None]) -> list[SourceInfo]:
        sources = []
        for source_id in dict.fromkeys(s for s in source_ids if s):
            source = self.store.source(source_id)
            if source:
                sources.append(
                    SourceInfo(
                        title=source["title"],
                        version=source["version"],
                        url=source["record_url"],
                        data_until=source["data_until"],
                        citation=source["citation"],
                        terms=source["terms"],
                    )
                )
        return sources

    def _not_found_message(self, identifier: str, body_id: str | None) -> str:
        where = f" in {body_id}" if body_id else ""
        parts = [f"No adopted decision '{identifier}' found{where}."]
        coverage = [
            f"{row['body_id']} ({row['name']}): {row['first_date']} to {row['last_date']}"
            for row in self.store.bodies()
            if row["decisions"] and (not body_id or row["body_id"] == body_id)
        ]
        if coverage:
            parts.append("The data covers " + "; ".join(coverage) + ".")
        parts.append("Only adopted decisions are included: drafts that failed or were vetoed are not.")
        suggestions = self.store.suggest(identifier, body_id)
        if not suggestions:  # e.g. 'resolution 2720': try the parts that contain a number
            for part in re.findall(r"[^\s]*\d[^\s]*", identifier):
                suggestions = self.store.suggest(part, body_id)
                if suggestions:
                    break
        if suggestions:
            parts.append("Did you mean: " + ", ".join(suggestions) + "?")
        return " ".join(parts)


def _member_label(row: sqlite3.Row) -> str:
    extra = f", {row['label']}" if row["label"] else ""
    return f"{row['name']} ({row['code']}{extra})"


def _totals(row: sqlite3.Row) -> VoteTotals | None:
    totals = VoteTotals(
        yes=row["total_yes"],
        no=row["total_no"],
        abstain=row["total_abstain"],
        non_voting=row["total_non_voting"],
        members=row["total_members"],
    )
    return totals if any(v is not None for v in totals.model_dump().values()) else None


def _period(start: str | None, end: str | None) -> str:
    """('1945-10-24', '2023-03-02') -> '1945-10-24 to 2023-03-02'; ('2023-03-03', None) -> 'since 2023-03-03'."""
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"since {start}"
    return f"until {end}" if end else "unknown"


def _year_ranges(years: set[int]) -> list[str]:
    """{1946, 1951, 1952, 2018} -> ['1946', '1951-1952', '2018']"""
    ranges: list[list[int]] = []
    for year in sorted(years):
        if ranges and year == ranges[-1][1] + 1:
            ranges[-1][1] = year
        else:
            ranges.append([year, year])
    return [str(first) if first == last else f"{first}-{last}" for first, last in ranges]


def _json_list(value: str | None) -> list[str]:
    return json.loads(value) if value else []


def _shorten(text: str | None, limit: int = 200) -> str | None:
    if not text or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
