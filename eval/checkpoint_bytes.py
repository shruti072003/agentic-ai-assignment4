"""Assignment 4, Part E, task 3: what one run's checkpoints cost on disk.

    python eval/checkpoint_bytes.py <run_id> ...

For each run, the summed length of every checkpoint it saved: the structured ones in
state/checkpoints.db (Checkpointer.size), and the copies with the conversation that
CONVERSATION_COPY=state/checkpoints_with_conversation.db wrote beside them. Then the
mean of each over the runs given.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from state.checkpointer import Checkpointer  # noqa: E402

COPY = ROOT / "state" / "checkpoints_with_conversation.db"


def main(run_ids: list[str]) -> int:
    cp, db = Checkpointer(), sqlite3.connect(COPY)
    rows = []
    for rid in run_ids:
        (with_conv, n) = db.execute("SELECT COALESCE(SUM(LENGTH(data)), 0), COUNT(*) FROM checkpoints WHERE run_id = ?",
                                    (rid,)).fetchone()
        rows.append({"run_id": rid, "checkpoints": len(cp.all(rid)), "copies": n, "structured": cp.size(rid),
                     "with_conversation": with_conv})
        print(json.dumps(rows[-1]))
    mean = {k: round(sum(r[k] for r in rows) / len(rows)) for k in ("structured", "with_conversation")}
    print(json.dumps({**mean, "runs": len(rows), "ratio": round(mean["with_conversation"] / mean["structured"], 2)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
