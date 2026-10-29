"""The voting database (SQLite): schema, writing (used by the build step) and reading.

The schema is the same for every body. Source-specific extras go in the JSON
`details` column of a decision and in the `notes` of a body.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA_VERSION = "3"  # 3: member profiles with name history, and representatives

# How a member voted. UN data uses yes/no/abstain/non_voting; 'present' is there for
# parliaments such as the US Senate.
VOTE_VALUES = ("yes", "no", "abstain", "present", "non_voting")

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE sources (              -- the datasets the data came from
    source_id     TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    publisher     TEXT,
    version       TEXT,
    record_url    TEXT,
    citation      TEXT NOT NULL,    -- shown with every answer
    file_name     TEXT,
    downloaded_on TEXT,
    data_until    TEXT,             -- date of the newest decision from this source
    terms         TEXT
);
CREATE TABLE bodies (               -- assemblies / parliaments
    body_id     TEXT PRIMARY KEY,   -- e.g. 'UNGA'
    name        TEXT NOT NULL,      -- e.g. 'United Nations General Assembly'
    member_term TEXT NOT NULL,      -- e.g. 'Member State', 'Senator'
    notes       TEXT                -- what the data does and doesn't cover
);
CREATE TABLE decisions (            -- one row per resolution / bill / roll call
    decision_id      INTEGER PRIMARY KEY,
    body_id          TEXT NOT NULL REFERENCES bodies(body_id),
    identifier       TEXT NOT NULL, -- e.g. 'A/RES/78/1'
    lookup_key       TEXT NOT NULL, -- identifier without spaces, upper case
    title            TEXT,
    date             TEXT,          -- YYYY-MM-DD
    session          TEXT,
    adoption_method  TEXT,          -- 'recorded vote', 'non-recorded vote', 'without a vote', ...
    outcome          TEXT,          -- 'adopted', 'rejected', ...
    total_yes        INTEGER,
    total_no         INTEGER,
    total_abstain    INTEGER,
    total_non_voting INTEGER,
    total_members    INTEGER,
    note             TEXT,
    details          TEXT,          -- JSON: source-specific fields
    record_url       TEXT,
    source_id        TEXT REFERENCES sources(source_id),
    votes_source_id  TEXT REFERENCES sources(source_id)
);
CREATE TABLE members (              -- a member under one name (names change over time)
    member_id INTEGER PRIMARY KEY,
    body_id   TEXT NOT NULL,
    code      TEXT NOT NULL,        -- stable code, e.g. ISO 'NLD' or a senator id
    name      TEXT NOT NULL,        -- name as recorded at the time of the vote
    UNIQUE (body_id, code, name)
);
CREATE TABLE member_profiles (      -- one row per code: who the member is
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,     -- the name to show today (a former member: its last name)
    is_current   INTEGER,           -- 1 = still a member, 0 = not any more, NULL = unknown
    member_since TEXT,              -- YYYY-MM-DD
    member_until TEXT,              -- YYYY-MM-DD; NULL while still a member
    names        TEXT,              -- JSON: name history, [{name, current, periods, note, record_url}]
    related      TEXT,              -- JSON: predecessors and successors, [{code, name, relation, via}]
    details      TEXT,              -- JSON: source-specific, e.g. other codes, founding member
    record_url   TEXT,
    source_id    TEXT REFERENCES sources(source_id)
);
CREATE TABLE member_aliases (       -- every name people might use, normalised
    alias_key TEXT NOT NULL,
    code      TEXT NOT NULL,
    priority  INTEGER NOT NULL,     -- 0 = the code, 1 = name used in the votes, 2 = other names
    PRIMARY KEY (alias_key, code)
) WITHOUT ROWID;
CREATE TABLE representative_roles ( -- kinds of representatives, e.g. 'Permanent Representative'
    role      TEXT PRIMARY KEY,
    notes     TEXT,                 -- what the data does and doesn't cover
    source_id TEXT REFERENCES sources(source_id)
);
CREATE TABLE representatives (      -- people who represented a member, e.g. a country's ambassadors
    code        TEXT NOT NULL,
    role        TEXT NOT NULL REFERENCES representative_roles(role),
    name        TEXT NOT NULL,      -- as recorded, e.g. 'Gregoire-Van-Haaren, Lise'
    salutation  TEXT,
    other_names TEXT,               -- JSON list
    recorded_as TEXT,               -- JSON list: the member's name(s) as given in this person's record
    notes       TEXT,               -- JSON list: functions, e.g. 'Security Council President (Mar. 2018)'
    record_url  TEXT
);
CREATE TABLE votes (
    decision_id INTEGER NOT NULL,
    member_id   INTEGER NOT NULL,
    vote        TEXT NOT NULL,      -- one of VOTE_VALUES
    raw_vote    TEXT,               -- the value as in the source, e.g. 'Y'
    label       TEXT,               -- extra info shown with the member, e.g. 'permanent member'
    PRIMARY KEY (decision_id, member_id)
) WITHOUT ROWID;
CREATE VIRTUAL TABLE decisions_fts USING fts5(   -- full-text search; rowid = decision_id
    identifier, title, keywords,
    content = '',
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

INDEXES = """
CREATE INDEX decisions_lookup ON decisions(lookup_key);
CREATE INDEX decisions_body_date ON decisions(body_id, date);
CREATE INDEX members_code ON members(code);
CREATE INDEX votes_member ON votes(member_id, decision_id);
CREATE INDEX representatives_code ON representatives(code, role);
"""


def normalize_identifier(identifier: str) -> str:
    """'S/RES/2720 (2023)' -> 'S/RES/2720(2023)'; used to look decisions up."""
    return re.sub(r"\s+", "", identifier or "").upper()


def normalize_name(name: str) -> str:
    """"Côte d'Ivoire" -> 'cote d ivoire'; 'NETHERLANDS (KINGDOM OF THE)' -> 'netherlands kingdom of the'."""
    text = unicodedata.normalize("NFKD", (name or "").replace("ı", "i"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", text.lower()).strip()


class DataNotLoadedError(Exception):
    """The voting database hasn't been built yet."""


# --- Writing (build step) ------------------------------------------------------


class VoteWriter:
    """Fills a new database. Loaders in unspeaks.sources use this."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._member_ids: dict[tuple[str, str, str], int] = {}

    @classmethod
    @contextmanager
    def create(cls, path: Path) -> Iterator["VoteWriter"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA journal_mode = OFF")
            conn.execute("PRAGMA synchronous = OFF")
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
            writer = cls(conn)
            yield writer
            writer._finish()
            conn.commit()
        finally:
            conn.close()

    def _finish(self) -> None:
        self.conn.executescript(INDEXES)
        # The newest decision; a source without decisions keeps the date given by its loader.
        self.conn.execute(
            """UPDATE sources SET data_until = COALESCE((
                   SELECT MAX(date) FROM decisions d
                   WHERE d.source_id = sources.source_id OR d.votes_source_id = sources.source_id),
                   data_until)"""
        )
        self.conn.execute("ANALYZE")

    def add_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def add_source(self, source_id: str, *, title: str, citation: str, publisher: str | None = None,
                   version: str | None = None, record_url: str | None = None,
                   file_name: str | None = None, downloaded_on: str | None = None,
                   terms: str | None = None, data_until: str | None = None) -> None:
        """`data_until`: how recent the data is. For sources with decisions it is replaced by
        the date of the newest decision when the database is finished."""
        self.conn.execute(
            """INSERT OR REPLACE INTO sources (source_id, title, publisher, version, record_url,
                   citation, file_name, downloaded_on, data_until, terms)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (source_id, title, publisher, version, record_url, citation, file_name, downloaded_on,
             data_until, terms),
        )

    def add_body(self, body_id: str, name: str, member_term: str, notes: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO bodies VALUES (?,?,?,?)", (body_id, name, member_term, notes)
        )

    def add_decision(self, *, body_id: str, identifier: str, title: str | None = None,
                     date: str | None = None, session: str | None = None,
                     adoption_method: str | None = None, outcome: str | None = None,
                     totals: tuple[int | None, int | None, int | None, int | None, int | None] = (None,) * 5,
                     note: str | None = None, details: dict | None = None,
                     keywords: str | None = None, record_url: str | None = None,
                     source_id: str | None = None, votes_source_id: str | None = None) -> int:
        """Add one decision and return its id.

        totals = (yes, no, abstain, non_voting, members). `keywords` is extra searchable
        text, e.g. agenda items and subjects.
        """
        details = {k: v for k, v in (details or {}).items() if v not in (None, "", [])}
        cursor = self.conn.execute(
            """INSERT INTO decisions (body_id, identifier, lookup_key, title, date, session,
                   adoption_method, outcome, total_yes, total_no, total_abstain, total_non_voting,
                   total_members, note, details, record_url, source_id, votes_source_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (body_id, identifier, normalize_identifier(identifier), title, date, session,
             adoption_method, outcome, *totals, note,
             json.dumps(details, ensure_ascii=False) if details else None,
             record_url, source_id, votes_source_id),
        )
        decision_id = int(cursor.lastrowid)
        self.conn.execute(
            "INSERT INTO decisions_fts (rowid, identifier, title, keywords) VALUES (?,?,?,?)",
            (decision_id, identifier, title or "", keywords or ""),
        )
        return decision_id

    def set_votes_source(self, decision_ids: Iterable[int], source_id: str) -> None:
        self.conn.executemany(
            "UPDATE decisions SET votes_source_id = ? WHERE decision_id = ?",
            [(source_id, decision_id) for decision_id in decision_ids],
        )

    def member_id(self, body_id: str, code: str, name: str) -> int:
        key = (body_id, code, name)
        if key not in self._member_ids:
            cursor = self.conn.execute(
                "INSERT INTO members (body_id, code, name) VALUES (?,?,?)", key
            )
            self._member_ids[key] = int(cursor.lastrowid)
        return self._member_ids[key]

    def add_votes(self, rows: Iterable[tuple[int, int, str, str | None, str | None]]) -> None:
        """rows: (decision_id, member_id, vote, raw_vote, label)."""
        self.conn.executemany("INSERT OR REPLACE INTO votes VALUES (?,?,?,?,?)", rows)

    def add_member_profile(self, code: str, name: str, *, is_current: bool | None = None,
                           member_since: str | None = None, member_until: str | None = None,
                           names: list[dict] | None = None, related: list[dict] | None = None,
                           details: dict | None = None, record_url: str | None = None,
                           source_id: str | None = None) -> None:
        """Who a member is. Only `name` is required; the rest comes from a source that
        describes the members, such as the UN Member States dataset."""
        details = {k: v for k, v in (details or {}).items() if v not in (None, "", [], {})}
        self.conn.execute(
            """INSERT OR REPLACE INTO member_profiles (code, name, is_current, member_since,
                   member_until, names, related, details, record_url, source_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (code, name, None if is_current is None else int(is_current), member_since, member_until,
             _json(names), _json(related), _json(details), record_url, source_id),
        )

    def add_representative_role(self, role: str, notes: str | None = None,
                                source_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO representative_roles VALUES (?, ?, ?)", (role, notes, source_id)
        )

    def add_representative(self, code: str, role: str, name: str, *, salutation: str | None = None,
                           other_names: list[str] | None = None, recorded_as: list[str] | None = None,
                           notes: list[str] | None = None, record_url: str | None = None) -> None:
        """One person who represented one member in one role (add the role first)."""
        self.conn.execute(
            "INSERT INTO representatives VALUES (?,?,?,?,?,?,?,?)",
            (code, role, name, salutation, _json(other_names), _json(recorded_as), _json(notes),
             record_url),
        )

    def add_member_aliases(self, code: str, names: Iterable[str], priority: int = 2) -> None:
        """Names that refer to this member. When a name fits several members, the lowest
        priority wins: 0 = the code itself, 1 = a name used in the votes, 2 = other names.
        Add the most important names first."""
        rows = [(normalize_name(code), code, 0)]
        rows += [(normalize_name(name), code, priority) for name in names]
        self.conn.executemany(
            "INSERT OR IGNORE INTO member_aliases VALUES (?, ?, ?)", [r for r in rows if r[0]]
        )


# --- Reading (used by the tools) ---------------------------------------------------


class VoteStore:
    """Read-only access to the voting database. Opens a connection per call, so it is
    safe to use from parallel tool calls and never keeps the file locked."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise DataNotLoadedError(
                "The voting data hasn't been loaded yet. Download the datasets into "
                "data/raw/ and run `uv run unspeaks-build-db` in the UNSpeaksCode folder."
            )
        conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # --- decisions ---

    def find_decisions(self, identifier: str, body_id: str | None = None) -> list[sqlite3.Row]:
        """Exact match on the identifier. If there is none, accept a unique match that only
        lacks a bracketed suffix ('S/RES/2720' -> 'S/RES/2720(2023)')."""
        key = normalize_identifier(identifier)
        body_sql, body_params = (" AND body_id = ?", [body_id]) if body_id else ("", [])
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE lookup_key = ?" + body_sql, [key, *body_params]
            ).fetchall()
            if rows or not key:
                return rows
            rows = conn.execute(
                "SELECT * FROM decisions WHERE lookup_key LIKE ? ESCAPE '\\'" + body_sql + " LIMIT 2",
                [_like_escape(key) + "(%", *body_params],
            ).fetchall()
            return rows if len(rows) == 1 else []

    def suggest(self, identifier: str, body_id: str | None = None, limit: int = 5) -> list[str]:
        """Identifiers that contain the given text, e.g. '78/1' -> 'A/RES/78/1'."""
        key = normalize_identifier(identifier)
        if not key:
            return []
        sql = "SELECT identifier FROM decisions WHERE lookup_key LIKE ? ESCAPE '\\'"
        params: list = [f"%{_like_escape(key)}%"]
        if body_id:
            sql += " AND body_id = ?"
            params.append(body_id)
        sql += " ORDER BY length(lookup_key), date DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [row["identifier"] for row in conn.execute(sql, params)]

    def votes_for(self, decision_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT m.code, m.name, v.vote, v.raw_vote, v.label
                   FROM votes v JOIN members m USING (member_id)
                   WHERE v.decision_id = ? ORDER BY m.name""",
                (decision_id,),
            ).fetchall()

    def search(self, *, query: str | None = None, body_id: str | None = None,
               member_code: str | None = None, vote: str | None = None,
               adoption_method: str | None = None, date_from: str | None = None,
               date_to: str | None = None, session: str | None = None,
               limit: int = 20, offset: int = 0) -> tuple[int, list[sqlite3.Row]]:
        """Decisions matching all given filters, newest first. Returns (total, page of rows).

        With `member_code`, only decisions where that member has a recorded vote are
        returned, together with its vote (`member_vote`, `member_name`, `member_label`).
        """
        select = "d.*"
        joins = ""
        where: list[str] = []
        params: list = []
        if member_code:
            select += ", v.vote AS member_vote, m.name AS member_name, v.label AS member_label"
            joins = (" JOIN votes v ON v.decision_id = d.decision_id"
                     " JOIN members m ON m.member_id = v.member_id AND m.code = ?")
            params.append(member_code)
            if vote:
                where.append("v.vote = ?")
                params.append(vote)
        if query:
            match = _fts_query(query)
            if match:
                where.append("d.decision_id IN (SELECT rowid FROM decisions_fts WHERE decisions_fts MATCH ?)")
                params.append(match)
        for column, value in (("d.body_id", body_id), ("d.adoption_method", adoption_method),
                              ("d.session", session)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        if date_from:
            where.append("d.date >= ?")
            params.append(_date_bound(date_from, end=False))
        if date_to:
            where.append("d.date <= ?")
            params.append(_date_bound(date_to, end=True))

        base = f"FROM decisions d{joins}" + (" WHERE " + " AND ".join(where) if where else "")
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT {select} {base} ORDER BY d.date DESC, d.decision_id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return total, rows

    # --- members ---

    def resolve_member(self, text: str) -> list[sqlite3.Row]:
        """Members matching a name or code, e.g. 'Netherlands', 'Pays-Bas', 'NLD'.

        Tries, in order: an exact name (lowest priority wins, so 'USSR' finds the USSR
        rather than the Russian Federation, which lists it as an earlier name); then the
        text as a whole word inside a name ('Korea' -> both Koreas); then names that
        start with the text. More than one row means the text is ambiguous.
        """
        key = normalize_name(text)
        if not key:
            return []
        select = """SELECT a.code, COALESCE(p.name, a.code) AS name, MIN(a.priority) AS priority
                    FROM member_aliases a LEFT JOIN member_profiles p USING (code)
                    WHERE {where} GROUP BY a.code ORDER BY priority, name LIMIT 10"""
        with self.connect() as conn:
            rows = conn.execute(select.format(where="a.alias_key = ?"), (key,)).fetchall()
            if rows:
                best = rows[0]["priority"]
                return [row for row in rows if row["priority"] == best]
            word = f"% {_like_escape(key)} %"
            rows = conn.execute(
                select.format(where="(' ' || a.alias_key || ' ') LIKE ? ESCAPE '\\'"), (word,)
            ).fetchall()
            if rows:
                return rows
            return conn.execute(
                select.format(where="a.alias_key LIKE ? ESCAPE '\\'"), (_like_escape(key) + "%",)
            ).fetchall()

    def member_profile(self, code: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM member_profiles WHERE code = ?", (code,)).fetchone()

    def member_participation(self, code: str) -> list[sqlite3.Row]:
        """How a member took part in recorded votes: one row per body, year, name used,
        vote and label, with the number of votes and the first and last date."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT d.body_id, substr(d.date, 1, 4) AS year, m.name, v.vote, v.label,
                          d.votes_source_id, COUNT(*) AS n, MIN(d.date) AS first_date,
                          MAX(d.date) AS last_date
                   FROM members m JOIN votes v USING (member_id) JOIN decisions d USING (decision_id)
                   WHERE m.code = ?
                   GROUP BY d.body_id, year, m.name, v.vote, v.label, d.votes_source_id
                   ORDER BY d.body_id, year""",
                (code,),
            ).fetchall()

    def representatives(self, code: str) -> list[sqlite3.Row]:
        """People who represented a member, grouped by role (in the order the roles were
        added), then by name."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT r.*, rr.notes AS role_notes, rr.source_id AS role_source_id
                   FROM representatives r JOIN representative_roles rr USING (role)
                   WHERE r.code = ? ORDER BY rr.rowid, r.name COLLATE NOCASE""",
                (code,),
            ).fetchall()

    # --- bodies, sources and settings ---

    def meta(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def body(self, body_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM bodies WHERE body_id = ?", (body_id,)).fetchone()

    def bodies(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT b.*, MIN(d.date) AS first_date, MAX(d.date) AS last_date,
                          COUNT(d.decision_id) AS decisions
                   FROM bodies b LEFT JOIN decisions d USING (body_id)
                   GROUP BY b.body_id ORDER BY b.body_id"""
            ).fetchall()

    def all_sources(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM sources ORDER BY source_id").fetchall()

    def source(self, source_id: str | None) -> sqlite3.Row | None:
        if not source_id:
            return None
        with self.connect() as conn:
            return conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()


# --- helpers -------------------------------------------------------------------------


def _json(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value else None


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts_query(text: str) -> str:
    """'nuclear weapons' -> '"nuclear"* AND "weapons"*' (every word must match, as a prefix)."""
    words = re.findall(r"\w+", text or "")
    return " AND ".join(f'"{word}"*' for word in words)


def _date_bound(value: str, *, end: bool) -> str:
    """'2025' -> '2025-01-01' or '2025-12-31'; '2025-06' -> '2025-06-01' or '2025-06-31'."""
    value = value.strip()
    if len(value) == 4:
        return value + ("-12-31" if end else "-01-01")
    if len(value) == 7:
        return value + ("-31" if end else "-01")
    return value
