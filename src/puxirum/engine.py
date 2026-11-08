"""The engine: the deterministic loop that drives every job.

Each tick: notice PRs merged on the forge, start jobs for new issues while slots
are free, then drive every workable job until it waits or finishes. Driving a
job means repeating `step`: drain its pending effects, then do the one thing
its stage calls for (run an agent, run the gate, merge) and move it on.

Rules the engine keeps:

- Every change to a job is load → change → save under the store lock, so
  parallel reviewers never overwrite each other.
- An agent's run only counts if it exited 0 *and* rewrote its output file. A
  file that breaks the contract, or a move the machine refuses because of what
  the agent did, makes the agent run again; after `agent_attempts` runs the job
  escalates with the last error.
- A failing effect is retried on later ticks; after `effect_attempts` failures
  its pending effects are abandoned and the job escalates.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from puxirum import files, gate, report, servers
from puxirum.files import MalformedFile
from puxirum.forge import ForgeError
from puxirum.git import GitError
from puxirum.machine import ACTIVE, TERMINAL, WAITING, Refused, advance, resume_stage
from puxirum.runner import AgentResult, AgentTask, Runner
from puxirum.store import Job, now
from puxirum.world import EffectError, World, replied_since_question

MAX_STEPS = 200
PORT_SLOTS = 100
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
APP_LENSES = ("ux", "ui")


class Escalate(Exception):
    """Stop working on the job and hand it to a person, with this reason."""


@dataclass(frozen=True)
class Row:
    action: str  # resume | new | hold | wait | skip
    issue: int
    job_id: str | None
    stage: str | None
    round: int
    pr: int | None
    note: str


class Engine:
    def __init__(self, world: World, runner: Runner, log: Callable[[str], None] | None = None):
        self.world = world
        self.runner = runner
        self.cfg = world.cfg
        self.store = world.store
        self.forge = world.forge
        self.git = world.git
        self.log = log or (lambda msg: None)
        self.run_id: str | None = None

    # ---- the queue ---------------------------------------------------------------------------

    def plan(self, only: int | None = None) -> list[Row]:
        """What a run would do with each labeled issue and each unfinished job, in start order."""
        jobs = {j.issue: j for j in self.store.all()}
        issues = sorted(self.forge.list_issues(self.cfg.queue_label), key=lambda i: i.number)
        open_numbers = {i.number for i in issues}
        free = self.cfg.concurrency - sum(1 for j in jobs.values() if j.stage in ACTIVE)
        op = self.forge.operator()
        resume, waiting_ready, new, other = [], [], [], []

        def row(action: str, j: Job | None, issue: int, note: str) -> Row:
            return Row(action, issue, j.id if j else None, j.stage if j else None,
                       j.round if j else 0, j.pr if j else None, note)

        for issue in issues:
            j = jobs.get(issue.number)
            if j is None:
                new.append((issue.number, issue.title))
            elif j.stage in ACTIVE:
                resume.append(row("resume", j, issue.number, f"round {j.round}" if j.round else j.stage))
            elif j.stage == "needs-info":
                if replied_since_question(self.forge.issue(issue.number), op):
                    waiting_ready.append((j, "the author replied"))
                else:
                    other.append(row("wait", j, issue.number, "waiting for the author to reply"))
            elif j.stage == "needs-human":
                if self._feedback_ready(j):
                    waiting_ready.append((j, "feedback received"))
                else:
                    note = f"give feedback, reject, or merge PR #{j.pr}" if j.pr else "give feedback or reject"
                    other.append(row("wait", j, issue.number, note))
            else:
                other.append(row("skip", j, issue.number, j.stage))
        for n, j in sorted(jobs.items()):
            if n not in open_numbers and j.stage not in TERMINAL:
                other.append(row("skip", j, n, f"the issue is closed or no longer labeled {self.cfg.queue_label}"))

        rows = list(resume)
        for j, note in waiting_ready:
            if free > 0:
                rows.append(row("resume", j, j.issue, note))
                free -= 1
            else:
                rows.append(row("hold", j, j.issue, f"{note}; concurrency {self.cfg.concurrency} reached"))
        for n, title in new:
            if free > 0:
                rows.append(Row("new", n, None, None, 0, None, title))
                free -= 1
            else:
                rows.append(Row("hold", n, None, None, 0, None, f"concurrency {self.cfg.concurrency} reached"))
        rows += other
        return [r for r in rows if only is None or r.issue == only]

    def run(self, only: int | None = None, max_ticks: int = 100) -> dict:
        """Work until every job waits, finishes or can't move. Returns the run's summary."""
        started = now()
        self.run_id = f"{started.replace('-', '').replace(':', '')}-{os.getpid()}"
        try:
            self._ticks(only, max_ticks)
        finally:
            summary = report.write_run(self.store, self.run_id, started, only)
            self.run_id = None
        return summary

    def _ticks(self, only: int | None, max_ticks: int) -> None:
        for _ in range(max_ticks):
            progressed = self.sync_merged()
            work = []
            for r in self.plan(only):
                if r.action == "new":
                    work.append(self.start(r.issue))
                    progressed = True
                elif r.action == "resume":
                    assert r.job_id is not None, "a resume row always names its job"
                    work.append(r.job_id)
            if work:
                with ThreadPoolExecutor(max_workers=self.cfg.concurrency) as pool:
                    progressed = any(list(pool.map(self.drive, work))) or progressed
            if not progressed:
                return

    def start(self, issue_number: int) -> str:
        issue = self.forge.issue(issue_number)
        with self.store.lock():
            job = self.store.create(issue.number, issue.title, self.cfg.branch_prefix, self.cfg.worktrees_dir)
        self.world.write_issue_md(job)
        self.log(f"{job.id}: new job for #{issue.number}")
        return job.id

    def sync_merged(self) -> bool:
        """Finish jobs whose PR was merged on the forge, by Puxirum or by a person."""
        moved = False
        for j in self.store.all():
            if j.stage not in TERMINAL and j.pr and not j.pending and self.forge.pr(j.pr).state == "MERGED":
                self._move(j.id, "merged")
                moved = True
        return moved

    # ---- driving one job ---------------------------------------------------------------------

    def drive(self, job_id: str) -> bool:
        progressed = False
        for _ in range(MAX_STEPS):
            if not self.step(job_id):
                return progressed
            progressed = True
        raise RuntimeError(f"{job_id}: no rest after {MAX_STEPS} steps")

    def step(self, job_id: str) -> bool:
        """Do the next thing for the job. False when there is nothing to do right now."""
        job = self.store.load(job_id)
        if job.pending:
            return self._drain(job)
        handler = getattr(self, "_" + job.stage.replace("-", "_"), None)
        if handler is None:
            return False
        try:
            return handler(job)
        except Escalate as e:
            self.log(f"{job.id}: escalating from {job.stage}: {e}")
            self._move(job.id, "needs-human", reason=str(e))
            return True

    def _drain(self, job: Job) -> bool:
        try:
            self.world.drain(job.id)
            return True
        except EffectError as e:
            failures = sum(1 for ev in self.store.events(job.id)
                           if ev["type"] == "effect-failed" and ev.get("key") == e.effect.key)
            if failures < self.cfg.effect_attempts:
                self.log(f"{job.id}: {e} (attempt {failures} of {self.cfg.effect_attempts})")
                return False
            self.world.abandon(job.id, str(e))
            if job.stage in ACTIVE:
                self._move(job.id, "needs-human", reason=f"An action failed {failures} times:\n\n{e}")
            else:
                self.log(f"{job.id}: abandoned effects in {job.stage}: {e}")
            return True

    # ---- stages --------------------------------------------------------------------------------

    def _intake(self, job: Job) -> bool:
        d = self.store.job_dir(job.id)
        if not (d / "issue.md").exists():
            self.world.write_issue_md(job)
        key = f"intake@{job.seq}"
        if key not in job.done:
            return self._agent(job, key, "intake", None, "intake.md", self.world.repo)
        f = self._read(job, key, "intake.md", "intake")
        if f is None:
            return True
        target = {"ACCEPT": "spec", "NEEDS-INFO": "needs-info", "REJECT": "rejected"}[f.header["DECISION"]]
        return self._agent_move(job, key, "intake.md", target)

    def _spec(self, job: Job) -> bool:
        key = f"spec@{job.seq}"
        if key not in job.done:
            return self._agent(job, key, "spec", None, "spec.md", self._worktree(job))
        return self._agent_move(job, key, "spec.md", "build")

    def _build(self, job: Job) -> bool:
        key = f"builder@{job.seq}"
        if key not in job.done:
            return self._agent(job, key, "builder", None, "build.md", self._worktree(job))
        f = self._read(job, key, "build.md", "build")
        if f is None:
            return True
        target = "gate" if f.header["STATUS"] == "READY" else "needs-human"
        return self._agent_move(job, key, "build.md", target)

    def _gate(self, job: Job) -> bool:
        out = self._round_dir(job)
        try:
            head = self.git.head(job.worktree)
            current = self._checks(out / "checks.md")
            if current is None or current.header["COMMIT"] != head:
                self.log(f"{job.id}: gate, round {job.round}")
                gate.run(self.cfg, self.world.repo, self._worktree(job), out, env=self._env(job))
                current = self._checks(out / "checks.md")
        except (gate.GateError, GitError) as e:
            raise Escalate(f"The gate couldn't run:\n\n{e}") from e
        assert current is not None
        if current.header["GATE"] == "PASS":
            target = "review"
        else:
            target = "build" if job.round < job.round_limit else "needs-human"
        return self._move_or_escalate(job, target)

    def _review(self, job: Job) -> bool:
        missing = [lens for lens in job.reviewers if f"review-{lens}@{job.seq}" not in job.done]
        if missing:
            with ThreadPoolExecutor(max_workers=len(missing)) as pool:
                list(pool.map(lambda lens: self._agent(
                    job, f"review-{lens}@{job.seq}", "reviewer", lens,
                    f"round-{job.round}/review-{lens}.md", self._worktree(job)), missing))
            return True
        changes, invalid = [], False
        for lens in job.reviewers:
            f = self._read(job, f"review-{lens}@{job.seq}", f"round-{job.round}/review-{lens}.md", "review")
            if f is None:
                invalid = True
            elif f.header["VERDICT"] == "PASS" and self._missing_evidence(job, lens):
                self._retry(job, f"review-{lens}@{job.seq}", f"round-{job.round}/review-{lens}.md",
                            f"VERDICT: PASS without screenshots: save them in {self._round_dir(job) / 'evidence'} "
                            f"with names starting `{lens}-`")
                invalid = True
            elif f.header["VERDICT"] == "CHANGES":
                changes.append(lens)
        if invalid:
            return True
        if not changes:
            target = "approve"
        else:
            target = "build" if job.round < job.round_limit else "needs-human"
        return self._move_or_escalate(job, target)

    def _approve(self, job: Job) -> bool:
        key = f"approver@{job.seq}"
        if key not in job.done:
            return self._agent(job, key, "approver", None, "decision.md", self._worktree(job))
        f = self._read(job, key, "decision.md", "decision")
        if f is None:
            return True
        target = "merging" if f.header["DECISION"] == "APPROVE" else "needs-human"
        return self._agent_move(job, key, "decision.md", target)

    def _merging(self, job: Job) -> bool:
        if job.pr is None:
            raise Escalate("There is no PR to merge.")
        if self.forge.pr(job.pr).state == "MERGED":
            return self._move_or_escalate(job, "merged")
        base = self.cfg.base_branch
        try:
            ok, output = self.git.sync_with_base(job.worktree, base)
            if not ok:
                raise Escalate(f"The branch conflicts with {base}:\n\n```\n{output}\n```")
            result = gate.run(self.cfg, self.world.repo, self._worktree(job), self._round_dir(job),
                              merge=True, env=self._env(job))
            if result.verdict != "PASS":
                raise Escalate(f"The gate failed after syncing with {base}. "
                               f"See round-{job.round}/merge-checks.md.")
            self.git.push(job.worktree, job.branch)
            self.forge.mark_ready(job.pr)
            self.forge.merge_pr(job.pr, self.cfg.merge_method)
        except (GitError, ForgeError, gate.GateError) as e:
            raise Escalate(f"The merge failed:\n\n```\n{e}\n```") from e
        self.log(f"{job.id}: merged PR #{job.pr}")
        return self._move_or_escalate(job, "merged")

    def _needs_info(self, job: Job) -> bool:
        return self._try_move(job, "intake")

    def _needs_human(self, job: Job) -> bool:
        if not self._feedback_ready(job):
            return False
        return self._try_move(job, resume_stage(job.escalations[-1]["from"]))

    # ---- people ----------------------------------------------------------------------------------

    def feedback(self, ref: str | int, text: str) -> Job:
        """Record a person's feedback on an escalated job and send it back to work when a slot is free."""
        if not text.strip():
            raise ValueError("the feedback is empty")
        job = self.store.find(ref)
        if job.stage != "needs-human":
            raise Refused(f"{job.id} is in {job.stage}, not needs-human")
        k = len(job.escalations)
        path = self.store.job_dir(job.id) / f"feedback-{k}.md"
        if path.exists():
            raise Refused(f"{job.id} already has {path.name}; it resumes when a slot is free")
        path.write_text(f"FROM: {self.forge.operator()}\n\n## Feedback\n{text.strip()}\n", encoding="utf-8")
        self.store.event(job.id, "feedback", file=path.name)
        self._try_move(job, resume_stage(job.escalations[-1]["from"]))
        return self.store.load(job.id)

    def reject(self, ref: str | int, reason: str) -> Job:
        """Reject a job that waits for a person or for the author."""
        if not reason.strip():
            raise ValueError("the reason is empty")
        job = self.store.find(ref)
        if job.stage not in WAITING:
            raise Refused(f"{job.id} is in {job.stage}; only a waiting job can be rejected")
        path = self.store.job_dir(job.id) / "rejection.md"
        path.write_text(f"REJECTED-BY: {self.forge.operator()}\n\n{reason.strip()}\n", encoding="utf-8")
        self._move(job.id, "rejected")
        return self.store.load(job.id)

    # ---- helpers ---------------------------------------------------------------------------------

    def _update(self, job_id: str, change: Callable[[Job], None]) -> Job:
        with self.store.lock():
            job = self.store.load(job_id)
            change(job)
            self.store.save(job)
            return job

    def _move(self, job_id: str, target: str, reason: str | None = None) -> Job:
        """Advance the job, save it with its effects pending, then run them."""
        with self.store.lock():
            job = self.store.load(job_id)
            new, effects = advance(job, target, cfg=self.cfg, job_dir=self.store.job_dir(job_id),
                                   facts=self.world.facts(job), reason=reason)
            new.pending = effects
            new.last_error = None
            self.store.save(new)
            self.store.event(job_id, "transition", **{"from": job.stage, "to": target, "seq": new.seq,
                                                      "reason": reason})
        self.log(f"{job_id}: {job.stage} → {target}")
        self._drain(new)
        return new

    def _try_move(self, job: Job, target: str) -> bool:
        """A move that may be refused for now (waiting for a reply or a slot)."""
        try:
            self._move(job.id, target)
            return True
        except Refused:
            return False

    def _move_or_escalate(self, job: Job, target: str) -> bool:
        try:
            self._move(job.id, target)
        except Refused as e:
            raise Escalate(f"Puxirum refused {job.stage} → {target}: {e}") from e
        return True

    def _agent_move(self, job: Job, key: str, output: str, target: str) -> bool:
        """A move justified by an agent's file: if the machine refuses it, the agent runs again."""
        try:
            self._move(job.id, target)
        except Refused as e:
            self._retry(job, key, output, str(e))
        return True

    def _read(self, job: Job, key: str, output: str, kind: str) -> files.AgentFile | None:
        try:
            return files.read(self.store.job_dir(job.id) / output, kind)
        except (FileNotFoundError, MalformedFile) as e:
            self._retry(job, key, output, f"{output}: {getattr(e, 'reason', 'missing')}")
            return None

    def _retry(self, job: Job, key: str, output: str, error: str) -> None:
        """Set the agent's file aside and make it run again on the next step."""
        path = self.store.job_dir(job.id) / output
        n = job.attempts.get(key, 0)
        if path.exists():
            path.rename(path.with_name(f"{path.stem}.invalid-{n}{path.suffix}"))

        def change(j: Job) -> None:
            if key in j.done:
                j.done.remove(key)
            j.last_error = error

        self._update(job.id, change)
        self.store.event(job.id, "agent-rejected", key=key, error=error)
        self.log(f"{job.id}: {key}: {error}")

    def _agent(self, job: Job, key: str, role: str, lens: str | None, output: str, cwd: Path) -> bool:
        attempts = job.attempts.get(key, 0)
        if attempts >= self.cfg.agent_attempts:
            name = f"{role}:{lens}" if lens else role
            raise Escalate(f"The {name} agent failed {attempts} times. Last error: {job.last_error}")
        d = self.store.job_dir(job.id)
        out = d / output
        out.parent.mkdir(parents=True, exist_ok=True)
        before = _fingerprint(out)
        self._update(job.id, lambda j: j.attempts.__setitem__(key, attempts + 1))
        task = AgentTask(
            role=role, lens=lens, job_id=job.id,
            model=job.reviewers[lens] if lens else self.cfg.models[role],
            cwd=cwd, job_dir=d, output=out, vars=self._vars(job, role, lens, attempts),
        )
        self.log(f"{job.id}: running {task.name} ({task.model}), attempt {attempts + 1}")
        error = None
        try:
            result = self._run_with_app(job, task)
        except servers.ServerError as e:
            error = f"the app didn't start for the {task.name} agent: {e}"
            result = AgentResult(exit_code=1, seconds=0.0)
        self.store.event(job.id, "agent", run=self.run_id, key=key, role=role, lens=lens, model=task.model,
                         exit_code=result.exit_code, seconds=round(result.seconds, 3), cost_usd=result.cost_usd)
        if error is None and result.exit_code != 0:
            error = f"the {task.name} agent exited with {result.exit_code}"
        elif error is None and (_fingerprint(out) == before or before is not None and not out.exists()):
            error = f"the {task.name} agent didn't write {output}"

        def change(j: Job) -> None:
            j.cost_usd += result.cost_usd or 0.0
            j.agent_seconds += result.seconds
            if error:
                j.last_error = error
            elif key not in j.done:
                j.done.append(key)

        self._update(job.id, change)
        if error:
            self.log(f"{job.id}: {error}")
        return True

    def _needs_app(self, job: Job, task: AgentTask) -> bool:
        if not self.cfg.app_command:
            return False
        ui = "ui" in ((job.intake or {}).get("surfaces") or [])
        return (task.role == "builder" and ui) or (task.role == "reviewer" and task.lens in APP_LENSES)

    def _run_with_app(self, job: Job, task: AgentTask) -> AgentResult:
        """Run the agent, with the app's dev server up for the agents that must see it."""
        if not self._needs_app(job, task):
            return self.runner.run(task)
        log = task.job_dir / "logs" / f"app-{task.name.replace(':', '-')}-r{job.round}.log"
        port = int(task.vars["port"])
        with servers.running(self.cfg.app_command, task.cwd, port, log, setup=self.cfg.app_setup,
                             ready_timeout_s=self.cfg.app_ready_timeout_s, env=self._env(job)) as url:
            self.log(f"{job.id}: app for {task.name} at {url}")
            return self.runner.run(dataclasses.replace(task, vars={**task.vars, "app_url": url}))

    def _missing_evidence(self, job: Job, lens: str) -> bool:
        if not self.cfg.app_command or lens not in APP_LENSES:
            return False
        evidence = self._round_dir(job) / "evidence"
        return not any(p.suffix.lower() in IMAGE_SUFFIXES for p in evidence.glob(f"{lens}-*"))

    def _vars(self, job: Job, role: str, lens: str | None, attempts: int) -> dict:
        d = self.store.job_dir(job.id)
        feedback = sorted(d.glob("feedback-*.md"))
        lenses = list(job.reviewers)
        port = self._port(job) + (1 + lenses.index(lens) if lens else 0)
        return {
            "issue": job.issue, "branch": job.branch, "base": self.cfg.base_branch, "round": job.round,
            "port": port, "worktree": str(self._worktree(job)), "main_checkout": str(self.world.repo),
            "feedback": str(feedback[-1]) if feedback and job.feedback else None,
            "retry": job.last_error if attempts else None,
            "attempt": attempts + 1,
            "risk": (job.intake or {}).get("risk"),
            "surfaces": (job.intake or {}).get("surfaces", []),
            "checks": str(self.world.repo / self.cfg.checks),
            "checks_timeout_s": self.cfg.gate_timeout_s,
            "writable": [str(self._round_dir(job) / "evidence")] if role == "reviewer" else [],
            "sandbox": self.cfg.sandbox,
            "network": list(self.cfg.network),
            "sandbox_writes": list(self.cfg.sandbox_writes),
        }

    def _feedback_ready(self, job: Job) -> bool:
        k = len(job.escalations)
        return k > job.feedback and (self.store.job_dir(job.id) / f"feedback-{k}.md").is_file()

    def _checks(self, path: Path) -> files.AgentFile | None:
        try:
            return files.read(path, "checks")
        except (FileNotFoundError, MalformedFile):
            return None

    def _port(self, job: Job) -> int:
        n = int(job.id.split("-", 1)[0])
        return self.cfg.ports_base + ((n - 1) % PORT_SLOTS) * self.cfg.ports_step

    def _env(self, job: Job) -> dict[str, str]:
        return {"PUXIRUM_JOB": job.id, "PUXIRUM_PORT": str(self._port(job))}

    def _worktree(self, job: Job) -> Path:
        return self.world.repo / job.worktree

    def _round_dir(self, job: Job) -> Path:
        return self.store.job_dir(job.id) / f"round-{job.round}"


def _fingerprint(path: Path) -> tuple[int, str] | None:
    """Modification time and content hash: a rewrite with the same text still counts as written."""
    if not path.exists():
        return None
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()

