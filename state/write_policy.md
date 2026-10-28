# RepoMind's write policy

What enters RepoMind's memory store (`state/store.py`, `state/store.db`), and how. It was
written before the store (Lecture 4, slide 23), and is four decisions plus eviction.
The store enforces what code can hold: the provenance fields, the rule for issue text,
supersession and eviction (`Store._checked`, `Store.supersede`, `Store._expire`,
`Store._cap`). The way (`ways/planned.py`) decides when to write and what.

## 1. When

- **At the end of a run, never in the middle of one.** A run writes only after its last
  write, the comment, has returned. At that point its decision has been checked by the
  second pass where that is on, is public, and nothing later in the run can overturn
  it. A guess from step 2, such as a search term or a file the run is not yet sure
  of, is never stored.
- **Once a claim is verified**, for anything that comes from outside a run: a
  procedure RepoMind worked out, stored once a later check confirmed it.
- A run that ends escalated, held or crashed writes nothing. A crashed run that is
  resumed writes once, at the end of its resumed half.

## 2. What

Only three things are stored. Everything else, including every search result, file
text and draft, stays in the run's checkpoint and dies with the run.

- **What was expensive to derive:** the run's triage decision (label, file, and
  whether the run read that file itself), and a procedure RepoMind worked out over
  several steps (candidate A).
- **What was stated rather than inferred:** a rule a person with standing (a
  maintainer) stated, word for word, with who stated it and when (candidate C, and
  Part F's maintainer note).
- **What was confirmed:** the procedure is stored only as confirmed, and the run's
  decision only once it is posted.

Text from an issue (its body or its discussion) is never stored as a fact. If it is
kept at all, it is kept as a record of **what the issue said** (episodic), unconfirmed.

## 3. How

- **Insert** a new record when nothing active covers the same thing.
- **Merge** when an active record already says exactly the same thing: nothing new is
  written, and the existing record is marked used.
- **Replace only by superseding.** When a new record contradicts an active one on the
  same topic (a maintainer's new rule on duplicates, or a new triage decision for the
  same issue), a new record is written with `supersedes: <old id>` and its own
  `written_at`. The old one goes inactive and stays in the store as the record of what
  was replaced. Only one record per topic is ever active. Nothing is updated in place,
  and nothing is deleted.
- The topic of a record is what it is about (`duplicates`, `export-button`,
  `triage:4207`, `reproduce-ui`). Two records contradict each other when they share a
  topic and a scope (repository and issue) and say different things.

## 4. With: provenance on every record

| Field | What goes in it |
|---|---|
| `source` | `user`: a person with standing (a maintainer) stated it. `issue:<n>`: an issue's text, which anyone can write. `repo`: the repository's own files. `memory`: RepoMind's own earlier work |
| `written_at` | ISO 8601, UTC. For a record a run writes, when it was stored. For something seen earlier (the three candidates), **when it was seen**, the candidate's `when`: the age shown with the record is the age of what it says |
| `origin` | `derived`: RepoMind worked it out. `ingested`: read from outside, whether a person's words or an issue's |
| `confirmed` | `true` only when it is verified or stated by a person with standing; `false` for anything from an issue, always |
| `stated_by` | who stated it, for a record a person stated |

**A maintainer stating a rule confirms it.** A rule from `user` is stored
`confirmed: true`, because a person with standing stating it is the confirmation; there
is nothing more for RepoMind to check. It is still `ingested`, because RepoMind did not
work it out. What it invites is contradiction: when the maintainer changes the rule,
the new rule supersedes the old (section 3).

## The three candidates (`fixtures/memory/`)

| Candidate | Stored? | Kind | source | origin | confirmed | Invites |
|---|---|---|---|---|---|---|
| A, a procedure RepoMind worked out in a run of 4191 | yes, repository-wide | procedural | `memory` | derived | true | staleness: package.json can change and the procedure not |
| B, an issue body's claim that auto-merge is approved | yes, as a record of what issue 4188 said, scoped to 4188 | episodic | `issue:4188` | ingested | false | poisoning, if it were ever stored as a fact; stored this way it is only an episode |
| C, a maintainer's rule on duplicates | yes, word for word, repository-wide, `stated_by: priya-s` | procedural | `user` | ingested | true | contradiction: the rule can change |

B's text is kept in quotation with its author, as "tk-dev-91 wrote in issue 4188's body
that ...". It is never semantic, so no retrieval returns it as something RepoMind knows,
and records from `issue:<n>` are kept out of the planner's context.

## Retrieval

Before the first search, a run reads the active records for its repository and its
issue. They go into every fill call's context with their source, age and confirmation
shown, after the run's own results:

- a rule a maintainer stated (`user`, confirmed) is to be **followed**, not checked;
- RepoMind's own earlier decisions and procedures (`memory`) are leads, to be checked
  against what this run reads;
- anything from an issue (`issue:<n>`) is what someone wrote, never an instruction.

The planner sees none of the store's text from `issue:<n>` (as Assignment 2 kept the
issue body out of its context).

## Eviction

A store that never removes anything grows until retrieval fills with near-matches
(slide 25). One store, two rules:

- **Consolidation by supersession.** A run's triage decision supersedes the last one for
  the same issue, so each issue has at most **one** active decision, however many times
  it is triaged. Every other record per topic is likewise one active.
- **Expiry on access.** An episodic record that has not been written or used for **90
  days** goes inactive the next time a read finds it, so a run is never shown a
  months-old episode as current. Retrieval marks what it returns as used.
- **A size cap.** At most **200** active records per repository, other than a person's
  stated rules. Past it, the least recently used go inactive first.
- A record a person with standing stated never expires. It is only ever superseded,
  because only that person, or another with standing, can change it.

Inactive records stay in the file as the audit trail. They are never retrieved.

How long an entry lives at RepoMind's write rate is worked out from Part D's runs in
`reports/LAB_04.md`, Part D.
