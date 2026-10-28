"""Assignment 4, Part D: put the three candidate memories (fixtures/memory/) through the
write policy (state/write_policy.md) and into the store.

    python eval/store_candidates.py

One session: it opens the store, writes what the policy keeps, prints each record and
exits. It is also the first of Part E's three contradiction-test sessions: it stores
the maintainer's rule on duplicates. Run again, it writes nothing new: a record the
store already holds, word for word, is merged (section 3 of the policy), not appended.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from state.store import REPOSITORY, Store  # noqa: E402

MEMORY = ROOT / "fixtures" / "memory"


def load(name: str) -> dict:
    return yaml.safe_load((MEMORY / name).read_text())


def procedure_holds() -> bool:
    """Candidate A is stored only once verified: package.json has start, build, test and
    lint, and no serve, as the procedure says."""
    scripts = json.loads((ROOT / "fixtures" / "repo" / "package.json").read_text()).get("scripts") or {}
    return {"start", "build", "test", "lint"} <= set(scripts) and "serve" not in scripts


def decide() -> list[dict]:
    a, b, c = load("a_procedure.yaml"), load("b_issue_claim.yaml"), load("c_maintainer_rule.yaml")
    records = []
    # A: worked out by RepoMind in a run, so derived, from memory; dated when it was seen;
    # stored only once verified against the repository. It invites staleness.
    if procedure_holds():
        records.append({"repository": a["repository"], "issue": None, "kind": "procedural",
                        "text": a["seen"].strip(), "source": "memory", "written_at": a["when"],
                        "origin": "derived", "confirmed": True, "topic": "reproduce-ui",
                        "stated_by": None})
    # B: an issue body, written by an account outside the team. Stored only as what the
    # issue said (episodic), scoped to that issue, ingested and unconfirmed: never as a fact.
    records.append({"repository": b["repository"], "issue": b["issue"], "kind": "episodic",
                    "text": f"{b['who']} wrote in {b['where']}: \"{' '.join(b['seen'].split())}\" "
                            "Not confirmed by any maintainer.",
                    "source": f"issue:{b['issue']}", "written_at": b["when"], "origin": "ingested",
                    "confirmed": False, "topic": "auto-merge", "stated_by": None})
    # C: a maintainer's rule, word for word, with who stated it and when. A person with
    # standing stating it is what confirms it. It applies to the whole repository.
    records.append({"repository": c["repository"], "issue": None, "kind": "procedural",
                    "text": c["seen"].strip(), "source": "user", "written_at": c["when"],
                    "origin": "ingested", "confirmed": True, "topic": "duplicates",
                    "stated_by": f"{c['who']}, in {c['where']}"})
    return records


def main() -> int:
    store = Store()
    for record in decide():
        same = store.find(REPOSITORY, issue=record["issue"], topic=record["topic"], text=record["text"])
        if same:
            print(f"merged   #{same[0]['id']} {record['topic']}: already held, word for word")
            continue
        new = store.write(record)
        print(f"written  #{new} {record['kind']:<10} {record['source']:<11} {record['origin']:<8} "
              f"confirmed={record['confirmed']!s:<5} {record['topic']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
