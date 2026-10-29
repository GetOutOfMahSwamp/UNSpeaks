"""What the voting tools return. Generic: the same shape for any body."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VoteTotals(BaseModel):
    yes: int | None = None
    no: int | None = None
    abstain: int | None = None
    non_voting: int | None = None
    members: int | None = Field(None, description="Number of members of the body at the time")


class SourceInfo(BaseModel):
    title: str
    version: str | None = None
    url: str | None = None
    data_until: str | None = Field(
        None, description="How recent the data is: the date of its newest record, or when it was published"
    )
    citation: str = Field(description="Include this citation when you use the data")
    terms: str | None = None


class MemberVote(BaseModel):
    code: str
    name: str = Field(description="Name as recorded at the time of the vote")
    vote: str | None = Field(None, description="yes / no / abstain / non_voting, or null if no individual vote")
    label: str | None = Field(None, description="e.g. 'permanent member'")
    note: str | None = None


class VotingRecord(BaseModel):
    body_id: str = Field(description="e.g. 'UNGA' or 'UNSC'")
    body: str = Field(description="Full name of the body that voted")
    identifier: str = Field(description="e.g. the resolution symbol")
    title: str | None = None
    date: str | None = Field(None, description="Date of the vote (YYYY-MM-DD)")
    session: str | None = None
    outcome: str | None = Field(None, description="e.g. 'adopted'")
    adoption_method: str | None = Field(
        None, description="'recorded vote', 'non-recorded vote' or 'without a vote'"
    )
    explanation: str = Field(description="What the adoption method means for the votes below")
    totals: VoteTotals | None = None
    member_vote: MemberVote | None = Field(None, description="The vote of the member you asked about")
    votes: dict[str, list[str]] | None = Field(
        None,
        description="Members grouped by vote ('yes', 'no', 'abstain', 'non_voting'), each as "
        "'NAME (CODE)'. null when there were no individual votes or they weren't requested.",
    )
    note: str | None = Field(None, description="Remarks from the data source about this vote")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific details, e.g. draft symbol, meeting record, agenda items, subjects",
    )
    record_url: str | None = Field(None, description="The official record of this vote")
    coverage: str | None = Field(None, description="What the data does and doesn't cover")
    sources: list[SourceInfo]


class DecisionSummary(BaseModel):
    body_id: str
    identifier: str
    title: str | None = None
    date: str | None = None
    session: str | None = None
    adoption_method: str | None = None
    totals: VoteTotals | None = None
    member_vote: str | None = Field(None, description="How the requested member voted")
    record_url: str | None = None


class NameInUse(BaseModel):
    name: str
    current: bool = Field(description="True for the name in use today")
    periods: list[str] = Field(description="When the name was used, e.g. '1945-10-24 to 2023-03-02' or 'since 2023-03-03'")
    note: str | None = Field(None, description="Remarks from the data source, e.g. why the name changed")


class RelatedMember(BaseModel):
    code: str = Field(description="Use it with the other tools, e.g. search_votes(member=code)")
    name: str
    relation: str = Field(description="'earlier' (it came from this member) or 'later' (it became this member)")
    via: str | None = Field(None, description="The name that links them, if it differs from `name`")


class Participation(BaseModel):
    body_id: str
    body: str
    recorded_votes: int = Field(description="Number of recorded votes it was listed in")
    votes: dict[str, int] = Field(description="How often it voted yes / no / abstain / non_voting")
    first_vote: str | None = None
    last_vote: str | None = None
    years: list[str] = Field(
        description="Years with recorded votes it was listed in, e.g. ['1946', '1951-1952']. For a body "
        "with elected seats, such as the Security Council, these are the years it had a seat. A gap can "
        "also mean the body held no recorded votes that year (the General Assembly had none in 1964)."
    )
    names_used: list[str] = Field(description="Its names as recorded in these votes")
    labels: list[str] = Field(default_factory=list, description="Extra info recorded with its votes, e.g. 'permanent member'")


class Representative(BaseModel):
    name: str = Field(description="As recorded: 'Last name, first name'")
    salutation: str | None = Field(None, description="As used in UN documents, e.g. 'Ms.'")
    roles: list[str] = Field(
        default_factory=list,
        description="Functions as recorded, some with a date, e.g. 'Security Council President (Mar. 2018)'",
    )
    recorded_as: list[str] | None = Field(
        None,
        description="The member's name(s) in this person's record. Only given when the member has had "
        "more than one name: it tells under which name(s), and so roughly when, the person served.",
    )
    other_names: list[str] = Field(default_factory=list, description="Other forms of the person's name")
    record_url: str | None = None


class RepresentativeGroup(BaseModel):
    role: str = Field(description="e.g. 'Permanent Representative'")
    total: int
    people: list[Representative] = Field(description="In alphabetical order, not by date")
    note: str | None = Field(None, description="What this data does and doesn't cover")


class MemberProfile(BaseModel):
    code: str = Field(description="The member's code in the voting data, usually its ISO 3166 code")
    name: str = Field(description="Its name today, or the last name of a former member")
    status: str | None = Field(None, description="'current member' or 'former member'")
    member_since: str | None = Field(None, description="Start of its first name in the records (YYYY-MM-DD)")
    member_until: str | None = Field(None, description="Only for former members: end of its last name (YYYY-MM-DD)")
    names: list[NameInUse] = Field(default_factory=list, description="Every name it was known by, oldest first")
    related: list[RelatedMember] = Field(
        default_factory=list,
        description="Members it came from or became, e.g. USSR -> Russian Federation. Each has its own "
        "code and votes.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific details, e.g. ISO and M49 codes, founding member, membership "
        "resolution, names in other UN languages, UN Thesaurus term",
    )
    participation: list[Participation] = Field(
        default_factory=list, description="How it took part in recorded votes, per body"
    )
    representatives: list[RepresentativeGroup] | None = Field(
        None, description="People who represented it, per role. null when not requested."
    )
    record_url: str | None = Field(None, description="The official record of this member")
    sources: list[SourceInfo]


class SearchVotesResult(BaseModel):
    total: int = Field(description="Number of matching decisions")
    page: int
    limit: int
    has_more: bool = Field(description="True if there are more results: ask for page + 1")
    member: MemberVote | None = Field(None, description="The member the results are filtered on")
    results: list[DecisionSummary]
    note: str | None = None
    sources: list[SourceInfo]
