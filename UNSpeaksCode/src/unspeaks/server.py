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

INSTRUCTIONS = """\
UNSpeaks gives you access to official United Nations information.

- All data and documents are (c) United Nations and provided "as is". When you use
  them in an answer, cite the source: the document symbol and the URL or citation
  that the tools return.
- Documents are downloaded from UN servers on demand, within strict rate limits.
  Only fetch documents you actually need, and read long documents a few pages at a time.
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
