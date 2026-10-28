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

**The hand walk, written before the matrix.**

I wrote this out before any model run crashed and committed it before running the matrix, so the Git history shows the order. The plan is: read the issue, search, read a file, open the PR, and post the comment. I checkpoint after steps 1, 2, and 3, then sync right before steps 4 and 5.

The crash I expect to be the worst is **`--die-during-step 5`**. The tracker commits the comment, but the process dies before it gets the acknowledgement. So the comment is public, the process never finds out it was posted, and the call record has no entry for it.

- **Last checkpoint:** The sync checkpoint immediately before step 5, saved after the PR was returned. In it, steps 1–4 are marked `done` and step 5 is `running`. `completed_calls` contains the four calls from steps 1–4, including the PR key. `findings` has the label, file, and the exact arguments for the comment. `current_step` is 5.

- **What happens between the checkpoint and the crash:** Nothing else happens in between, since the checkpoint is right before the write. Step 5, posting the comment, is the step running when the crash happens. This is the tricky case: the comment was posted, but the process doesn't know that.

- **What each step does on replay, and what prevents duplicates:**
  - Steps 1–4 are already `done` in the checkpoint. On resume, the run skips them and reuses their recorded results, so their side effects aren't repeated. The recorded result is enough to close those steps. In particular, the PR isn't opened again because its call is already in `completed_calls`.
  - Step 5 has a side effect: a public comment. It has already happened once, even though the process didn't get the acknowledgement. On resume, the system uses the **saved arguments**, not a newly generated comment. The key is derived from `hash(run_id, plan step 5, arguments)`, so it stays the same. Before trying the write, the registry checks the tracker for a comment with that key. It finds the one that's already been committed and returns it as "already there," without posting another comment. **The key is the only thing that closes this gap.** Nothing else in the code checks whether the comment already exists. The checkpoint matters because it preserves the arguments, which keeps the key the same.

I think this is the worst case because the write definitely reached the tracker, the process definitely didn't get confirmation, and only one mechanism prevents the replay from posting a second public comment. With random keys in Part C, I expect this exact case—and `--die-after-step 5`—to leave two comments.

### Predictions for the other cases (derived keys)

| Case | Last checkpoint | Replay window; last running step | Side effects in the window, and what prevents duplicates | Prediction |
|---|---|---|---|---|
| After 1, during 1 | None | The whole run, starting from the plan | No side effects have happened yet. The run starts over with the same `run_id` and replans. | 1 comment, 1 PR (if a file), matches |
| After 2, during 2 | After step 1 | Step 2 (search) | Search is a read, so there's no side effect. The fill call runs again and may choose a different query. | 1 comment, ≤1 PR, matches |
| After 3, during 3 | After step 2 | Step 3 (file read) | File read is a read, so there's no side effect. The fill call may choose a different path, which could change the triage from the original run, but it should still match its own findings. | 1 comment, ≤1 PR, matches |
| After 4, during 4 | Sync, immediately before step 4 | Step 4 (PR), which committed | The PR already exists. Replay uses the saved arguments, so the key is the same. The registry checks the branch first and finds the open PR from `repomind/issue-4201`; the branch check and key prevent another PR from being created. | 1 comment, 1 PR, matches |
| After 5, during 5 | Sync, immediately before step 5 | Step 5 (comment), which committed | The comment already exists. The registry finds it by key and returns it without writing again. | 1 comment, 1 PR, matches |

I don't expect any crash to repeat a tool call that happened before the last checkpoint. After resuming, the trace should pick up at the step after the last checkpoint: step 2 for a step-2 crash, step 3 for step 3, step 4 for step 4, and step 5 for step 5.

**The matrix, derived keys.**
The uncrashed run was `planned-4201-s01-323f1d`, run right after `make reset`. The previous state is in `tracker/archive/tracker-20261028-171719.db`. The plan had five steps: read the issue, search, read a file, open the PR, and post the comment. So the matrix tests N = 1 through 5, both after and during each step.

I got every count below directly from the tracker by `run_id`, using `Tracker().comments(run_id, 4201)` and `Tracker().prs(run_id, branch="repomind/issue-4201")`. These numbers aren't taken from the trace.

| Step | When | run_id | Comments | Open PRs | Matches its findings | Last checkpoint before the kill | Calls after resume (plan steps) |
|---|---|---|---|---|---|---|---|
| 1 | after | `planned-4201-s01-baf218` | 1 (#2) | 1 | yes: bug, `src/notifications/templates.ts` | none | 1–5 (started over and re-planned) |
| 1 | during | `planned-4201-s01-635019` | 1 (#3) | 1 | yes: bug, `src/notifications/templates.ts` | none | 1–5 (started over and re-planned) |
| 2 | after | `planned-4201-s01-425fe9` | 1 (#4) | 1 | yes: bug, `src/notifications/templates.ts` | after 1 | 2–5 |
| 2 | during | `planned-4201-s01-ed1927` | 1 (#5) | 1 | yes: bug, `src/notifications/templates.ts` | after 1 | 2–5 |
| 3 | after | `planned-4201-s01-ef5bee` | 1 (#6) | 1 | yes: bug, `src/notifications/templates.ts` | after 2 | 3–5 |
| 3 | during | `planned-4201-s01-7ff2e2` | 1 (#7) | 1 | yes: bug, `src/notifications/templates.ts` | after 2 | 3–5 |
| 4 | after | `planned-4201-s01-e91efc` | 1 (#8) | 1 | yes: bug, `src/notifications/templates.ts` | before 4 (sync) | 4 (PR `already there`, same key), 5 |
| 4 | during | `planned-4201-s01-7e6be3` | 1 (#9) | 1 | yes: bug, `src/notifications/templates.ts` | before 4 (sync) | 4 (PR `already there`, same key), 5 |
| 5 | after | `planned-4201-s01-11a955` | 1 (#10) | 1 | yes: bug, `src/notifications/templates.ts` | before 5 (sync) | 5 (comment `already there`, same key) |
| 5 | during | `planned-4201-s01-c23af6` | 1 (#12) | 1 | yes: bug, `src/notifications/templates.ts` | before 5 (sync) | 5 (comment `already there`, same key) |

All 10 cases ended with exactly one triage comment and one open PR. Each comment also matched the findings from its own last checkpoint: `bug` and `src/notifications/templates.ts`, the same findings as the uncrashed run. No resumed run repeated a tool call that had completed before its last checkpoint (`make check-04`, "Resume, not restart", 8/8).

The replayed writes are visible in the call records. After a step-4 kill, the PR attempt returned `already there` with the same key as the original attempt. After a step-5 kill, the comment did the same. In both step-4 cases and both step-5 cases, the resumed run made **no model call**. The saved arguments were enough.

Three things to report:

- **One crashed run had a different plan.** The first `during 5` case, `planned-4201-s01-a10b62`. Its first search used the issue's own wording and found no source file, then two revisions retried it (reset-password, reset_password, both 0 hits) and the second added another search step (localhost), so its plan grew to six steps. That meant step 5 was the **PR**, not the comment, and the kill happened as the PR committed. It still ended with one comment and one PR because the replay found the PR by its branch. I ran `during 5` again with `planned-4201-s01-c23af6`, which had the intended five-step plan, so the kill would land on the comment—the worst case from the hand walk. The checker uses this later run.

- **I kept the first matrix too.** I ran the matrix once before, after the uncrashed run `planned-4201-s01-4c1244`, archived in `tracker/archive/tracker-20261028-171214.db`. That matrix also ended with one comment and one PR in every case. The problem was that 7 of its 11 runs posted comments containing `label: $fill / file: $fill`. The planner had put the comment arguments in as a template (`"label: $fill\nfile: $fill\n\n$fill"`), but the starter executor treated the template as already filled and posted it as-is. I fixed this in `ways/planned.py` with `unfilled()`, so any argument containing `$fill` gets filled, then ran `make reset` and reran the matrix above. The first matrix is still useful evidence: the drafts were wrong, but no crash caused a duplicate write. That protection comes from the key and the arguments saved in the checkpoint, not from the quality of the draft.

- **A step-1 crash starts the run over.** A checkpoint isn't saved until step 1 returns, so a kill during or just after step 1 leaves no checkpoint. The run re-plans and executes every step again under the same `run_id`. Since nothing had been written yet, nothing was duplicated.

## Part C · Break it on purpose

`make reset` (Part B's tracker is archived in `tracker/archive/tracker-20261028-173410.db`),
then the same ten cases with `KEY_MODE=uuid` on every crashed run. Each resume kept the
run's own switches: every `resume` line records `key_mode: uuid`. The code and the
checkpoints are the same as in Part B. Counts are read from the tracker by `run_id`.

| Step | When | run_id | Comments | Comment IDs | Open PRs | Matches its findings | What the call record and tracker show |
|---|---|---|---|---|---|---|---|
| 1 | after | `planned-4201-s01-c9e58d` | 1 | #1 | 1 | yes |  |
| 1 | during | `planned-4201-s01-3e0a6e` | 1 | #2 | 1 | yes |  |
| 2 | after | `planned-4201-s01-b21a5c` | 1 | #3 | 1 | yes |  |
| 2 | during | `planned-4201-s01-ee981c` | 1 | #4 | 1 | yes |  |
| 3 | after | `planned-4201-s01-c9e9dc` | 1 | #5 | 1 | yes |  |
| 3 | during | `planned-4201-s01-f7cfbd` | 1 | #6 | 1 | yes |  |
| 4 | after | `planned-4201-s01-4fff4a` | 1 | #7 | 1 | yes | the replayed PR carried a new key (`aaf2a41a…` against the first `7d49cf4c…`) and was found by its branch: `already there` |
| 4 | during | `planned-4201-s01-fd0c3c` | 1 | #8 | 1 | yes | the PR committed during the kill; the replay, with a new key, was found by its branch: `already there` |
| 5 | after | `planned-4201-s01-ae6b0a` | 2 | #9, #10 | 1 | no | the comment returned with key `7d32b5fc…`; the replay sent `52487cb8…`, which the check by key could not find |
| 5 | during | `planned-4201-s01-5a6774` | 2 | #11, #12 | 1 | no | the comment committed during the kill with key `d045c8cb…`; the replay sent `d6a2a0d2…` |

**Which N produce a second comment: N = 5, after and during, and only those.** The
tracker holds comments #9 and #10 for `planned-4201-s01-ae6b0a`, with keys
`7d32b5fceec548549a07b10a` and `52487cb872644b3cb2980b69`, and comments #11 and #12 for
`planned-4201-s01-5a6774`, with keys `d045c8cbb20b40f7a376f7af` and
`d6a2a0d2fdce48ab8daaf80d`. Same run, same body (`label: bug / file:
src/notifications/templates.ts`), two keys. For N = 1 to 3 the comment had not been
posted when the process died, so there was nothing to double. For N = 4 the PR had
been opened, and the replay sent it with a new random key. The registry's check
before `open_pr` reads by **branch**, not by key, so it found the open PR from
`repomind/issue-4201` and wrote nothing. No case left a second PR, as expected.

**What the checkpoint did, and what the key did.** The checkpoint did the same thing in
Part C as in Part B. It decided where each replay started (the step after the last
save) and how much ran again. Steps 1 to 4 were never called again after a step-5
kill, and the comment was replayed with exactly the arguments saved before it, with
no new model call. So the checkpoint bounded the replay window to the one running
write, and it handed the replay the same body both times. That was not enough. With
the same checkpoints, the same arguments, the same replay window and the same code, the
tracker holds one comment per run in Part B and two per run at N = 5 here. The only
thing that changed was the key. With a derived key the replayed comment carried
`hash(run, step, arguments)`, the key the committed comment already had, so the check
before the attempt found it. With a random key it carried a key the tracker had never
seen, and nothing else in the system looks for an existing comment. The PR, the one
write checked by something other than its key, did not double. The checkpoint narrows
what replays, and only the key decides whether a replayed write writes again. That is
slide 47's callout, "the key, not the checkpoint", measured on one run.

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
