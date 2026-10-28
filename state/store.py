"""Assignment 4, Part D: the memory store.

A store is shared by every run, keyed by repository and issue: a SQLite file,
state/store.db, durable across processes. What enters it, and how, is
state/write_policy.md; this file enforces the parts of it code can hold:

  - every record carries its provenance: source (user, issue:<n>, repo or memory),
    written_at (ISO 8601, UTC), origin (derived or ingested) and confirmed;
  - text from an issue (source issue:<n>) is never confirmed and never semantic: it
    is a record of what the issue said, not of what is true (slide 24);
  - a contradicted fact is superseded, never appended beside: the new record names
    the old in `supersedes`, and the old goes inactive, so one is active (slide 25);
  - eviction (slides 25 and 27): expiry on access. An episodic record not written or
    used for EPISODIC_DAYS goes inactive when a read finds it; and no more than
    MAX_ACTIVE records stay active per repository, the least recently used going
    first. A record a person with standing stated (source user) never expires: it
    is only ever superseded.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.5):

    Store(path=None)                                  # None: state/store.db, or $REPOMIND_STORE
    .write(record) -> id                              # a new record; returns its id
    .supersede(old_id, record) -> id                  # a new record that replaces old_id
    .active(repository, issue=None) -> list[dict]     # the active records, for retrieval
    .records() -> list[dict]                          # every record, active or not

Two switches, both environment variables, and with both unset Store() is the real
store, which is how the checker opens it:

    REPOMIND_STORE=<path>   another file, for tests on a scripted model
    EMPTY_STORE=1           Store.for_run(run_id) gives each run a new, empty store
                            (state/empty/<run_id>.db): Part D's empty-store set, and
                            Part F's attention and compaction cases
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness import ROOT

DEFAULT = ROOT / "state" / "store.db"
EMPTY_DIR = ROOT / "state" / "empty"
REPOSITORY = "ledgerline"
KINDS = ("episodic", "semantic", "procedural")
ORIGINS = ("derived", "ingested")
SOURCE = re.compile(r"^(user|repo|memory|issue:\d+)$")
EPISODIC_DAYS = 90    # an episode not written or used in this long goes inactive when a read finds it
MAX_ACTIVE = 1000     # active records per repository; past it, the least recently used go inactive

COLUMNS = ("id", "repository", "issue", "kind", "text", "source", "written_at", "origin", "confirmed", "active",
           "supersedes", "stated_by", "topic", "used_at", "expired")
SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repository  TEXT NOT NULL,
    issue       INTEGER,
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    origin      TEXT NOT NULL,
    confirmed   INTEGER NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    supersedes  INTEGER REFERENCES records (id),
    stated_by   TEXT,
    topic       TEXT,
    used_at     TEXT,
    expired     TEXT
);
CREATE INDEX IF NOT EXISTS records_scope ON records (repository, issue, active);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def age(record: dict) -> str:
    """How old a record is, in words, for the context it goes into."""
    days = (datetime.now(timezone.utc) - parse_time(record["written_at"])).days
    return "today" if days < 1 else f"{days} day{'s' if days != 1 else ''} ago"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.environ.get("REPOMIND_STORE") or DEFAULT)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @classmethod
    def for_run(cls, run_id: str) -> "Store":
        """The store a run reads and writes: the real one, or with EMPTY_STORE=1 a new,
        empty one of its own, which no other run ever reads."""
        if os.environ.get("EMPTY_STORE") == "1":
            path = EMPTY_DIR / f"{run_id}.db"
            path.unlink(missing_ok=True)
            return cls(path)
        return cls()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _out(row: sqlite3.Row) -> dict:
        record = dict(row)
        record["confirmed"] = bool(record["confirmed"])
        record["active"] = bool(record["active"])
        return record

    # -- the write policy's rules that code holds --------------------------------------------
    @staticmethod
    def _checked(record: dict) -> dict:
        r = {k: record.get(k) for k in COLUMNS if k not in ("id", "active", "supersedes", "used_at", "expired")}
        r["repository"] = r.get("repository") or REPOSITORY
        r["written_at"] = r.get("written_at") or now()
        problems = []
        if r.get("kind") not in KINDS:
            problems.append(f"kind {r.get('kind')!r} is not one of {KINDS}")
        if not SOURCE.match(str(r.get("source") or "")):
            problems.append(f"source {r.get('source')!r} is not user, repo, memory or issue:<n>")
        if r.get("origin") not in ORIGINS:
            problems.append(f"origin {r.get('origin')!r} is not one of {ORIGINS}")
        if not isinstance(r.get("confirmed"), bool):
            problems.append("confirmed must be true or false")
        if not str(r.get("text") or "").strip():
            problems.append("a record has text")
        try:
            parse_time(r["written_at"])
        except ValueError:
            problems.append(f"written_at {r['written_at']!r} is not ISO 8601")
        if str(r.get("source") or "").startswith("issue:"):   # text anyone can write (slide 24)
            if r.get("confirmed") or r.get("kind") == "semantic" or r.get("origin") != "ingested":
                problems.append("text from an issue is stored ingested, unconfirmed and never as a semantic fact")
        if problems:
            raise ValueError("this record breaks the write policy: " + "; ".join(problems))
        r["confirmed"] = int(r["confirmed"])
        return r

    def _insert(self, db: sqlite3.Connection, r: dict, supersedes=None) -> int:
        cur = db.execute(
            "INSERT INTO records (repository, issue, kind, text, source, written_at, origin, confirmed, active, "
            "supersedes, stated_by, topic, used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (r["repository"], r.get("issue"), r["kind"], r["text"], r["source"], r["written_at"], r["origin"],
             r["confirmed"], supersedes, r.get("stated_by"), r.get("topic"), r["written_at"]))
        return cur.lastrowid

    # -- the interface -----------------------------------------------------------------------
    def write(self, record: dict):
        r = self._checked(record)
        with self._connect() as db:
            new = self._insert(db, r)
            self._cap(db, r["repository"])
        return new

    def supersede(self, old_id, record: dict):
        """A new record that replaces old_id: the old one stays, inactive, and is named."""
        r = self._checked(record)
        with self._connect() as db:
            old = db.execute("SELECT id, active FROM records WHERE id = ?", (int(old_id),)).fetchone()
            if old is None:
                raise KeyError(f"no record {old_id!r} to supersede")
            db.execute("UPDATE records SET active = 0 WHERE id = ?", (int(old_id),))
            new = self._insert(db, r, supersedes=int(old_id))
        return new

    def active(self, repository: str, issue: int | None = None) -> list[dict]:
        """With no issue, every active record of the repository; with one, that issue's
        and every repository-wide record. Expiry on access runs first."""
        with self._connect() as db:
            self._expire(db, repository)
            if issue is None:
                rows = db.execute("SELECT * FROM records WHERE repository = ? AND active = 1 ORDER BY id",
                                  (repository,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM records WHERE repository = ? AND active = 1 AND "
                                  "(issue IS NULL OR issue = ?) ORDER BY id", (repository, int(issue))).fetchall()
        return [self._out(r) for r in rows]

    def records(self) -> list[dict]:
        with self._connect() as db:
            return [self._out(r) for r in db.execute("SELECT * FROM records ORDER BY id")]

    # -- helpers for the way and the scripts ---------------------------------------------------
    def find(self, repository: str, *, issue=None, source=None, topic=None, text=None) -> list[dict]:
        """Active records matching every filter given."""
        out = []
        for r in self.active(repository, issue):
            if issue is not None and r["issue"] != issue:
                continue
            if (source is None or r["source"] == source) and (topic is None or r["topic"] == topic) \
                    and (text is None or r["text"] == text):
                out.append(r)
        return out

    def used(self, ids: list) -> None:
        """Mark records as used now: a read keeps them from expiring."""
        if ids:
            with self._connect() as db:
                db.executemany("UPDATE records SET used_at = ? WHERE id = ?", [(now(), int(i)) for i in ids])

    # -- eviction ------------------------------------------------------------------------------
    def _expire(self, db: sqlite3.Connection, repository: str) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=EPISODIC_DAYS)
        for row in db.execute("SELECT id, used_at, written_at FROM records WHERE repository = ? AND active = 1 "
                              "AND kind = 'episodic'", (repository,)).fetchall():
            if parse_time(row["used_at"] or row["written_at"]) < cutoff:
                db.execute("UPDATE records SET active = 0, expired = ? WHERE id = ?", (now(), row["id"]))

    def _cap(self, db: sqlite3.Connection, repository: str) -> None:
        rows = db.execute("SELECT id FROM records WHERE repository = ? AND active = 1 AND source != 'user' "
                          "ORDER BY COALESCE(used_at, written_at) DESC, id DESC", (repository,)).fetchall()
        for row in rows[MAX_ACTIVE:]:
            db.execute("UPDATE records SET active = 0, expired = ? WHERE id = ?", (now(), row["id"]))
