"""Assignment 4, Part A: the checkpointer.

A checkpointer saves one run's state, so its checkpoints are keyed by the run's
run_id (frameworks call one run's line of checkpoints a thread). They live in a
SQLite file, state/checkpoints.db: durable, and shared by every process, so a run
killed with kill -9 can be resumed by the next one. An in-memory store would die
with the process.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.4):

    Checkpointer(path=None)                    # None: state/checkpoints.db
    .save(run_id, checkpoint, *, step, mode)   # one checkpoint; mode is sync, async or exit
    .last(run_id) -> dict | None               # the run's latest checkpoint, or None
    .all(run_id) -> list[dict]                 # every checkpoint the run saved, oldest first
    .runs() -> list[str]                       # every run_id that has a checkpoint

A checkpoint is a dict of exactly the five fields in harness.formats.CHECKPOINT_FIELDS:
plan, step_status, completed_calls (each with its idempotency key), findings and
current_step. save() refuses anything else, and refuses a checkpoint that holds the
conversation, so that what is on disk is what a resume needs and no more (slide 14).

The durability mode (slide 12) says how a save is written:

    sync   committed, with SQLite's synchronous=FULL, before save() returns: the
           next step starts only once the checkpoint is on disk. Slowest, safest.
    async  handed to a background thread, and save() returns at once: a crash in
           the gap before the thread commits loses that checkpoint.
    exit   kept in memory until flush() at the end of the run: fastest, and a
           crash loses every one of them.

RepoMind runs sync, one mode for the whole run, because its plan has irreversible
steps (ways/planned.py, DURABILITY). The trace line for each save,
trace.event("checkpoint", step=..., mode=...), is written by the way.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from pathlib import Path

from harness import ROOT
from harness.formats import CHECKPOINT_FIELDS, DURABILITY_MODES

DEFAULT = ROOT / "state" / "checkpoints.db"
CONVERSATION_KEYS = {"conversation", "messages", "history", "transcript"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL,
    step      TEXT,
    mode      TEXT NOT NULL,
    saved_at  TEXT NOT NULL,
    data      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checkpoints_run ON checkpoints (run_id, id);
"""


def holds_conversation(node) -> bool:
    """A key that names the conversation, or a chat message (role and content), anywhere."""
    if isinstance(node, dict):
        if CONVERSATION_KEYS & {str(k).lower() for k in node} or {"role", "content"} <= set(node):
            return True
        return any(holds_conversation(v) for v in node.values())
    if isinstance(node, list):
        return any(holds_conversation(v) for v in node)
    return False


class Checkpointer:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
        self._held: list[tuple] = []           # exit mode: saves kept until flush()
        self._queue: queue.Queue | None = None  # async mode: saves waiting for the writer thread
        self._writer: threading.Thread | None = None

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")   # a commit is on disk before it returns
        return db

    # -- writing ---------------------------------------------------------------------------
    def save(self, run_id: str, checkpoint: dict, *, step, mode: str = "sync") -> None:
        if mode not in DURABILITY_MODES:
            raise ValueError(f"mode is one of {DURABILITY_MODES}, not {mode!r}")
        if not isinstance(checkpoint, dict) or set(checkpoint) != set(CHECKPOINT_FIELDS):
            raise ValueError(f"a checkpoint has exactly the fields {CHECKPOINT_FIELDS}")
        if holds_conversation(checkpoint):
            raise ValueError("a checkpoint never holds the conversation (slide 14)")
        row = (run_id, None if step is None else str(step), mode, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               json.dumps(checkpoint, sort_keys=True))   # raises if anything in it does not serialize
        if mode == "sync":
            self._insert([row])
        elif mode == "async":
            self._background(row)
        else:
            self._held.append(row)

    def _insert(self, rows: list[tuple]) -> None:
        with self._connect() as db:   # the with block commits
            db.executemany("INSERT INTO checkpoints (run_id, step, mode, saved_at, data) VALUES (?, ?, ?, ?, ?)", rows)

    def _background(self, row: tuple) -> None:
        if self._writer is None:
            self._queue = queue.Queue()
            self._writer = threading.Thread(target=self._drain, daemon=True)
            self._writer.start()
        self._queue.put(row)

    def _drain(self) -> None:
        while True:
            row = self._queue.get()
            try:
                self._insert([row])
            finally:
                self._queue.task_done()

    def flush(self) -> None:
        """The end of a run: write what exit mode held, and wait for async saves to land."""
        if self._held:
            self._insert(self._held)
            self._held = []
        if self._queue is not None:
            self._queue.join()

    # -- reading ---------------------------------------------------------------------------
    def all(self, run_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT data FROM checkpoints WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [json.loads(data) for (data,) in rows]

    def last(self, run_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT data FROM checkpoints WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                             (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def runs(self) -> list[str]:
        with self._connect() as db:
            return [r for (r,) in db.execute("SELECT DISTINCT run_id FROM checkpoints ORDER BY run_id")]

    def size(self, run_id: str) -> int:
        """The bytes one run's checkpoints take together: the summed length of what was saved (Part E)."""
        with self._connect() as db:
            (total,) = db.execute("SELECT COALESCE(SUM(LENGTH(data)), 0) FROM checkpoints WHERE run_id = ?",
                                  (run_id,)).fetchone()
        return int(total)
