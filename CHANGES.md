# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan written as data before the issue is read; a validator with four checks; an executor that runs only the plan's steps; one checkpoint that may revise the plan; a second pass before the comment; detectors and a diff over traces; a progress file and a compaction
- **Removed:** the model's choice of the next tool, in the planned way
- **Constrained:** every tool call to a step of a validated plan; revisions to steps not yet done; the comment to drafts that pass the second pass

## Assignment 3
- **Added:** five rewritten tool definitions with examples, among them open_pr; a boundary check before every call; errors that name the fix; harness-derived idempotency keys, a check before every write attempt and a read-back after a timeout; the call record; a fail-closed hook
- **Removed:** free-text tool descriptions and free-form filters; protocol detail in anything the model sees
- **Constrained:** every write to be safe to retry, and to a person when its outcome cannot be read back; the comment to the last write, after the PR

## Assignment 4
- **Added:** a checkpointer (SQLite, keyed by run_id: plan, step status, completed calls with their keys, findings, current step) and resume from the last checkpoint; a memory store whose records carry source, time, origin and confirmation, with supersession and eviction; a write policy (`state/write_policy.md`); the store read before the first search and the run's decision written at its end; Part F's switches for where a run is told a maintainer's rule, and a compaction that keeps the issue out of it
- **Removed:** state that lived only in the process: a killed run no longer loses its plan, its results or the arguments of the write it was making; and the starter's fill of only a leading `$fill`, which posted a template unfilled
- **Constrained:** every write to sit behind a sync checkpoint, for its own plan step, holding the arguments it will be sent, so a replay sends the same key; a replay to reuse recorded results and never ask the model for a write's arguments again; issue text to enter the store only as an unconfirmed episode, never a fact
