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
│   ├── store.py     #   SQLite schema, writing and reading (bodies, decisions, members, votes,
│   │                #   member profiles, representatives)
│   ├── service.py   #   look-ups and search used by the tools
│   └── models.py    #   what the voting tools return
└── sources/         # one loader per data source: everything source-specific lives here
    └── undl.py      #   UN Dag Hammarskjöld Library: weekly voting archives (MARCXML) and datasets
                     #   (GA, SC, Member States, Permanent Representatives)
scripts/try_ods.py   # try a download by hand, without MCP
tests/               # offline tests (fake ODS, tiny copies of the UN archives and datasets)
```

Downloaded documents are cached in `../data/cache/ods/`, and the voting database is
`../data/unspeaks.sqlite`. Neither is in Git.

### Where the voting data comes from

`unspeaks-build-db` only reads files in `../data/raw/`; it never downloads anything. For
each body it uses the Library's weekly MARCXML archive if it is there, and otherwise the
CSV datasets, so you can mix them (say, the GA archive with the SC CSV):

| Body | Used first | Otherwise |
|---|---|---|
| General Assembly | `all_voting_data_general_assembly.xml` or `.xml.gz` | `*_ga_outcomes.csv` and `*_ga_voting.csv` |
| Security Council | `all_voting_data_security_council.xml` or `.xml.gz` | `*_sc_voting.csv` |

The archives are downloaded by hand (see the [main README](../README.md#data-sources)) and
keep the Library's file names. Their citation is the download link plus the download
date, taken from the file's modification date. The build log says which files it used.

The MARCXML fields UNSpeaks reads are listed at the top of the archive section in
`sources/undl.py`. In short:

- `791 $a` symbol, `791 $c` GA session, `245` title, `992` date (`269` only when `992` is missing; a different `269` goes into `details.date_note`)
- `590` "Vote" / "Without Vote"; a vote without `967` fields is a non-recorded vote
- `967` one per member (`$c` code, `$e` name, `$d` Y/N/A/X, blank = not voting, `$b` P = SC permanent member)
- `996` totals (a missing count is 0), `996 $a` the remark on the vote
- `952` meeting, `993` drafts and GA committee reports, `991 $c` agenda items, `991 $d` subjects
- `591` (free text) and `650` (nearly empty) are not used

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
| `get_member_state` | A Member State's names over time, codes, membership dates, related states, Security Council years, vote counts and Permanent Representatives |

After pulling a new version, run `uv run unspeaks-build-db` again if the database schema changed
(`get_member_state` says so when it did), then restart Claude Desktop. Rebuild too whenever you
download newer voting archives (the Library refreshes them weekly).
