# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 42 to 44):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below is RepoMind as Assignment 4 left it.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:150` | present |
| Harness | The loop, with three bounds checked in code; a plan validated before it runs, and an executor that runs only the plan's steps | `agent/loop.py:38`, `ways/planned.py:207`, `ways/planned.py:333` | present |
| Tools | Five namespaced tools behind one registry: every call checked at the boundary before it runs; every write keyed by the harness, checked before each attempt and read back after a timeout; every attempt in the call record | `tools/__init__.py:166`, `tools/__init__.py:249`, `tools/__init__.py:254`, `tools/__init__.py:271`, `tools/__init__.py:315` | present |
| Memory & State | Within a run, the context each fill call is built from (and a progress file). Across a crash, a checkpointer: SQLite, keyed by run_id, the five fields and never the conversation, saved after each read and sync immediately before each write with that write's arguments; a resume replays from the last checkpoint, skipping done steps and replaying the running write with its saved arguments, so the same key. Between runs, a memory store whose every record carries source, time, origin and confirmation; issue text never stored as a fact; a contradicted rule superseded, not appended; expiry on access and a size cap; read before the first search, written at the end of a run | `state/checkpointer.py:92`, `state/checkpointer.py:88`, `ways/planned.py:172`, `ways/planned.py:580`, `ways/planned.py:553`, `ways/planned.py:671`, `state/store.py:125`, `state/store.py:168`, `state/store.py:215`, `ways/planned.py:422`, `ways/planned.py:441` | partial: nothing notices a crashed run or restarts it without a person (no supervisor), and the journal is only as fresh as the last checkpoint |
| Control & Policy | A hook runs before every call and denies when it fails; a write that cannot be confirmed goes to a person; the second pass holds a draft that still fails | `tools/__init__.py:221`, `ways/planned.py:298` | partial: the hook allows every call |
| Observability | One trace line per model call and per tool call, and the plan as data before it runs | `agent/loop.py:50`, `ways/planned.py:179` | partial: traces, no alerts |
| Evaluation | The grounded check reads the tracker, never the agent | `eval/check_triage.py:7` | partial: offline only |

**Empty layers: 0 of 7**, and five are partial.
