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
