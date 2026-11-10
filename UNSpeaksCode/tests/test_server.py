"""End-to-end tests: an MCP client talks to the UNSpeaks server in-process,
the same way Claude Desktop would (but with a fake ODS)."""

from __future__ import annotations

import pytest
from mcp import Client

from unspeaks import server
from unspeaks.documents import DocumentService
from unspeaks.ods_client import DocumentNotFoundError

from test_documents import TWELVE_PAGES, FakeClient


@pytest.fixture
def fake_ods():
    client = FakeClient()
    server.set_service(DocumentService(client, page_loader=lambda path: TWELVE_PAGES))
    yield client
    server.set_service(None)


@pytest.mark.anyio
async def test_the_tool_is_listed_with_a_clear_description(fake_ods):
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
    tool = next(t for t in tools if t.name == "get_document")
    assert "document symbol" in tool.description
    properties = tool.input_schema["properties"]
    assert set(properties) == {"symbol", "language", "start_page", "max_pages"}
    assert tool.input_schema["required"] == ["symbol"]
    assert tool.annotations.read_only_hint is True
    assert tool.output_schema is not None  # answers are structured JSON


@pytest.mark.anyio
async def test_calling_the_tool_returns_pages_and_a_source(fake_ods):
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_document", {"symbol": "A/RES/78/1", "max_pages": 2})
    assert result.is_error is False
    data = result.structured_content
    assert [p["page"] for p in data["pages"]] == [1, 2]
    assert data["next_page"] == 3
    assert data["source"]["citation"].startswith("United Nations, A/RES/78/1")


@pytest.mark.anyio
async def test_problems_are_reported_to_the_ai_as_tool_errors(fake_ods):
    fake_ods.error = DocumentNotFoundError("No document found for 'A/RES/99/999'")
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_document", {"symbol": "A/RES/99/999"})
    assert result.is_error is True
    assert "No document found" in result.content[0].text


@pytest.mark.anyio
async def test_invalid_arguments_are_rejected(fake_ods):
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_document", {"symbol": "A/RES/78/1", "language": "nl"})
    assert result.is_error is True
    assert fake_ods.calls == 0  # nothing was fetched


# --- voting tools ---------------------------------------------------------------


@pytest.fixture
def voting_db(tmp_path):
    from unspeaks.build_db import build
    from unspeaks.votes.service import VotingService
    from unspeaks.votes.store import VoteStore
    from votes_fixtures import write_raw_dir

    path = tmp_path / "unspeaks.sqlite"
    build(write_raw_dir(tmp_path / "raw"), path, log=lambda message: None)
    server.set_voting(VotingService(VoteStore(path)))
    yield
    server.set_voting(None)


@pytest.mark.anyio
async def test_voting_tools_are_listed(voting_db):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"get_document", "get_voting_record", "search_votes"} <= set(tools)
    assert tools["get_voting_record"].input_schema["required"] == ["symbol"]
    assert tools["search_votes"].input_schema["properties"]["body"]["anyOf"][0]["enum"] == ["UNGA", "UNSC"]


@pytest.mark.anyio
async def test_get_voting_record_tool(voting_db):
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_voting_record", {"symbol": "A/RES/80/10", "member": "Netherlands"})
    assert result.is_error is False
    data = result.structured_content
    assert data["member_vote"]["vote"] == "yes"
    assert data["votes"]["no"] == ["UNITED STATES (USA)"]


@pytest.mark.anyio
async def test_search_votes_tool(voting_db):
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_votes", {"member": "Türkiye", "position": "yes"})
    assert result.is_error is False
    assert [r["identifier"] for r in result.structured_content["results"]] == [
        "A/RES/80/10", "S/RES/2720(2023)", "A/RES/62/223B", "A/RES/62/223 A",
    ]


@pytest.mark.anyio
async def test_get_member_state_tool(voting_db):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        found = await client.call_tool("get_member_state", {"member": "Pays-Bas (Royaume des)"})
        unknown = await client.call_tool("get_member_state", {"member": "Atlantis"})
    tool = tools["get_member_state"]
    assert tool.input_schema["required"] == ["member"]
    assert tool.annotations.read_only_hint is True and tool.output_schema is not None
    assert "no dates" in tool.description
    assert found.is_error is False
    data = found.structured_content
    assert data["code"] == "NLD" and data["status"] == "current member"
    assert data["representatives"][0]["total"] == 2
    assert unknown.is_error is True and "No member matches" in unknown.content[0].text


@pytest.mark.anyio
async def test_voting_errors_reach_the_ai(voting_db):
    async with Client(server.mcp) as client:
        unknown = await client.call_tool("get_voting_record", {"symbol": "A/RES/99/999"})
        bad_date = await client.call_tool("search_votes", {"date_from": "last year"})
    assert unknown.is_error is True and "No adopted decision" in unknown.content[0].text
    assert bad_date.is_error is True


# --- meetings tool ----------------------------------------------------------------


@pytest.fixture
def meetings(tmp_path):
    from datetime import date

    from unspeaks.meetings.service import MeetingService
    from meetings_fixtures import SYMBOL, calendar_fetcher, write_calendar_pdf

    fetch = calendar_fetcher(write_calendar_pdf(tmp_path))
    server.set_meetings(
        MeetingService(fetch_pdf=fetch, calendars={2026: SYMBOL}, today=lambda: date(2026, 11, 10))
    )
    yield fetch
    server.set_meetings(None)


@pytest.mark.anyio
async def test_search_meetings_is_listed_next_to_the_other_tools(meetings):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "get_document", "get_member_state", "get_voting_record", "search_meetings", "search_people",
        "search_votes",
    }
    tool = tools["search_meetings"]
    assert set(tool.input_schema["properties"]) == {"date_from", "date_to", "body", "location", "limit", "page"}
    assert not tool.input_schema.get("required")  # every parameter is optional
    assert tool.annotations.read_only_hint is True and tool.output_schema is not None
    assert "not single meetings" in tool.description and '"as required"' in tool.description


@pytest.mark.anyio
async def test_search_meetings_answers_next_week_in_new_york_in_one_call(meetings):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_meetings", {"date_from": "2026-11-16", "date_to": "2026-11-22", "location": "New York"}
        )
    assert result.is_error is False
    data = result.structured_content
    assert [m["entry"] for m in data["meetings"]] == [314, 292]
    source = data["sources"][0]
    assert (source["symbol"], source["as_at"]) == ("A/AC.172/2026/2", "2026-02-02")
    assert data["undated_total"] == 3 and len(data["limitations"]) == 4


@pytest.mark.anyio
async def test_search_meetings_problems_reach_the_ai(meetings):
    async with Client(server.mcp) as client:
        backwards = await client.call_tool("search_meetings", {"date_from": "2026-11-20", "date_to": "2026-11-10"})
        not_a_date = await client.call_tool("search_meetings", {"date_from": "next week"})
    assert backwards.is_error is True and "before date_from" in backwards.content[0].text
    assert not_a_date.is_error is True
    assert meetings.calls == []  # nothing was fetched for questions that can't be answered


@pytest.mark.anyio
async def test_search_meetings_reports_ods_problems(meetings):
    from unspeaks.meetings.service import MeetingService
    from unspeaks.ods_client import OdsUnavailableError

    def offline(symbol, language):
        raise OdsUnavailableError("ODS could not be reached.")

    server.set_meetings(MeetingService(fetch_pdf=offline, calendars={2026: "A/AC.172/2026/2"}))
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_meetings", {"date_from": "2026-11"})
    assert result.is_error is True and "ODS could not be reached" in result.content[0].text
