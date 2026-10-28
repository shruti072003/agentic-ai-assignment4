"""Assignment 3's working solution, over Assignment 2's planned way: the same plan,
boundary, checkpoint and second pass, with Assignment 3's tools and the PR step.
It ships in Assignment 4's starter in place of your own Assignment 3 code.

Assignment 3 changes four things here:
  - Tools are found by role (harness.roles), never by name: the names are the
    team's own (tools/roles.yaml).
  - The plan ends with the PR and then the comment (slide 41): the schema check
    wants exactly one comment step, the last, and exactly one PR step, right before
    it. A PR can be closed; a comment, once read, cannot be taken back. The comment
    is drafted, and passes the second pass, before the first write; the PR opens
    only when that draft names a file, and when it says none the step is skipped
    (status "skipped"), a condition the executor applies, not the model. The draft
    posts last.
  - The PR's issue and branch are the code's: repomind/issue-<n>, whatever the plan
    or the model wrote. The model fills only its title and body.
  - A write the registry cannot confirm (tools.Unverifiable, the third exit) ends
    the run escalated: a person on review duty decides.

The boundary: the executor runs the plan's steps in order and nothing else. Where a
step's arguments are "$fill", one model call fills them, offered that step's tool
alone; a call to any other tool is refused, traced as off_plan, and never runs.
Two tries without an on-plan call halt the run as escalated.

The planner's output is checked against agent/plan_schema.json (harness.schema)
before the four checks, and so is the rule about its comment step (above): a
vendor can accept "strict" and not enforce it, and a plan with no comment step
passes all four checks and posts nothing. A plan that breaks either is rejected
like one that fails a check.

The checkpoint, a check in code: after the first search step, and after any search
step a revision added or changed, until MAX_REVISIONS is spent, the search returned
at least one source file: a .ts or .tsx file under src/, not only documentation
(README.md, CHANGELOG.md, docs/) or translations (src/i18n/*.json). A revision never
changes a step that is done; it may change a failed step, which then runs again.

Part G's ways/notes.py extends this file without changing it: it subclasses
Executor and overrides its hooks, record() (after every step), context() (what
every executor call sees) and the class attribute critique, and asks its questions
once run() has returned, however the run ended.

The second pass, before the first write, in ctx.critique's mode: external runs
agent.critique.verify, code; self asks the model with agent.critique.self_critique.
A failing draft with a round left is rewritten by one call; a draft still failing
in the last round is held, and the run escalates having written nothing. One
comment, after the last round and the PR.

Assignment 4 adds saves of the run's state (state/checkpointer.py), which are not
Assignment 2's checkpoint above (the point where the plan may be revised; nothing is
saved there). Where they go is read from the plan (slide 13):
  - after each read (SAVE_AFTER): the read issue keeps the validated plan, the
    planner's call, so a crash after it never re-plans; the search and the file read
    each cost a fill call;
  - immediately before each write, sync, with the write's arguments in findings, so
    that a replay sends the same arguments and so the same derived key. The replay
    window then holds at most one irreversible write, the running step itself.
The mode is DURABILITY, one for the run: sync, because the plan has irreversible steps.
A checkpoint holds the five fields of slide 14 and never the conversation.

A resume (run.py --resume) is told from a fresh run by the checkpointer: a run_id
with a checkpoint is restored from its last one and replays from there. A done step
is skipped and its recorded result reused; a write is replayed with the arguments
the checkpoint saved, never new ones from the model, through the registry, whose
check before every attempt asks the tracker by the write's key (and a PR by its
branch): there, proceed; not there, write with the same key; cannot tell, escalate.
A run with no checkpoint starts over under the same run_id.
"""

from __future__ import annotations

import copy
import json
import re

from agent.critique import self_critique, verify
from agent.diff import step_args
from agent.plan import SCHEMA, make_plan, revise_plan
from agent.validator import validate
from harness.formats import FILL, format_triage_comment, parse_triage_comment, result_paths
from harness.roles import arg, tool_for
from harness.schema import errors as schema_errors
from state.checkpointer import Checkpointer
from tools import ToolResult, Unverifiable

MAX_REPLANS = 2       # three planner calls in all; a fourth on the same request is the same coin, so a person looks
MAX_REVISIONS = 2     # a repair of the first search, and one more if the repair also finds nothing
MAX_ROUNDS = 2        # check, rewrite once, check again: slide 43's limit, the same in both modes
MAX_FILL_TRIES = 2    # a step the model will not fill on plan, twice, halts the run
CHECKPOINT = "after_first_search"
SOURCE = re.compile(r"^src/(?!i18n/).+\.tsx?$")   # code, not documentation or translations
CONTEXT_CHARS = 6000  # of each earlier result, in a fill call
DURABILITY = "sync"   # one mode for the run (slide 12): it has irreversible steps
SAVE_AFTER = ("read_issue", "search", "read_file")   # reads worth not repeating: the plan, and two fill calls


def role(name: str | None) -> str | None:
    """The role a step's tool plays, or None."""
    return next((r for r in ("read_issue", "search", "read_file", "comment", "open_pr") if tool_for(r) == name), None)


def unfilled(value) -> bool:
    """An argument still to fill in: "$fill", "$fill: a note", or a template that holds a
    "$fill" anywhere, such as "label: $fill\nfile: $fill", which a planner may write.
    Only a leading "$fill" counted before, so a template went out as it was written."""
    return FILL in str(value)


def allows_null(spec: dict) -> bool:
    """Whether a property's schema takes null: "type": [..., "null"], or a null branch."""
    kind = spec.get("type")
    return ("null" in kind if isinstance(kind, list) else kind == "null") or any(
        isinstance(b, dict) and allows_null(b) for b in spec.get("anyOf") or spec.get("oneOf") or [])


def run(ctx) -> None:
    saved = Checkpointer().last(ctx.run_id)
    if saved is not None:                         # a resume: replay from the last checkpoint
        Executor.restore(ctx, saved).run()
        return
    plan = plan_until_valid(ctx)                  # a fresh run, or a crash before the first checkpoint
    if plan is None:
        return
    ctx.trace.plan(1, plan)
    Executor(ctx, plan).run()


def schema_check(ctx, plan: dict, version: int) -> list[dict]:
    """The plan as the planner's tool returned it, against agent/plan_schema.json. A
    failure is written as a schema line, and comes back as failures for a re-plan."""
    problems = schema_errors({k: v for k, v in plan.items() if k != "meta"}, SCHEMA)
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    roles = [role(s.get("tool")) for s in steps]
    if roles.count("comment") != 1 or roles[-1] != "comment":
        problems.append(f"the comment step comes once, last, with the PR step right before it; this plan's steps are {roles}")
    elif roles.count("open_pr") != 1 or roles[-2] != "open_pr":
        problems.append("the PR step comes exactly once, right before the comment step")
    if problems:
        ctx.trace.event("schema", version=version, errors=problems[:20])
    return [{"step": None, "check": "schema", "error": e} for e in problems[:5]]


def plan_until_valid(ctx) -> dict | None:
    """The reject exit: re-plan up to MAX_REPLANS times, then escalate. Never execute a rejected plan."""
    failures = None
    for attempt in range(1, MAX_REPLANS + 2):
        plan = make_plan(ctx.client, ctx.issue_number, ctx.tools.schemas, trace=ctx.trace, failures=failures)
        broken = schema_check(ctx, plan, 1)
        if broken:                                # rejected before the four checks: it never runs
            failures = broken
            continue
        verdict = validate(plan)
        ctx.trace.event("validation", version=1, attempt=attempt, valid=verdict["valid"],
                        failures=verdict["failures"])
        if verdict["valid"]:
            return plan
        failures = verdict["failures"]
    ctx.trace.end("escalated", detail=f"no valid plan in {MAX_REPLANS + 1} attempts; last failures {failures}")
    return None


class Executor:
    critique = True   # the notes way turns the second pass off

    def __init__(self, ctx, plan: dict):
        self.ctx = ctx
        self.plan = copy.deepcopy(plan)
        self.version = 1
        self.results: list[dict] = []    # step_results (checks/FORMATS.md, section 10.3), in the order steps ran
        self.outputs: dict[str, str] = {}  # each step's tool output, for later calls; never shown to the reviser
        self.calls = 0                   # execute and critique calls so far: the step number of the next lines
        self.revisions = 0
        self.revised: set[str] = set()   # ids of steps a revision added or changed: the checkpoint follows them
        self.ran: set[str] = set()       # ids of steps that ran and are not to run again
        self.saves = Checkpointer()      # Assignment 4: the run's state, on disk
        self.completed: list[dict] = []  # completed_calls: every tool call that returned, with its key
        self.pr_args: dict | None = None # the PR's arguments, once filled: saved before it is opened

    # -- the plan, in order ------------------------------------------------------------
    def next_step(self) -> dict | None:
        return next((s for s in self.plan.get("steps") or [] if str(s.get("id")) not in self.ran), None)

    def run(self) -> None:
        try:
            self.steps()
        finally:
            self.saves.flush()                    # exit and async saves land at the end of the run

    def steps(self) -> None:
        while True:
            step = self.next_step()
            if step is None:
                return                            # the plan is finished; the runner writes completed
            if role(step.get("tool")) in ("open_pr", "comment") and self.draft is None:
                if not self.prepare(self.comment_step()):
                    return                        # held, or not filled: nothing was written
            if role(step.get("tool")) == "open_pr":
                if not self.pull_request(step):
                    return
                continue
            if role(step.get("tool")) == "comment":
                if not self.post(step):
                    return
                continue
            first = not any(role(r["tool"]) == "search" for r in self.results)
            result = self.run_step(step)
            if result is None:
                return                            # halted, and ended escalated
            if role(step.get("tool")) == "search" and (first or str(step.get("id")) in self.revised):
                self.checkpoint(CHECKPOINT, any(SOURCE.match(p) for p in result.get("paths") or []))
            if role(step.get("tool")) in SAVE_AFTER:   # after the revision, so the plan saved is the one in force
                after = self.next_step()
                self.save(step.get("id"), None if after is None else after.get("id"))

    # -- one step ------------------------------------------------------------------------
    def run_step(self, step: dict) -> dict | None:
        tool, args = step.get("tool"), step_args(step)
        if not tool:
            return self.record(step, args, None, "no_tool")
        args = self.filled(step, args)
        if args is None:
            return None
        result = self.call(step, tool, args)
        return None if result is None else self.record(step, args, result)

    def call(self, step: dict, tool: str, args: dict):
        """One tool call for a plan step; None when the registry could not confirm a
        write, and the run has ended escalated (the third exit)."""
        try:
            result = self.ctx.call_tool(self.calls, tool, args, plan_step=step.get("id"))
        except Unverifiable as exc:
            self.record(step, args, None, "unverifiable")
            self.ctx.trace.end("escalated", detail=f"step {step.get('id')}: {exc}; a person on review duty decides")
            return None
        self.completed.append({"step": step.get("id"), "tool": tool, "args": args, "key": result.key,
                               "result": {"text": result.content[:CONTEXT_CHARS], "is_error": result.is_error}})
        return result

    def filled(self, step: dict, args: dict) -> dict | None:
        to_fill = [k for k, v in args.items() if unfilled(v)]   # "$fill", "$fill: a note", or a template holding one
        if not to_fill:
            return args
        filled = self.fill(step, args, to_fill)
        if filled is None:
            self.record(step, args, None, "off_plan")
            self.ctx.trace.end("escalated", detail=f"step {step.get('id')}: no on-plan call in {MAX_FILL_TRIES} tries")
        return filled

    def fill(self, step: dict, args: dict, keys: list[str], *, system: str = "executor.md",
             purpose: str = "execute", note: str = "") -> dict | None:
        """One model call fills a step's "$fill" arguments, offered the step's tool alone. It
        keeps every argument the model gave that the schema knows, the ones the plan never
        mentioned included, and a null where the schema allows one (Part A's required and
        nullable fields); the plan's own values win."""
        schema = next((t for t in self.ctx.tools.schemas if t["name"] == step["tool"]), None)
        if schema is None:
            return None
        fixed = {k: v for k, v in args.items() if not unfilled(v)}
        props = (schema.get("input_schema") or {}).get("properties") or {}
        nullable = {k for k, s in props.items() if isinstance(s, dict) and allows_null(s)}
        for _ in range(MAX_FILL_TRIES):
            self.calls += 1
            response = self.ctx.client.create(system=self.ctx.prompt(system), tools=[schema],
                                              messages=[{"role": "user", "content": self.fill_request(step, fixed, keys, note)}])
            self.ctx.trace.model_call(self.calls, response, purpose=purpose)
            for call in response.tool_calls:
                if call.name != step["tool"]:
                    self.refuse(step, call)       # the boundary: never run, always traced
                    continue
                filled = {**{k: v for k, v in call.input.items() if k in props}, **fixed}   # the plan's values win
                if any(k not in filled or filled[k] == "" or unfilled(filled[k])
                       or (filled[k] is None and k not in nullable)
                       for k in keys):
                    continue
                if role(step["tool"]) == "comment":
                    body = arg("comment", "body")
                    label, file = parse_triage_comment(str(filled[body]))
                    filled[body] = format_triage_comment(label or "bug", file)
                return filled
        return None

    def refuse(self, step: dict, call) -> None:
        self.ctx.trace.event("off_plan", step=step.get("id"), tool=call.name, input=call.input, version=self.version)

    def context(self) -> list[str]:
        """What the run has gathered so far, one block per step, for a fill or a critique."""
        return [f"## Step {r['id']}, {r['tool']}, {r['status']}\n{self.outputs.get(str(r['id']), '')[:CONTEXT_CHARS]}"
                for r in self.results]

    def fill_request(self, step: dict, fixed: dict, keys: list[str], note: str = "") -> str:
        parts = [f"Triage issue #{self.ctx.issue_number}. You are running step {step.get('id')} of a fixed "
                 f"plan: {step.get('action')}. Call {step['tool']} once. Fill in: {', '.join(keys)}. "
                 f"The plan fixes: {json.dumps(fixed)}."]
        if role(step["tool"]) == "comment":
            parts.append("The comment's first two lines must be:\nlabel: <bug | feature | question | docs>\n"
                         "file: <path relative to the repository root, or none>")
        if role(step["tool"]) == "open_pr":
            parts.append(f"The triage comment's draft names {self.drafted_file}. The pull request's title says what "
                         "the change fixes; its body names that file first, then proposes the change in prose.")
        notes = {k: str(v)[len(FILL):].lstrip(": ").strip() for k, v in step_args(step).items()
                 if str(v).startswith(FILL) and str(v).strip() != FILL}
        if notes:
            parts.append("The plan's notes on them: " + "; ".join(f"{k}: {v}" for k, v in notes.items()))
        if note:
            parts.append(note)
        return "\n\n".join(parts + self.context())

    def record(self, step: dict, args: dict, result, error: str | None = None) -> dict:
        tool = step.get("tool")
        text = result.content if result is not None else ""
        count, paths = None, []
        if result is not None and role(tool) in ("search", "read_file"):
            paths = result_paths(tool, args, text, result.is_error)
            count = len(paths) if role(tool) == "search" else None
        if error is None and result is not None and result.is_error:
            error = "not_found" if "no such file" in text else "tool_error"
        if error is None and role(tool) == "search" and not count:
            error = "no_matches"
        status = "skipped" if error == "skipped" else "failed" if error else "done"
        entry = {"id": step.get("id"), "tool": tool, "status": status, "count": count,
                 "paths": paths, "error_code": error, "args": args}
        self.results.append(entry)
        self.ran.add(str(step.get("id")))
        self.outputs[str(step.get("id"))] = text
        for s in self.plan.get("steps") or []:
            if str(s.get("id")) == str(step.get("id")):
                s["status"] = entry["status"]
        return entry

    # -- revision, at the checkpoint whose check failed --------------------------------------
    def checkpoint(self, name: str, ok: bool) -> bool:
        """True when a new version is now active."""
        if ok or self.revisions >= MAX_REVISIONS:
            return False
        self.revisions += 1
        proposed = revise_plan(self.ctx.client, self.plan, self.results, trace=self.ctx.trace)
        broken = schema_check(self.ctx, proposed, self.version + 1)
        verdict = {"valid": False, "failures": broken} if broken else validate(proposed)
        self.ctx.trace.event("revision", checkpoint=name, version=self.version + 1, valid=verdict["valid"],
                             failures=verdict["failures"])
        if not verdict["valid"]:
            return False                          # rejected: it never runs, and it counted against the bound
        before = {str(s.get("id")): {k: v for k, v in s.items() if k != "status"} for s in self.plan.get("steps") or []}
        changed = {str(s.get("id")) for s in proposed.get("steps") or []
                   if before.get(str(s.get("id"))) != {k: v for k, v in s.items() if k != "status"}}
        self.revised |= changed
        failed = {str(r["id"]) for r in self.results if r["status"] == "failed"}
        done = {str(r["id"]) for r in self.results if r["status"] == "done"}
        self.ran -= (changed & failed) - done      # a failed step the revision changed runs again
        self.version += 1
        self.plan = proposed
        self.ctx.trace.plan(self.version, proposed)
        return True

    # -- the comment's draft and the second pass, before the first write ---------------------------
    draft: dict | None = None        # the comment's arguments, checked, waiting to be posted last
    drafted_file: str | None = None

    def comment_step(self) -> dict:
        return next(s for s in self.plan.get("steps") or [] if role(s.get("tool")) == "comment")

    def prepare(self, step: dict) -> bool:
        """Draft the comment and run the second pass, before the PR or the comment is
        written. False when the run has ended, with nothing written."""
        draft = self.filled(step, step_args(step))
        if draft is None:
            return False
        final = self.second_pass(step, draft) if self.critique else draft
        if final is None:
            self.record(step, draft, None, "held")
            self.ctx.trace.end("escalated", detail=f"the draft still failed the second pass after {MAX_ROUNDS} rounds")
            return False
        self.draft = final
        self.drafted_file = parse_triage_comment(str(final.get(arg("comment", "body"))))[1] or "none"
        return True

    def post(self, step: dict) -> bool:
        """Post the checked draft, the run's last write. False when the run has ended.
        The draft is on disk, sync, before the call: a replay posts these arguments."""
        self.save(step.get("id"), step.get("id"))
        result = self.call(step, step["tool"], self.draft)
        if result is None:
            return False
        self.record(step, self.draft, result)
        return True

    # -- the pull request, before the comment ---------------------------------------------------
    def pull_request(self, step: dict) -> bool:
        """Open the draft PR when the comment's draft names a file; skip the step when it
        says none. The issue and the branch are fixed here, by code. False when the run
        has ended."""
        if self.drafted_file in (None, "none"):
            self.record(step, step_args(step), None, "skipped")
            return True
        if self.pr_args is None:                  # a replay keeps the arguments it saved; never new ones
            number = self.ctx.issue_number
            args = step_args(step)
            args[arg("open_pr", "number")] = f"issue-{number}"
            args[arg("open_pr", "branch")] = f"repomind/issue-{number}"
            filled = self.filled(step, args)
            if filled is None:
                return False
            self.pr_args = filled
        filled = self.pr_args
        self.save(step.get("id"), step.get("id"))   # sync, with the PR's arguments, before it is opened
        result = self.call(step, step["tool"], filled)
        if result is None:
            return False
        self.record(step, filled, result)
        return True

    def evidence(self) -> dict:
        issue = next((self.outputs.get(str(r["id"]), "") for r in self.results if role(r["tool"]) == "read_issue"), "")
        return {"issue": issue, "results": self.context()}

    def second_pass(self, step: dict, args: dict) -> dict | None:
        mode = self.ctx.critique
        if mode not in ("self", "external"):
            return args
        body = arg("comment", "body")
        for round_ in range(1, MAX_ROUNDS + 1):
            draft = args[body]
            if mode == "external":
                verdict = verify(draft, self.ctx)
            else:
                self.calls += 1
                v = self_critique(self.ctx.client, draft, self.evidence(), self.ctx.trace, step=self.calls)
                verdict = {"passed": v["decision"] == "accept", "reasons": [v["reason"]] if v.get("reason") else []}
            reason = "; ".join(verdict["reasons"]) or None
            changed = False
            if not verdict["passed"] and round_ < MAX_ROUNDS:
                rewritten = self.rewrite(step, args, reason or "the critic asked for a revision")
                if rewritten is not None:
                    changed = rewritten[body] != draft
                    args = rewritten
            self.ctx.trace.event("critique", round=round_, mode=mode, result="pass" if verdict["passed"] else "fail",
                                 reason=reason, changed=changed, draft=draft)
            if verdict["passed"]:
                return args
        return None                               # still failing in the last round: held

    def rewrite(self, step: dict, args: dict, reason: str) -> dict | None:
        """One model call rewrites the draft with the reason, offered the comment tool alone."""
        body = arg("comment", "body")
        note = f"Rewrite the draft. The draft:\n\n{args[body]}\n\nWhy it must change: {reason}"
        return self.fill(step, {**args, body: FILL}, [body], system="rewrite.md", purpose="critique", note=note)

    # -- Assignment 4: the run's state, saved and restored ----------------------------------------
    def findings(self) -> dict:
        """What the run has established: once drafted, the label and file its comment states,
        and the arguments of each write it is about to make; and the bookkeeping a resume
        needs to go on as this run would have."""
        out = {}
        if self.draft is not None:
            label, file = parse_triage_comment(str(self.draft.get(arg("comment", "body"))))
            out.update(label=label, file=file or "none", comment=copy.deepcopy(self.draft))
        if self.pr_args is not None:
            out["pull_request"] = copy.deepcopy(self.pr_args)
        out["progress"] = {"plan_version": self.version, "revisions": self.revisions,
                           "revised": sorted(self.revised), "model_calls": self.calls}
        return out

    def snapshot(self, current, running: bool) -> dict:
        """The five fields of slide 14, and nothing else: never the conversation."""
        status = {str(s.get("id")): s.get("status") or "pending" for s in self.plan.get("steps") or []}
        if running and current is not None:
            status[str(current)] = "running"
        return {"plan": copy.deepcopy(self.plan), "step_status": status,
                "completed_calls": copy.deepcopy(self.completed), "findings": self.findings(),
                "current_step": current}

    def save(self, step_id, current) -> None:
        """One checkpoint, for plan step step_id: after a read, or immediately before a write
        (current == step_id, the write about to run). Sync: on disk before the next call."""
        checkpoint = self.snapshot(current, running=current is not None and str(current) == str(step_id))
        self.saves.save(self.ctx.run_id, checkpoint, step=step_id, mode=DURABILITY)
        self.ctx.trace.event("checkpoint", step=step_id, mode=DURABILITY)

    @classmethod
    def restore(cls, ctx, saved: dict) -> "Executor":
        """An executor where the last checkpoint left the run. A step done, failed or skipped
        there is not run again, and its recorded result is the context later steps see; the
        running step, the one whose outcome is unknown, and every pending one run again."""
        ex = cls(ctx, saved["plan"])
        found = saved.get("findings") or {}
        progress = found.get("progress") or {}
        ex.version = progress.get("plan_version", 1)
        ex.revisions = progress.get("revisions", 0)
        ex.revised = set(progress.get("revised") or [])
        ex.calls = progress.get("model_calls", 0)
        steps = {str(s.get("id")): s for s in ex.plan.get("steps") or []}
        for call in saved.get("completed_calls") or []:   # a recorded result, never a second call
            step = steps.get(str(call["step"])) or {"id": call["step"], "tool": call["tool"]}
            result = call.get("result") or {}
            ex.record(step, call["args"], ToolResult(result.get("text", ""), bool(result.get("is_error")), 0.0,
                                                     call.get("key")))
            ex.completed.append(call)
        status = saved.get("step_status") or {}
        for sid, state in status.items():
            if state == "skipped" and sid not in ex.ran and sid in steps:
                ex.record(steps[sid], step_args(steps[sid]), None, "skipped")
        ex.ran = {sid for sid, state in status.items() if state in ("done", "failed", "skipped")}
        for sid, step in steps.items():                  # the saved statuses are the truth
            step["status"] = status.get(sid, step.get("status"))
            if step["status"] == "running":
                step["status"] = "pending"
        if found.get("comment") is not None:
            ex.draft = found["comment"]
            ex.drafted_file = found.get("file") or "none"
        ex.pr_args = found.get("pull_request")
        ctx.trace.event("restored", step=saved.get("current_step"), done=sorted(ex.ran, key=str),
                        version=ex.version, checkpoints=len(ex.saves.all(ctx.run_id)))
        return ex
