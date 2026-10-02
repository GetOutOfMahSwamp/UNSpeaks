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
├── config.py        # settings (data folder, limits, User-Agent)
├── build_db.py      # `unspeaks-build-db`: builds data/unspeaks.sqlite from data/raw/
├── votes/           # GENERIC voting layer: works for any assembly or parliament
│   ├── store.py     #   SQLite schema, writing and reading (bodies, decisions, members, votes)
│   ├── service.py   #   look-ups and search used by the tools
│   └── models.py    #   what the voting tools return
└── sources/         # one loader per data source: everything source-specific lives here
    └── undl.py      #   UN Dag Hammarskjöld Library datasets (GA, SC, Member State names)
scripts/try_ods.py   # try a download by hand, without MCP
tests/               # offline tests (fake ODS, tiny copies of the UN datasets)
```

Downloaded documents are cached in `../data/cache/ods/`, and the voting database is
`../data/unspeaks.sqlite`. Neither is in Git.

### Adding another assembly or parliament

The voting tools only use the generic `votes/` layer. To add, say, the US Senate:
write `sources/us_senate.py` with a `load(writer, raw_dir, log)` function that adds its
body, sources, decisions, members and votes (mapping e.g. Yea/Nay/Present/Not Voting to
yes/no/present/non_voting), call it from `build_db.py`, and add its body id to the `Body`
choices in `server.py`.

## Commands (run from this folder)

| What | Command |
|---|---|
| Run the tests | `uv run pytest` |
| Build the voting database from `../data/raw/` | `uv run unspeaks-build-db` |
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
| `get_voting_record` | How a GA or SC resolution was adopted, totals, and how each member voted (optionally highlighting one) |
| `search_votes` | Find resolutions by words, body, date, session or adoption method, or how one Member State voted |
