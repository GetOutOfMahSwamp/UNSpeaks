# UNSpeaks

**UNSpeaks is an MCP server that lets AI assistants answer questions about the United Nations using official data. The goal is to make democracy more transparent, one natural-language question at a time.**

It connects AI assistants such as Claude to data published by the UN Dag Hammarskjöld Library through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). Questions like these then get answers based on real, citable records:

- *"How did the Netherlands vote on General Assembly resolutions about climate change last session?"*
- *"Which Security Council resolutions were adopted without a vote in 2025?"*
- *"Who represents Brazil at the UN, and who spoke for Brazil in the general debate?"*

> **Status: early development.** This is a student project. No tools are working yet; this README describes the design and the rules the project follows.

UNSpeaks is an independent project. It is **not affiliated with, endorsed by or sponsored by the United Nations** or the Dag Hammarskjöld Library.

---

## How it works

```
AI assistant  ──MCP──▶  UNSpeaks server  ──▶  local SQLite database (built from UN Library datasets)
                                        └──▶  documents.un.org (single documents, on demand, rate-limited)
```

1. You download the official datasets from the UN Digital Library **by hand** (see [Data sources](#data-sources)).
2. A build command turns them into one local SQLite database.
3. The MCP server answers the assistant's questions from that database. Every answer includes a source citation.
4. When a question needs a document's full text, the server fetches that one document from the UN Official Document System, within strict rate limits (see [Guidelines](#terms-of-use-and-how-unspeaks-follows-them)).

### Planned tools

These may still change:

- [ ] `search_resolutions`: find General Assembly and Security Council resolutions by keyword, subject, session or date
- [ ] `get_voting_record`: how each Member State voted on a resolution (yes / no / abstain / non-voting)
- [ ] `get_country_votes`: a Member State's voting history, filtered by topic or period
- [ ] `get_member_state`: names, codes, membership dates and representatives of a Member State
- [ ] `find_speakers`: who spoke in the General Assembly general debate, by session or Member State
- [ ] `get_document`: the text of a UN document by its symbol (e.g. `A/RES/78/1`), fetched on demand

### Tech stack

- Python 3.10+
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- SQLite, managed with [uv](https://docs.astral.sh/uv/)

---

## Data sources

All data comes from datasets published by the **United Nations Dag Hammarskjöld Library**. They are **not included in this repository**. Download them by hand from the record pages below and put them in `data/raw/`.

| Dataset | Version used | Coverage | Record |
|---|---|---|---|
| General Assembly Voting Data | v5 (Feb 2026) | Resolutions 1 (1946) to 80/246 (30 Dec 2025) | [4060887](https://digitallibrary.un.org/record/4060887) |
| General Assembly resolutions | v5 (Feb 2026) | Resolutions 1 (1946) to 80/246 (30 Dec 2025) | [4060945](https://digitallibrary.un.org/record/4060945) |
| Security Council Voting Data | v6 (Feb 2026) | Resolutions 1 (1946) to 2815 (30 Jan 2026) | [4055387](https://digitallibrary.un.org/record/4055387) |
| United Nations Member States | v6 (17 Aug 2026) | All Member State names, codes and membership periods | [4082085](https://digitallibrary.un.org/record/4082085) |
| United Nations Permanent Representatives | Jan 2026 | Current and historical heads of Permanent Missions in New York | [4091498](https://digitallibrary.un.org/record/4091498) |
| Security Council representatives and presidents | v3 (3 Sep 2026) | Up to 3 Sep 2026 | [4047618](https://digitallibrary.un.org/record/4047618) |
| General Assembly general debate speeches | v3 (Jan 2026) | Sessions 1–79 | [4067189](https://digitallibrary.un.org/record/4067189) |
| United Nations Thesaurus | Aug 2026 | Subject vocabulary | [4075456](https://digitallibrary.un.org/record/4075456) |

Individual documents (resolutions, meeting records, reports) come from the UN [Official Document System](https://documents.un.org).

---

## Terms of use and how UNSpeaks follows them

The data and documents are © United Nations. UNSpeaks follows:

- the [Dag Hammarskjöld Library Data Terms of Use](https://digitallibrary.un.org/pages/?ln=en&page=tos)
- the [Terms of use of United Nations websites](https://www.un.org/en/about-us/terms-of-use)
- the guidance the Library gave this project by email

In practice, that means:

1. **Non-commercial use only.** UNSpeaks is free and has no paid features, ads or resale.
2. **Attribution in every answer.** Each tool response names the dataset, its version and its download date, and links to the UN Digital Library record where possible.
3. **No automated access to the UN Digital Library.** UNSpeaks does not scrape, crawl or automatically download from `digitallibrary.un.org`, and does not try to get around its bot protection. The datasets are downloaded by hand. The Library does not permit automated downloads without its approval.
4. **Careful document downloads.** Documents from `documents.un.org` are fetched:
   - only when a user asks for one, one document at a time;
   - at **no more than 100 requests per 5 minutes**, as the Library recommends;
   - with respect for server responses: on **HTTP 429** or other errors, the server waits (honouring `Retry-After`) instead of retrying straight away;
   - **with caching**, so each document is downloaded only once;
   - with a User-Agent that identifies UNSpeaks.
5. **No redistribution.** This repository contains no UN datasets or documents. The `data/` folder is excluded from Git.
6. **Neutral naming.** Country names are shown exactly as they appear in the UN datasets. For historical votes, that is the name at the time of the vote.

We have asked the Library for guidance on a hosted version of UNSpeaks. This section will be updated with their answer.

### Citation

When you use results from UNSpeaks, cite the underlying dataset. For example:

> United Nations Dag Hammarskjöld Library, General Assembly Voting Data, United Nations, version 5 (February 2026), 2026, downloaded from https://digitallibrary.un.org/record/4060887, [download date]

Each dataset's record page gives the exact citation.

---

## Limitations

- **Data is not live.** Answers are only as current as the dataset versions above. For example, General Assembly votes currently run up to December 2025.
- **Adopted resolutions only.** The voting data leaves out votes on drafts that failed and votes on individual paragraphs.
- **Not every resolution has a vote.** About three quarters of General Assembly resolutions were adopted without a recorded vote, so there are no country-by-country votes for them. That is how they were adopted, not missing data.
- **Security Council adoptions without a vote.** For resolutions adopted without a vote or by acclamation, the current data (v6) records every member as "X" (non-voting), with `modality` set to "Without Vote". The dataset description says "Y" instead, so UNSpeaks relies on the `modality` field and never presents these as abstentions or absences.
- **AI can make mistakes.** Check important answers against the linked UN records.

The data is provided by the UN "as is", without warranty. The designations used and the presentation of material do not imply any opinion of the United Nations, or of this project, on the legal status of any country, territory or area, or of its authorities.

---

## Repository layout

```
UNSpeaks/
├── UNSpeaksCode/      # the UNSpeaks MCP server (Python, in development)
├── data/              # local datasets, NOT in Git
│   └── raw/           # put the downloaded dataset files here
├── opentk-mcp-main/   # reference implementation (see Credits)
└── README.md
```

## Getting started

Installation instructions will follow once the first tools work. You will need:

1. Python 3.10+ and [uv](https://docs.astral.sh/uv/)
2. The datasets above, downloaded into `data/raw/`
3. An MCP-compatible AI assistant, e.g. Claude Desktop

---

## Credits

- **UN Dag Hammarskjöld Library**, for publishing the datasets this project is built on.
- **[OpenTK MCP server](https://github.com/r-huijts/opentk-mcp)** by r-huijts (MIT licence), an MCP server for the Dutch House of Representatives. Its tool design inspired UNSpeaks, and a copy is kept in `opentk-mcp-main/` for reference.
- **[OpenTK / tkconv](https://berthub.eu/tkconv/)** by Bert Hubert, the data service behind OpenTK.

## License

The UNSpeaks code is released under the [MIT License](LICENSE).

This licence covers **only the code** written for UNSpeaks. It does not cover:

- **UN data and documents.** These remain © United Nations and may only be used under the UN terms described in [Terms of use](#terms-of-use-and-how-unspeaks-follows-them): non-commercial use, with attribution. The MIT licence allows commercial use of the code, but it gives no extra rights to the UN data. Anyone who reuses this code with UN data must still follow the UN terms.
- **`opentk-mcp-main/`.** This is third-party code by r-huijts, under its own MIT licence (see `opentk-mcp-main/LICENSE`).

## Contact

Questions or suggestions? Open an issue on GitHub.
