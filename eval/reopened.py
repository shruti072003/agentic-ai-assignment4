"""Assignment 4, Part D: the reopened issue, 4207, measured.

    python eval/reopened.py <run_id> ...

For each run: its tool calls (tool_call lines), its tokens (run_end.totals.total_tokens),
whether it passes Assignment 1's check() (eval/check_triage.py, read from the tracker by
run_id), the file its comment names, whether the run read that file itself, and what its
store read returned. Then the set's means, in the shape reports/LAB_04.json wants.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.check_triage import check  # noqa: E402
from harness.formats import parse_triage_comment  # noqa: E402
from harness.roles import role_of  # noqa: E402
from harness.tracker import Tracker  # noqa: E402

ISSUE = 4207


def measure(run_id: str, tracker: Tracker, answer: dict) -> dict:
    records = [json.loads(line) for line in (ROOT / "runs" / f"{run_id}.jsonl").read_text().splitlines()]
    calls = [r for r in records if r["type"] == "tool_call"]
    read = {p for r in calls if role_of(r["name"]) == "read_file" and not r["is_error"] for p in r["paths"]}
    end = next(r for r in reversed(records) if r["type"] == "run_end")
    comments = tracker.comments(run_id, ISSUE)
    label, file = parse_triage_comment(comments[0]["body"]) if comments else (None, None)
    memory = next((r["records"] for r in records if r["type"] == "store_read"), None)
    return {"run_id": run_id, "tool_calls": len(calls), "tokens": end["totals"]["total_tokens"],
            "passes": check(tracker, run_id, ISSUE, answer), "label": label, "file": file,
            "file_read_in_run": file in read, "store_read": memory,
            "searches": [r["input"].get("query") for r in calls if role_of(r["name"]) == "search"]}


def main(run_ids: list[str]) -> int:
    answer = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"][ISSUE]
    tracker = Tracker()
    rows = [measure(r, tracker, answer) for r in run_ids]
    for row in rows:
        print(json.dumps(row))
    print(json.dumps({"runs": len(rows), "passes": sum(r["passes"] for r in rows),
                      "mean_tool_calls": round(sum(r["tool_calls"] for r in rows) / len(rows), 2),
                      "mean_tokens": round(sum(r["tokens"] for r in rows) / len(rows), 1),
                      "run_ids": run_ids}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
