"""The voting database (SQLite): schema, writing (used by the build step) and reading.

The schema is the same for every body. Source-specific extras go in the JSON
`details` column of a decision or a person's role, and in the `notes` of a body or a role.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA_VERSION = "4"  # 4: people and their roles (incl. speeches), replacing representatives
# 3: member profiles with name history, and representatives

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
CREATE TABLE roles (                -- kinds of roles, e.g. 'Permanent Representative', 'General debate speaker'
    role               TEXT PRIMARY KEY,
    notes              TEXT,        -- what the data does and doesn't cover
    listed_with_member INTEGER NOT NULL DEFAULT 0,  -- 1 = listed in a member's profile, 0 = only counted there
    source_id          TEXT REFERENCES sources(source_id)
);
CREATE TABLE people (               -- people who acted for a member: representatives, speakers, ...
    person_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,      -- as recorded, e.g. 'Gregoire-Van-Haaren, Lise'
    salutation  TEXT,               -- as recorded, e.g. 'Ms.'
    other_names TEXT,               -- JSON list
    record_url  TEXT                -- the person's own record; NULL if the sources have none
);
CREATE TABLE person_roles (         -- a person in a role for a member; for speakers one row per speech
    person_id   INTEGER NOT NULL REFERENCES people(person_id),
    role        TEXT NOT NULL REFERENCES roles(role),
    code        TEXT,               -- the member's code; NULL if the name is not a member (e.g. an observer)
    recorded_as TEXT,               -- JSON list: the member's name(s) as given in the source
    session     TEXT,               -- for dated entries such as speeches, e.g. a General Assembly session
    date        TEXT,               -- YYYY-MM-DD
    document    TEXT,               -- a related document, e.g. the meeting record of a speech
    notes       TEXT,               -- JSON list: functions, e.g. 'Security Council President (Mar. 2018)'
    details     TEXT,               -- JSON: source-specific fields
    record_url  TEXT,               -- the entry's own record, if it has one (e.g. a speech)
    matched_by  TEXT                -- NULL: the entry names this person; otherwise how it was linked
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
CREATE VIRTUAL TABLE people_fts USING fts5(      -- name search; rowid = person_id
    names,
    content = '',
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

INDEXES = """
CREATE INDEX decisions_lookup ON decisions(lookup_key);
CREATE INDEX decisions_body_date ON decisions(body_id, date);
CREATE INDEX members_code ON members(code);
CREATE INDEX votes_member ON votes(member_id, decision_id);
CREATE INDEX person_roles_person ON person_roles(person_id);
CREATE INDEX person_roles_code ON person_roles(code, role);
CREATE INDEX person_roles_role ON person_roles(role, session);
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
        # The newest decision or dated role (e.g. a speech); a source without either keeps the
        # date given by its loader.
        self.conn.execute(
            """UPDATE sources SET data_until = COALESCE((
                   SELECT MAX(date) FROM decisions d
                   WHERE d.source_id = sources.source_id OR d.votes_source_id = sources.source_id), (
                   SELECT MAX(r.date) FROM person_roles r JOIN roles USING (role)
                   WHERE roles.source_id = sources.source_id),
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

    def add_role(self, role: str, notes: str | None = None, source_id: str | None = None, *,
                 listed_with_member: bool = False) -> None:
        """A kind of role, e.g. 'Permanent Representative'. With `listed_with_member` the people in
        this role are listed in a member's profile; otherwise they are only counted there."""
        self.conn.execute(
            "INSERT OR REPLACE INTO roles VALUES (?, ?, ?, ?)",
            (role, notes, int(listed_with_member), source_id),
        )

    def add_person(self, name: str, *, salutation: str | None = None,
                   other_names: list[str] | None = None, record_url: str | None = None) -> int:
        """Add one person and return their id. Their names are searchable."""
        cursor = self.conn.execute(
            "INSERT INTO people (name, salutation, other_names, record_url) VALUES (?,?,?,?)",
            (name, salutation, _json(other_names), record_url),
        )
        person_id = int(cursor.lastrowid)
        self.conn.execute(
            "INSERT INTO people_fts (rowid, names) VALUES (?, ?)",
            (person_id, " ".join([name, *(other_names or [])])),
        )
        return person_id

    def add_person_role(self, person_id: int, role: str, code: str | None, *,
                        recorded_as: list[str] | None = None, session: str | None = None,
                        date: str | None = None, document: str | None = None,
                        notes: list[str] | None = None, details: dict | None = None,
                        record_url: str | None = None, matched_by: str | None = None) -> None:
        """A person in a role for a member (add the role first). `code` is None when the member's
        name is not a member in the data, e.g. an observer. Dated entries, such as speeches, get
        one row each. `matched_by` says how the entry was linked to the person when it does not
        name them itself, e.g. 'name and Member State'."""
        details = {k: v for k, v in (details or {}).items() if v not in (None, "", [], {})}
        self.conn.execute(
            """INSERT INTO person_roles (person_id, role, code, recorded_as, session, date, document,
                   notes, details, record_url, matched_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (person_id, role, code, _json(recorded_as), session, date, document, _json(notes),
             _json(details), record_url, matched_by),
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
        """People listed in a member's profile (roles added with `listed_with_member`), grouped
        by role in the order the roles were added, then by name."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT r.role, p.name, p.salutation, p.other_names, r.recorded_as, r.notes,
                          p.record_url, ro.notes AS role_notes, ro.source_id AS role_source_id
                   FROM person_roles r JOIN people p USING (person_id) JOIN roles ro USING (role)
                   WHERE r.code = ? AND ro.listed_with_member = 1
                   ORDER BY ro.rowid, p.name COLLATE NOCASE""",
                (code,),
            ).fetchall()

    def role_counts(self, code: str) -> list[sqlite3.Row]:
        """For the roles only counted in a member's profile: how many people and entries."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT ro.role, ro.source_id, COUNT(DISTINCT r.person_id) AS people,
                          COUNT(*) AS entries
                   FROM person_roles r JOIN roles ro USING (role)
                   WHERE r.code = ? AND ro.listed_with_member = 0
                   GROUP BY ro.role ORDER BY MIN(ro.rowid)""",
                (code,),
            ).fetchall()

    # --- people ---

    def roles(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM roles ORDER BY rowid").fetchall()

    def unmatched_member_names(self) -> list[str]:
        """Names in people's roles that are not a member in the data, e.g. observers."""
        with self.connect() as conn:
            return [row[0] for row in conn.execute(
                """SELECT DISTINCT j.value FROM person_roles r, json_each(r.recorded_as) j
                   WHERE r.code IS NULL ORDER BY j.value""")]

    def search_people(self, *, name: str | None = None, code: str | None = None,
                      member_names: list[str] | None = None, role: str | None = None,
                      session: str | None = None, limit: int = 10,
                      offset: int = 0) -> tuple[int, list[sqlite3.Row], list[sqlite3.Row]]:
        """People with at least one role entry that matches all given filters. Returns (total,
        page of people, all role entries of those people). Each entry has `matches` = 1 if it
        matches the filters on the entry (member, role, session), so a caller can show only those.

        `name`: words of a name or another form of it, in any order. `code`: a member;
        `member_names`: instead of a code, names of non-members as recorded (e.g. 'Holy See').
        People with dated entries come first, newest first; then the others by name.
        """
        entry_filters: list[str] = []
        entry_params: list = []
        if code:
            entry_filters.append("r.code = ?")
            entry_params.append(code)
        elif member_names:
            marks = ",".join("?" * len(member_names))
            entry_filters.append(
                f"r.code IS NULL AND EXISTS (SELECT 1 FROM json_each(r.recorded_as) WHERE value IN ({marks}))")
            entry_params += member_names
        for column, value in (("r.role", role), ("r.session", session)):
            if value:
                entry_filters.append(f"{column} = ?")
                entry_params.append(value)
        filters, params = list(entry_filters), list(entry_params)
        if name:
            filters.append("r.person_id IN (SELECT rowid FROM people_fts WHERE people_fts MATCH ?)")
            params.append(_fts_query(name))

        matched = ("SELECT r.person_id, MAX(r.date) AS last_date FROM person_roles r"
                   + (" WHERE " + " AND ".join(filters) if filters else "") + " GROUP BY r.person_id")
        entry_match = " AND ".join(entry_filters) or "1"
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM ({matched})", params).fetchone()[0]
            people = conn.execute(
                f"""SELECT p.*, m.last_date FROM ({matched}) m JOIN people p USING (person_id)
                    ORDER BY m.last_date IS NULL, m.last_date DESC, p.name COLLATE NOCASE, p.person_id
                    LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
            ids = [row["person_id"] for row in people]
            entries = conn.execute(
                f"""SELECT r.*, CASE WHEN {entry_match} THEN 1 ELSE 0 END AS matches,
                           ro.source_id AS role_source_id
                    FROM person_roles r JOIN roles ro USING (role)
                    WHERE r.person_id IN ({",".join("?" * len(ids))})
                    ORDER BY r.person_id, ro.rowid, r.date DESC, r.rowid""",
                [*entry_params, *ids],
            ).fetchall() if ids else []
        return total, people, entries

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
