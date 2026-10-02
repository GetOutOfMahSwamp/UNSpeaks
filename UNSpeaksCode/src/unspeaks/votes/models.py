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
    data_until: str | None = Field(None, description="Date of the newest record in this dataset")
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


class SearchVotesResult(BaseModel):
    total: int = Field(description="Number of matching decisions")
    page: int
    limit: int
    has_more: bool = Field(description="True if there are more results: ask for page + 1")
    member: MemberVote | None = Field(None, description="The member the results are filtered on")
    results: list[DecisionSummary]
    note: str | None = None
    sources: list[SourceInfo]
