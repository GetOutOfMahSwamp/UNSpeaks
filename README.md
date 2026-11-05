# UNSpeaks

**UNSpeaks is an MCP server that lets AI assistants answer questions about the United Nations using official data. The goal is to make democracy more transparent, one natural-language question at a time.**

It connects AI assistants such as Claude to data published by the UN Dag Hammarskjöld Library through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). Questions like these then get answers based on real, citable records:

- *"How did the Netherlands vote on General Assembly resolutions about climate change last session?"*
- *"Which Security Council resolutions were adopted without a vote in 2025?"*
- *"Who represents Brazil at the UN, and who spoke for Brazil in the general debate?"*

> **Status: early development.** This is a student project. Four tools work (see [Tools](#tools)); more are planned.

UNSpeaks is an independent project. It is **not affiliated with, endorsed by or sponsored by the United Nations** or the Dag Hammarskjöld Library.

---

## How it works

```
AI assistant  ──MCP──▶  UNSpeaks server  ──▶  local SQLite database (built from UN Library data)
                                        └──▶  documents.un.org (single documents, on demand, rate-limited)
```

1. You download the official voting archives and datasets from the UN Digital Library **by hand** (see [Data sources](#data-sources)).
2. A build command turns them into one local SQLite database.
3. The MCP server answers the assistant's questions from that database. Every answer includes a source citation.
4. When a question needs a document's full text, the server fetches that one document from the UN Official Document System, within strict rate limits (see [Guidelines](#terms-of-use-and-how-unspeaks-follows-them)).

### Tools

- [x] `get_document`: the text of a UN document by its symbol (e.g. `A/RES/78/1`), a few pages at a time, fetched on demand from the Official Document System
- [x] `get_voting_record`: how a General Assembly or Security Council resolution was adopted and how each Member State voted
- [x] `search_votes`: find resolutions by topic, date, session or adoption method, or see how one Member State voted
- [x] `get_member_state`: a Member State's names over time, codes, membership dates, predecessor and successor states, Security Council terms and Permanent Representatives
- [ ] `search_people`: find people who spoke or acted for a Member State (general debate speakers, Permanent Representatives, Security Council representatives and presidents) by name, Member State, role or General Assembly session

The voting tools are built on a generic core (bodies, decisions, members, votes), with everything UN-specific in a separate loader, so the same tools could later serve another assembly or parliament.

### Tech stack

- Python 3.13+
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- SQLite, managed with [uv](https://docs.astral.sh/uv/)

---

## Data sources

All data comes from the **United Nations Dag Hammarskjöld Library**. None of it is **included in this repository**. Download the files by hand and put them in `data/raw/`.

### Voting data: the weekly MARCXML archives

The Library publishes every General Assembly and Security Council voting record as two MARCXML archives, refreshed weekly. UNSpeaks builds its voting data from these.

| Archive | Downloaded | Coverage then | Download link |
|---|---|---|---|
| General Assembly voting data | 27 Oct 2026 | 20,839 resolutions, from 1946 up to A/RES/81/6 (23 Oct 2026); 5,733 with a recorded vote | [all_voting_data_general_assembly.xml.gz](https://digitallibrary.un.org/export/marcxml/all_voting_data_general_assembly.xml.gz) |
| Security Council voting data | 3 Nov 2026 | 2,833 resolutions, from 1946 up to S/RES/2833(2026) (30 Oct 2026) | [all_voting_data_security_council.xml.gz](https://digitallibrary.un.org/export/marcxml/all_voting_data_security_council.xml.gz) |

To get or refresh them:

1. Open the link in your browser. The Library keeps its bot protection in place for these files, so UNSpeaks never downloads them itself.
2. Save the file in `data/raw/` under its own name. You can keep it as `.xml.gz` or unzip it to `.xml`. If both are there, UNSpeaks uses the one modified last.
3. Run `uv run unspeaks-build-db` again (see [Getting started](#getting-started)).

The file names have no date, so the download date in the citations is the file's **modification date**. Check it after unzipping: some unzip tools give the unzipped file the date stored inside the archive instead of today's date.

If an archive is not in `data/raw/`, UNSpeaks uses the CSV voting datasets below for that body instead.

### Datasets

| Dataset | Version used | Coverage | Record |
|---|---|---|---|
| General Assembly Voting Data (only used without the GA archive) | v5 (Feb 2026) | Resolutions 1 (1946) to 80/246 (30 Dec 2025) | [4060887](https://digitallibrary.un.org/record/4060887) |
| General Assembly resolutions (only used without the GA archive) | v5 (Feb 2026) | Resolutions 1 (1946) to 80/246 (30 Dec 2025) | [4060945](https://digitallibrary.un.org/record/4060945) |
| Security Council Voting Data (only used without the SC archive) | v6 (Feb 2026) | Resolutions 1 (1946) to 2815 (30 Jan 2026) | [4055387](https://digitallibrary.un.org/record/4055387) |
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
2. **Attribution in every answer.** Each tool response names its source (the voting archive or dataset, with its version where there is one) and its download date, and links to the resolution's or dataset's record in the UN Digital Library where possible.
3. **No automated access to the UN Digital Library.** UNSpeaks does not scrape, crawl or automatically download from `digitallibrary.un.org`, and does not try to get around its bot protection. The voting archives and datasets are downloaded by hand; the build step only reads the files in `data/raw/`. The Library does not permit automated downloads without its approval, and keeps its bot protection in place for the weekly voting archives.
4. **Careful document downloads.** Documents from `documents.un.org` are fetched:
   - only when a user asks for one, one document at a time;
   - at **no more than 100 requests per 5 minutes**, as the Library recommends;
   - with respect for server responses: on **HTTP 429** or other errors, the server waits (honouring `Retry-After`) instead of retrying straight away;
   - **with caching**, so each document is downloaded only once;
   - with a User-Agent that identifies UNSpeaks.
5. **No redistribution.** This repository contains no UN datasets or documents. The `data/` folder is excluded from Git.
6. **Neutral naming.** Country names are shown exactly as they appear in the UN data. For historical votes, that is the name at the time of the vote.

We have asked the Library for guidance on a hosted version of UNSpeaks. This section will be updated with their answer.

### Citation

When you use results from UNSpeaks, cite the underlying source. For the voting archives, the Library accepts the archive's link plus the download date:

> United Nations Dag Hammarskjöld Library, General Assembly voting data (weekly MARCXML export), United Nations, downloaded from https://digitallibrary.un.org/export/marcxml/all_voting_data_general_assembly.xml.gz, 2026-10-27

Each answer also links the resolution's own record, for example https://digitallibrary.un.org/record/3959039 for A/RES/ES-11/1.

For the datasets, each dataset's record page gives the exact citation, for example:

> United Nations Dag Hammarskjöld Library, General Assembly Voting Data, United Nations, version 5 (February 2026), 2026, downloaded from https://digitallibrary.un.org/record/4060887, [download date]

UNSpeaks reads it from the description file you save next to the dataset, and fills in the download date.

---

## Limitations

- **Data is not live.** Answers are only as current as the files you downloaded. The voting archives are refreshed weekly: download them again and rebuild the database to catch up. Each answer's `data_until` gives the date of the newest resolution.
- **Adopted resolutions only.** The voting data leaves out votes on drafts that failed (including vetoed Security Council drafts) and votes on individual paragraphs.
- **Not every resolution has a vote.** About three quarters of General Assembly resolutions were adopted without a recorded vote, so there are no country-by-country votes for them. That is how they were adopted, not missing data. For a non-recorded vote, only the totals are known, when the Library recorded them.
- **Security Council adoptions without a vote.** For resolutions adopted without a vote or by acclamation, the data records every member as "X" (non-voting). The CSV dataset's description says "Y" instead. UNSpeaks relies on how the resolution was adopted ("Without Vote") and never presents these as abstentions or absences.
- **Some records have two dates.** In 108 records of the October 2026 archives (76 General Assembly, 32 Security Council), the two date fields differ, sometimes by months. UNSpeaks uses field 992, which every record has and which the CSV datasets mostly used, and gives the other date in the answer (`details.date_note`).
- **Subjects come from the agenda.** The archives have almost no subject terms of their own (field 650). UNSpeaks uses the subject of each resolution's agenda item (field 991), which is exactly what the CSV datasets list as subjects, and which newer resolutions have too.
- **Divided resolutions.** The archive lists some resolutions by their parts where the CSV dataset had one symbol, for example A/RES/80/231 A and A/RES/80/231 B for A/RES/80/231. Asking for the undivided symbol gives a "did you mean" with the parts.
- **Known errors in the data.** In the archive, France is marked as an elected member of the Security Council for S/RES/1752(2007); the CSV dataset has the same error. The archive corrects some errors of the CSV dataset: Somalia marked as a permanent member for five resolutions in 2025, and China and Russia recorded as voting yes on S/RES/2812(2026), where they abstained.
- **Permanent Representatives have no dates.** The dataset lists current and past heads of mission, but not when they served, so UNSpeaks can't say who is in office now. Dated roles (such as "Security Council President (Mar. 2018)") and the country name a person served under are given as clues.
- **Security Council terms are derived from the votes.** The years in which a Member State took part in recorded Security Council votes are shown as the years it had a seat.
- **Permanent Representatives citation.** The Library's description file for this dataset cites record 4047618, which is the Security Council representatives dataset. UNSpeaks cites the dataset's own record, [4091498](https://digitallibrary.un.org/record/4091498), instead.
- **AI can make mistakes.** Check important answers against the linked UN records.

The data is provided by the UN "as is", without warranty. The designations used and the presentation of material do not imply any opinion of the United Nations, or of this project, on the legal status of any country, territory or area, or of its authorities.

---

## Repository layout

```
UNSpeaks/
├── UNSpeaksCode/      # the UNSpeaks MCP server (Python, in development)
├── data/              # local data, NOT in Git
│   └── raw/           # put the downloaded archives and datasets here
├── opentk-mcp-main/   # reference implementation (see Credits)
└── README.md
```

## Getting started

You need Python 3.13+, [uv](https://docs.astral.sh/uv/) and an MCP-compatible AI assistant such as Claude Desktop.

1. Download the voting archives and datasets listed under [Data sources](#data-sources) by hand and save them in `data/raw/`, keeping their file names. Save each dataset's description file (`.md`) too, with a name that starts with the same date (for example `2026_08_17_UN_member_states.md`): UNSpeaks reads the version, publication date and citation from it.
2. Build the local database (takes less than a minute). Do this again whenever you download newer files:
   ```
   cd UNSpeaksCode
   uv run unspeaks-build-db
   ```
3. Add the server to your AI assistant. See [UNSpeaksCode/README.md](UNSpeaksCode/README.md) for the Claude Desktop settings.

---

## Credits

- **UN Dag Hammarskjöld Library**, for publishing the voting data and datasets this project is built on, and for its guidance.
- **[OpenTK MCP server](https://github.com/r-huijts/opentk-mcp)** by r-huijts (MIT licence), an MCP server for the Dutch House of Representatives. Its tool design inspired UNSpeaks, and a copy is kept in `opentk-mcp-main/` for reference.
- **[OpenTK / tkconv](https://berthub.eu/tkconv/)** by Bert Hubert, the data service behind OpenTK.

## License

The UNSpeaks code is released under the [MIT License](LICENSE).

This licence covers **only the code** written for UNSpeaks. It does not cover:

- **UN data and documents.** These remain © United Nations and may only be used under the UN terms described in [Terms of use](#terms-of-use-and-how-unspeaks-follows-them): non-commercial use, with attribution. The MIT licence allows commercial use of the code, but it gives no extra rights to the UN data. Anyone who reuses this code with UN data must still follow the UN terms.
- **`opentk-mcp-main/`.** This is third-party code by r-huijts, under its own MIT licence (see `opentk-mcp-main/LICENSE`).

## Contact

Questions or suggestions? Open an issue on GitHub.
