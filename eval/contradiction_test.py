"""Assignment 4, Part E, task 2: the contradiction test (Lecture 4, slide 25: "set a
fact, contradict it, check in a third session"), on the maintainer's rule on duplicates.

Three sessions, each a separate process that opens the store, does one thing and exits:

    python eval/store_candidates.py            # session 1 (Part D): stores priya-s's rule
    python eval/contradiction_test.py contradict   # session 2: the same maintainer's new rule supersedes it
    python eval/contradiction_test.py retrieve     # session 3: retrieves the rule on duplicates, and only that

Session 2's rule is made up for the test: stated by the same maintainer, about the
same thing (duplicates), stored as the first was (source user, ingested, confirmed),
and written with supersede(), so the first goes inactive and stays in the store.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from state.store import REPOSITORY, Store, now  # noqa: E402

TOPIC = "duplicates"
NEW_RULE = ("For duplicates: label them `duplicate`, link the original, and close them after 14 days "
            "if the reporter has not replied.")


def rule_on_duplicates(store: Store) -> list[dict]:
    """The maintainer's rule on duplicates: active, stated by a person, on that topic."""
    return [r for r in store.active(REPOSITORY) if r["source"] == "user" and r["topic"] == TOPIC]


def contradict() -> int:
    store = Store()
    current = rule_on_duplicates(store)
    if len(current) != 1:
        print(f"want exactly one active rule on duplicates to contradict; the store has {len(current)}")
        return 1
    old = current[0]
    if old["text"] == NEW_RULE:
        print(f"#{old['id']} already holds the new rule: nothing to supersede")
        return 0
    new = store.supersede(old["id"], {
        "repository": REPOSITORY, "issue": None, "kind": "procedural", "text": NEW_RULE, "source": "user",
        "written_at": now(), "origin": "ingested", "confirmed": True, "topic": TOPIC,
        "stated_by": "priya-s, a maintainer (the contradiction test's made-up rule)"})
    print(f"#{new} supersedes #{old['id']}: {NEW_RULE}")
    return 0


def retrieve() -> int:
    found = rule_on_duplicates(Store())
    print("retrieved", [r["id"] for r in found])
    for r in found:
        print(f"  #{r['id']} supersedes {r['supersedes']}, stated by {r['stated_by']}, {r['written_at']}: {r['text']}")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("contradict", "retrieve"):
        sys.exit("usage: python eval/contradiction_test.py contradict | retrieve")
    sys.exit(contradict() if action == "contradict" else retrieve())
