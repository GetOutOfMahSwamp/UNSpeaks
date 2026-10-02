"""The UNSpeaks MCP server.

Run it with `uv run unspeaks` (stdio, e.g. for Claude Desktop), or open it in the
MCP Inspector with `uv run mcp dev src/unspeaks/server.py`.

Note: imports are absolute (`from unspeaks...`) because `mcp dev` loads this file
by its path rather than as part of the package.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from unspeaks import config
from unspeaks.documents import (
    DEFAULT_PAGES,
    MAX_PAGES_PER_CALL,
    DocumentPages,
    DocumentRequestError,
    DocumentService,
)
from unspeaks.ods_client import OdsError
from unspeaks.votes.models import SearchVotesResult, VotingRecord
from unspeaks.votes.service import VotingLookupError, VotingService
from unspeaks.votes.store import DataNotLoadedError

INSTRUCTIONS = """\
UNSpeaks gives you access to official United Nations information.

- All data and documents are (c) United Nations and provided "as is". When you use
  them in an answer, cite the source: the document symbol and the URL or citation
  that the tools return.
- Documents are downloaded from UN servers on demand, within strict rate limits.
  Only fetch documents you actually need, and read long documents a few pages at a time.
- Voting data comes from datasets of the UN Dag Hammarskjöld Library. They end at a
  certain date (see `data_until` in each answer); say so when a question is about
  something more recent.
- UNSpeaks is an independent project, not affiliated with or endorsed by the UN.
"""

mcp = MCPServer("UNSpeaks", instructions=INSTRUCTIONS, version=config.VERSION)

_service: DocumentService | None = None


def get_service() -> DocumentService:
    global _service
    if _service is None:
        _service = DocumentService()
    return _service


def set_service(service: DocumentService | None) -> None:
    """Swap the document service (used by tests)."""
    global _service
    _service = service


_voting: VotingService | None = None


def get_voting() -> VotingService:
    global _voting
    if _voting is None:
        _voting = VotingService()
    return _voting


def set_voting(service: VotingService | None) -> None:
    """Swap the voting service (used by tests)."""
    global _voting
    _voting = service


LOCAL_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
Body = Literal["UNGA", "UNSC"]
Position = Literal["yes", "no", "abstain", "non_voting"]
AdoptionMethod = Literal["recorded vote", "non-recorded vote", "without a vote"]
DateText = Annotated[str, Field(pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$", description="YYYY-MM-DD, YYYY-MM or YYYY")]
VOTING_ERRORS = (VotingLookupError, DataNotLoadedError)


@mcp.tool(title="Search UN votes", annotations=LOCAL_READ_ONLY)
def search_votes(
    query: Annotated[
        str | None,
        Field(description="Words to find in the title, agenda items and subjects, e.g. 'nuclear "
              "weapons'. Every word must match (word beginnings count), so keep it short."),
    ] = None,
    body: Annotated[
        Body | None,
        Field(description="'UNGA' = General Assembly, 'UNSC' = Security Council. Default: both."),
    ] = None,
    member: Annotated[
        str | None,
        Field(description="A Member State: a name in any common form ('Netherlands', 'Türkiye', "
              "'Ivory Coast') or an ISO code ('NLD'). Adds how it voted to each result, and keeps "
              "only resolutions with individual votes."),
    ] = None,
    position: Annotated[
        Position | None,
        Field(description="With `member`: only resolutions where it voted this way."),
    ] = None,
    adoption_method: Annotated[
        AdoptionMethod | None, Field(description="Only resolutions adopted this way.")
    ] = None,
    date_from: DateText | None = None,
    date_to: DateText | None = None,
    session: Annotated[
        str | None,
        Field(description="General Assembly session, e.g. '80'. Special sessions look like '10emsp' "
              "(emergency special session 10) or '29sp'."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Results per page (1-50).")] = 20,
    page: Annotated[int, Field(ge=1, description="Page number, starting at 1.")] = 1,
) -> SearchVotesResult:
    """Search adopted UN General Assembly and Security Council resolutions and how they were adopted.

    Based on the UN Dag Hammarskjöld Library's voting datasets. Use it to:
    - find resolutions on a topic: query='nuclear weapons', body='UNGA'
    - see how a Member State voted: member='Netherlands', optionally with query, dates,
      or position='no' to find the resolutions it voted against
    - list recent votes: date_from='2025-01-01'

    Good to know:
    - `query` searches titles, agenda items and subjects (UN Thesaurus terms such as
      CLIMATE CHANGE or HUMAN RIGHTS). Every word must match, so use one or two key words.
    - Only adopted resolutions are included: drafts that failed, including vetoed Security
      Council drafts, are not.
    - About two thirds of General Assembly resolutions are adopted without a vote. They have
      no individual votes, so they drop out when you filter on a member.
    - The data ends at `sources[].data_until`; anything newer is missing.
    - Results are newest first; use `page` for more. Cite `sources` when you use the data.

    Use get_voting_record for the full country-by-country vote on one resolution.
    """
    try:
        return get_voting().search(
            query=query, body_id=body, member=member, vote=position,
            adoption_method=adoption_method, date_from=date_from, date_to=date_to,
            session=session, limit=limit, page=page,
        )
    except VOTING_ERRORS as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(title="Get the vote on a UN resolution", annotations=LOCAL_READ_ONLY)
def get_voting_record(
    symbol: Annotated[
        str,
        Field(description="Symbol of the adopted resolution, e.g. 'A/RES/80/228' (General "
              "Assembly) or 'S/RES/2720(2023)' (Security Council; 'S/RES/2720' also works)."),
    ],
    member: Annotated[
        str | None,
        Field(description="Optional Member State (name or ISO code) whose vote to highlight."),
    ] = None,
    include_member_votes: Annotated[
        bool,
        Field(description="Set to false to get only the totals and details, without the lists "
              "of how every member voted."),
    ] = True,
) -> VotingRecord:
    """How a UN General Assembly or Security Council resolution was adopted, and how every
    Member State voted when there was a recorded vote.

    Returns the title, date, session, totals, related documents (`details`: draft, meeting
    record, agenda items, subjects) and, for recorded votes, the members per vote:
    yes / no / abstain / non_voting. Security Council permanent members are marked.

    - `adoption_method` tells how it was adopted. For 'without a vote' (most General Assembly
      resolutions) or 'non-recorded vote' there are no individual votes: say so, it is not
      missing data.
    - 'non_voting' means the member was recorded as not voting (for example absent); the
      data does not say why.
    - Names are as recorded at the time of the vote.
    - Only adopted resolutions are included; failed and vetoed drafts are not.

    To read the debate, use get_document on the meeting record in `details.meeting`; to read
    the resolution itself, use get_document with the same symbol. Cite `sources` and
    `record_url` when you use the data.
    """
    try:
        return get_voting().get_record(symbol, member=member, include_votes=include_member_votes)
    except VOTING_ERRORS as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(
    title="Get a UN document",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
def get_document(
    symbol: Annotated[
        str,
        Field(
            description="UN document symbol, e.g. 'A/RES/78/1', 'S/RES/2720(2023)', "
            "'A/78/PV.5' or 'S/PV.9520'."
        ),
    ],
    language: Annotated[
        Literal["en", "fr", "es", "ar", "zh", "ru"],
        Field(description="One of the six official UN languages. Default: English."),
    ] = "en",
    start_page: Annotated[int, Field(ge=1, description="First page to return (1 = start).")] = 1,
    max_pages: Annotated[
        int,
        Field(ge=1, le=MAX_PAGES_PER_CALL, description="How many pages to return (1-10)."),
    ] = DEFAULT_PAGES,
) -> DocumentPages:
    """Get the text of an official UN document by its document symbol.

    Works for any document in the UN Official Document System (ODS): resolutions,
    meeting records, reports, letters. Symbol examples:
    - 'A/RES/78/1': General Assembly resolution 78/1
    - 'S/RES/2720(2023)': Security Council resolution 2720 (2023)
    - 'A/78/PV.5': verbatim record of the 5th General Assembly plenary meeting, session 78
    - 'S/PV.9520': verbatim record of Security Council meeting 9520

    Returns the text page by page (page numbers match the PDF), the total number of
    pages and a `source` with a ready-made citation. Long documents (meeting records
    often have 30-50 pages) come in parts: call again with start_page = next_page,
    and only read the pages you need.

    Use this only when you know the symbol. Always cite the returned source when you
    use the text in an answer.
    """
    try:
        return get_service().get_pages(symbol, language, start_page, max_pages)
    except (OdsError, DocumentRequestError) as exc:
        raise ToolError(str(exc)) from exc


def main() -> None:
    """Start the server over stdio (how Claude Desktop and other MCP clients run it)."""
    mcp.run()


if __name__ == "__main__":
    main()
