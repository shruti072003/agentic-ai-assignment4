# Assignment 4 · Kill it and resume: state, keys and a memory with provenance

Model: OpenAI gpt-4.1-mini (`provider: openai-compatible`, served as gpt-4.1-mini-2025-04-14), the same for every run.

## Part A · Mark the plan, place the checkpoints

The plan, from the `plan` line of a run of issue 4201: read the issue, search, read a
file, open the draft PR, post the comment. A checkpoint here is a save of the run's
state (`state/checkpointer.py`), not Assignment 2's revision point after the first
search, where nothing is saved.

| Step | Tool | Kind | Checkpoint |
|---|---|---|---|
| 1 | `issues_read` (read the issue) | read | after: it holds the validated plan, the planner's model call, so a crash after step 1 never re-plans (a re-plan can choose a different plan, with different step numbers) |
| 2 | `code_search` (search) | read | after: a fill call wrote its query, and Assignment 2's revision check may have changed the plan; saved once the revision is settled |
| 3 | `code_read_file` (read a file) | read | after: a fill call chose the path; the draft that follows reads this file's text from the checkpoint, not from a second read |
| 4 | `pulls_open` (open the draft PR) | keyed write | before, sync: holds the comment's checked draft (label, file) and the PR's filled title and body, so a replay sends the same arguments, and so the same derived key |
| 5 | `issues_comment` (post the comment) | keyed write | before, sync: holds the comment's arguments, so a replay posts the same body with the same key |

Every checkpoint holds slide 14's five fields and nothing else: `plan`, `step_status`
(the write about to run is `running`), `completed_calls` (each `{step, tool, args, key,
result}`, the result cut to the 6,000 characters a later fill call is shown),
`findings` (`label`, `file`, the comment's arguments, the PR's arguments, and the
bookkeeping a resume needs: plan version, revisions, model-call count) and
`current_step`. The conversation is not in it: this way sends each model call one fresh
message built from these fields, so there is no conversation to save.

The replay window: each write has a sync checkpoint immediately before it, so a crash
can leave at most one irreversible write inside the window, the one that was running.
Placing checkpoints does not settle whether that write happened. Its key does, or for
the PR its branch, when the registry checks the tracker before it tries again.

- **Durability mode, and why: `sync`**, for the whole run (`DURABILITY` in
  `ways/planned.py`). Slide 12 says to use sync for any run with an irreversible step,
  and this plan has two. The key on each write is a hash of the run, the plan step and
  the arguments. The model wrote those arguments, so they must be on disk before the
  write runs. With `async`, a crash in the gap before the save lands would make the
  resume ask the model to draft again. With `exit`, every crash loses everything. Either
  way the replay could send new arguments with a new key, and the tracker would take it
  as a new write. Sync costs a little latency: a few SQLite commits with
  `synchronous=FULL`, next to model calls that take seconds.
- **The weaker of the two writes, and why: the comment.** Each write is checked before
  every attempt. The PR is checked by its **branch** (`repomind/issue-<n>`, fixed by
  code, not by the model), and the comment only by its **key**
  (`tools/__init__.py`, `_existing`). If the PR's key were lost or changed (a uuid key,
  or new arguments from a fresh fill), the branch check would still find the PR already
  opened and stop a second one. If the comment's key were lost or changed, nothing
  would stop a second comment. The comment also cannot be undone. A PR is a draft that
  someone can close, but a comment can be read by the issue's author the moment it
  posts. That is why it goes last (Lecture 3, slide 41), and why it is weak: the only
  thing that keeps it to one is its key.

## Part B · Kill it at every step

**The hand walk, written before the matrix.** The crash you expect to be worst:

- Its last checkpoint:
- The steps between it and the crash, and the step running at the crash:
- For each: its side effect, and what closes it (a key, a recorded result, or nothing):

**The matrix, derived keys.** Uncrashed run:

| Step | When | run_id | Comments | Open PRs | Matches its findings |
|---|---|---|---|---|---|

## Part C · Break it on purpose

| Step | When | run_id | Comments | Comment IDs | Open PRs |
|---|---|---|---|---|---|

What the checkpoint did, and what the key did:

## Part D · A memory that can say where it came from

- The write policy, in brief:
- The three candidates, and how each was stored:

| Candidate | Stored? | Kind | source | origin | confirmed | Invites |
|---|---|---|---|---|---|---|
| A | | | | | | |
| B | | | | | | |
| C | | | | | | |

- Eviction: the size, the rule, and how long an entry lives at your write rate:

| Issue 4207, five runs each | With the store | Empty store |
|---|---|---|
| Passes | | |
| Mean tool calls | | |
| Mean tokens | | |

## Part E · Answer from your own runs

1. Your prediction against the matrix:
2. The contradiction test, and the record IDs the third session retrieved:
3. What your checkpoint cost, structured and with the conversation, and over how many runs:
4. Is what you built durable execution?
5. Which abstraction?

## Part F · Find the boundary that lost it

The fact, word for word, and what the comment states when a run uses it:

| Case | The lost run | Where it lost the fact (trace and request record) | The fix | The fixed run |
|---|---|---|---|---|
| Attention | | | | |
| Compaction | | | | |
| The session | | | | |

The session case's stated run:

## AI assistance

Which tool, what it wrote, and what you checked.
