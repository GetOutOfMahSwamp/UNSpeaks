# UNSpeaks server (developer notes)

This folder holds the UNSpeaks MCP server. For what the project is and the rules it
follows, see the [main README](../README.md).

## Layout

```
src/unspeaks/
├── server.py        # the MCP server and its tools (start here)
├── documents.py     # get_document logic: paging, size limits, citations
├── ods_client.py    # downloads PDFs from the UN Official Document System, politely
├── rate_limiter.py  # max 100 requests per 5 minutes, 3 s apart, honours HTTP 429
├── pdf_text.py      # PDF -> text, one string per page
└── config.py        # settings (data folder, limits, User-Agent)
scripts/try_ods.py   # try a download by hand, without MCP
tests/               # offline tests (a fake ODS stands in for the real one)
```

Downloaded documents are cached in `../data/cache/ods/`, which is not in Git.

## Commands (run from this folder)

| What | Command |
|---|---|
| Run the tests | `uv run pytest` |
| Fetch one document by hand | `uv run python scripts/try_ods.py A/RES/78/1` |
| Open the server in the MCP Inspector (needs Node.js) | `uv run mcp dev src/unspeaks/server.py` |
| Start the server (stdio) | `uv run unspeaks` |

Optional: set `UNSPEAKS_CONTACT_EMAIL` to add a contact address to the User-Agent,
and `UNSPEAKS_DATA_DIR` to use another data folder.

## Use it in Claude Desktop

In Claude Desktop, open Settings → Developer → Edit Config, and add:

```json
{
  "mcpServers": {
    "unspeaks": {
      "command": "C:\\Users\\<you>\\.local\\bin\\uv.exe",
      "args": ["--directory", "C:\\path\\to\\UNSpeaks\\UNSpeaksCode", "run", "unspeaks"]
    }
  }
}
```

Then restart Claude Desktop completely.

## Tools

| Tool | What it does |
|---|---|
| `get_document` | Text of a UN document by symbol (e.g. `A/RES/78/1`), a few pages at a time, with a citation |
