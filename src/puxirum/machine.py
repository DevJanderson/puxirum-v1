"""The job state machine.

`advance(job, target, ...)` checks that the move is legal and that the proof
for it exists (the agent files, the gate result, the state of the branch). It
returns the new job and the effects the move owes the world (comments, labels,
worktree, push). It never writes anything itself: the caller saves the job with
the effects as `pending` and then executes them, so a crash between the two can
always be resumed without losing or repeating work.

An escalation (`target="needs-human"`) is legal either with the stage's own proof
(a blocked build, a failed last round, the approver's ESCALATE) or with an
explicit `reason` from the core, for failures no file records: an agent that
crashed or kept writing malformed files, a merge conflict, a broken effect.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from puxirum import files, route
from puxirum.config import Config
from puxirum.files import MalformedFile
from puxirum.store import Effect, Job, now

STAGES = (
    "intake", "needs-info", "spec", "build", "gate", "review",
    "approve", "merging", "needs-human", "merged", "rejected",
)
TRANSITIONS: dict[str, frozenset[str]] = {
    "intake": frozenset({"spec", "needs-info", "rejected", "needs-human"}),
    "needs-info": frozenset({"intake", "rejected"}),
    "spec": frozenset({"build", "needs-human"}),
    "build": frozenset({"gate", "needs-human"}),
    "gate": frozenset({"review", "build", "needs-human"}),
    "review": frozenset({"approve", "build", "needs-human"}),
    "approve": frozenset({"merging", "needs-human"}),
    "merging": frozenset({"merged", "needs-human"}),
    "needs-human": frozenset({"intake", "spec", "build", "rejected"}),
    "merged": frozenset(),
    "rejected": frozenset(),
}
TERMINAL = frozenset({"merged", "rejected"})
WAITING = frozenset({"needs-info", "needs-human"})
ACTIVE = frozenset(STAGES) - TERMINAL - WAITING


class Refused(Exception):
    """The move is illegal or its proof is missing. The message says why."""


class Facts(Protocol):
    """What the machine needs to know about the world for one job."""

    def head(self) -> str:
        """The commit at the tip of the job's worktree."""

    def worktree_clean(self) -> bool:
        """No uncommitted or untracked changes in the worktree."""

    def commits_ahead(self) -> int:
        """Commits on the job branch that the remote base branch doesn't have."""

    def pr_merged(self) -> bool:
        """The job's PR is merged on the forge."""

    def author_replied(self) -> bool:
        """The issue author (or operator) commented after the last question."""

    def slot_available(self) -> bool:
        """Fewer than `concurrency` other jobs are in active stages."""


def resume_stage(escalated_from: str) -> str:
    """Where a job goes back to after a person's feedback."""
    return escalated_from if escalated_from in ("intake", "spec") else "build"


@dataclass
class _Move:
    job: Job
    cfg: Config
    dir: Path
    effects: list[Effect] = field(default_factory=list)

    def effect(self, kind: str, **args: Any) -> None:
        self.effects.append(Effect(kind=kind, key=f"{self.job.id}:{self.job.seq}:{len(self.effects)}", args=args))

    def comment(self, body: str) -> None:
        """Comment on the PR when there is one, else on the issue."""
        if self.job.pr:
            self.effect("comment", on="pr", number=self.job.pr, body=body)
        else:
            self.effect("comment", on="issue", number=self.job.issue, body=body)

    def labels(self, add: tuple[str, ...] = (), remove: tuple[str, ...] = ()) -> None:
        self.effect("labels", issue=self.job.issue, add=list(add), remove=list(remove))

    def read(self, name: str, kind: str) -> files.AgentFile:
        path = self.dir / name
        ui = "ui" in ((self.job.intake or {}).get("surfaces") or [])
        try:
            return files.read(path, kind, require_edge_cases=(kind == "spec" and ui))
        except FileNotFoundError:
            raise Refused(f"{name} doesn't exist") from None
        except MalformedFile as e:
            raise Refused(f"{name} is malformed: {e.reason}") from None

    def round_file(self, name: str) -> str:
        return f"round-{self.job.round}/{name}"

    def next_round(self) -> None:
        self.job.round += 1
        self.job.gate = None
        self.job.reviews = {}


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise Refused(msg)


def advance(
    job: Job, target: str, *, cfg: Config, job_dir: Path, facts: Facts, reason: str | None = None
) -> tuple[Job, list[Effect]]:
    old = job.stage
    require(target in STAGES, f"{job.id}: unknown stage {target!r}")
    legal = target in TRANSITIONS[old] or (target == "merged" and old not in TERMINAL)
    require(legal, f"{job.id}: {old} → {target} is not a legal transition")
    require(not job.pending, f"{job.id}: {len(job.pending)} pending effect(s) must run first")
    if reason is not None and target != "needs-human":
        raise ValueError("a reason is only for escalating to needs-human")

    m = _Move(job=copy.deepcopy(job), cfg=cfg, dir=job_dir)
    m.job.seq += 1

    if target == "merged":
        _to_merged(m, facts)
    elif target == "rejected":
        _to_rejected(m)
    elif target == "needs-human":
        _to_needs_human(m, facts, reason)
    else:
        _HANDLERS[old](m, target, facts)

    if old == "needs-human" and target != "rejected":
        m.labels(remove=(cfg.needs_human_label,))

    if target in TERMINAL and m.job.reviewers:  # reviewers are routed when the worktree is created
        m.effect("worktree_remove", path=m.job.worktree, branch=m.job.branch)

    m.job.stage = target
    m.job.stage_started = now()
    m.job.ended = now() if target in TERMINAL | WAITING else None
    return m.job, m.effects


# ---- Moves out of each stage ----------------------------------------------------


def _from_intake(m: _Move, target: str, facts: Facts) -> None:
    f = m.read("intake.md", "intake")
    decision = f.header["DECISION"]
    want = {"spec": "ACCEPT", "needs-info": "NEEDS-INFO"}[target]
    require(decision == want, f"intake.md says DECISION: {decision}, not {want}")
    if target == "spec":
        surfaces = [] if f.header["SURFACES"] == "none" else [s.strip() for s in f.header["SURFACES"].split(",")]
        try:
            m.job.reviewers = route.reviewers(m.cfg, f.header["RISK"], surfaces)
        except route.RouteError as e:
            raise Refused(f"intake.md can't be routed: {e}") from None
        m.job.intake = {
            "decision": decision,
            "risk": f.header["RISK"],
            "surfaces": surfaces,
            "rescoped": f.header["RESCOPED"] == "yes",
        }
        title = f"### Puxirum intake: ACCEPT (risk {m.job.intake['risk']}, surfaces: {', '.join(surfaces) or 'none'})"
        m.comment(f"{title}\n\n{_body(f.text)}")
        m.effect("worktree_add", path=m.job.worktree, branch=m.job.branch, base=m.cfg.base_branch)
    else:
        m.job.questions += 1
        m.comment(f"### Puxirum intake: NEEDS-INFO\n\n{_body(f.text)}")
        m.labels(add=(m.cfg.needs_info_label,))


def _from_needs_info(m: _Move, target: str, facts: Facts) -> None:  # → intake
    require(facts.author_replied(), "the issue author hasn't replied since the last question")
    require(facts.slot_available(), "no free slot")
    m.effect("archive", src="intake.md", dst=f"intake-{m.job.questions}.md")
    m.effect("refresh_issue")
    m.labels(remove=(m.cfg.needs_info_label,))
    m.job.intake = None


def _from_spec(m: _Move, target: str, facts: Facts) -> None:  # → build
    m.read("spec.md", "spec")
    m.job.round_limit = m.cfg.max_rounds
    m.next_round()


def _from_build(m: _Move, target: str, facts: Facts) -> None:  # → gate
    f = m.read("build.md", "build")
    require(f.header["STATUS"] == "READY", f"build.md says STATUS: {f.header['STATUS']}, not READY")
    require(facts.worktree_clean(), "the worktree has uncommitted changes")
    require(facts.commits_ahead() > 0, f"{m.job.branch} has no commits on top of {m.cfg.base_branch}")
    m.job.head = facts.head()
    m.effect("push", path=m.job.worktree, branch=m.job.branch)
    if not m.job.pr:
        spec_title = m.read("spec.md", "spec").text.split("\n", 1)[0][2:].strip()
        m.effect("ensure_pr", branch=m.job.branch, base=m.cfg.base_branch, title=spec_title,
                 body=f"Closes #{m.job.issue}\n\n" + "\n".join(f"- {s}" for s in f.summary))


def _from_gate(m: _Move, target: str, facts: Facts) -> None:  # → review | build
    f = m.read(m.round_file("checks.md"), "checks")
    head = facts.head()
    require(f.header["COMMIT"] == head, f"checks.md is for {f.header['COMMIT'][:7]}, but HEAD is {head[:7]}")
    require(head == m.job.head, f"HEAD moved since the build ({m.job.head and m.job.head[:7]} → {head[:7]})")
    result = f.header["GATE"]
    if target == "review":
        require(result == "PASS", "the gate didn't pass")
        m.job.gate = "PASS"
        m.job.reviews = {r: "pending" for r in m.job.reviewers}
    else:
        require(result == "FAIL", "the gate passed")
        require(m.job.round < m.job.round_limit,
                f"round {m.job.round} of {m.job.round_limit} was the last; escalate instead")
        m.next_round()


def _from_review(m: _Move, target: str, facts: Facts) -> None:  # → approve | build
    changes = _changes(m)
    if target == "approve":
        require(not changes, f"reviews want CHANGES: {', '.join(changes)}")
        require(facts.head() == m.job.head, "HEAD moved since the gate; reviewers must not commit")
    else:
        require(bool(changes), "every review passed")
        require(m.job.round < m.job.round_limit,
                f"round {m.job.round} of {m.job.round_limit} was the last; escalate instead")
        m.next_round()


def _from_approve(m: _Move, target: str, facts: Facts) -> None:  # → merging
    f = m.read("decision.md", "decision")
    require(f.header["DECISION"] == "APPROVE", f"decision.md says DECISION: {f.header['DECISION']}, not APPROVE")
    require(facts.head() == m.job.head, "HEAD moved since the gate")


def _from_needs_human(m: _Move, target: str, facts: Facts) -> None:  # → intake | spec | build
    k = len(m.job.escalations)
    require(k > m.job.feedback and (m.dir / f"feedback-{k}.md").is_file(),
            "send feedback first: `puxirum feedback`")
    want = resume_stage(m.job.escalations[-1]["from"])
    require(target == want, f"this escalation resumes at {want}, not {target}")
    require(facts.slot_available(), "no free slot")
    m.job.feedback = k
    if target == "intake":
        m.effect("archive", src="intake.md", dst=f"intake-h{k}.md")
        m.job.intake = None
    elif target == "build":
        m.job.round_limit = m.job.round + m.cfg.max_rounds
        m.next_round()


_HANDLERS = {
    "intake": _from_intake,
    "needs-info": _from_needs_info,
    "spec": _from_spec,
    "build": _from_build,
    "gate": _from_gate,
    "review": _from_review,
    "approve": _from_approve,
    "needs-human": _from_needs_human,
}


# ---- Moves into terminal and waiting stages ---------------------------------------


def _to_merged(m: _Move, facts: Facts) -> None:
    require(m.job.pr is not None and facts.pr_merged(), "the PR isn't merged")
    m.effect("delete_remote_branch", branch=m.job.branch)  # GitHub may have deleted it already
    if m.job.stage == "needs-info":
        m.labels(remove=(m.cfg.needs_info_label,))


def _to_rejected(m: _Move) -> None:
    old = m.job.stage
    if old == "intake":
        f = m.read("intake.md", "intake")
        require(f.header["DECISION"] == "REJECT", f"intake.md says DECISION: {f.header['DECISION']}, not REJECT")
        m.comment(f"### Puxirum intake: REJECT\n\n{_body(f.text)}")
        m.labels(remove=(m.cfg.queue_label,))
        return
    rejection = m.dir / "rejection.md"
    require(rejection.is_file(), "reject a waiting job with `puxirum reject`")
    m.comment(f"### Puxirum: rejected\n\n{_body(rejection.read_text(encoding='utf-8'))}")
    waiting = m.cfg.needs_info_label if old == "needs-info" else m.cfg.needs_human_label
    m.labels(remove=(m.cfg.queue_label, waiting))
    if m.job.pr:
        m.effect("pr_close", number=m.job.pr)
        m.effect("delete_remote_branch", branch=m.job.branch)


def _to_needs_human(m: _Move, facts: Facts, reason: str | None) -> None:
    old = m.job.stage
    if reason is None:
        reason = _own_escalation(m, old)
    k = len(m.job.escalations) + 1
    m.job.escalations.append({"from": old, "round": m.job.round, "reason": reason, "at": now()})
    m.effect("write_file", name=f"escalation-{k}.md",
             text=f"ESCALATED-FROM: {old}\nROUND: {m.job.round}\n\n## Why\n{reason}\n")
    if m.job.pr:
        m.effect("pr_ready", number=m.job.pr)
    m.comment(f"### Puxirum: needs a human\n\n{reason}")
    m.labels(add=(m.cfg.needs_human_label,))


def _own_escalation(m: _Move, old: str) -> str:
    """The reason for an escalation that a stage's own files justify."""
    if old == "build":
        f = m.read("build.md", "build")
        require(f.header["STATUS"] == "BLOCKED", "build.md isn't BLOCKED; give a reason to escalate")
        return "The builder is blocked:\n\n" + (f.section("Blocked") or "")
    if old == "gate":
        f = m.read(m.round_file("checks.md"), "checks")
        require(f.header["GATE"] == "FAIL", "the gate passed")
        require(m.job.round >= m.job.round_limit, "rounds remain; go back to build")
        return f"The gate failed in round {m.job.round}, the last allowed round. See {m.round_file('checks.md')}."
    if old == "review":
        changes = _changes(m)
        require(bool(changes), "every review passed")
        require(m.job.round >= m.job.round_limit, "rounds remain; go back to build")
        return f"Review rounds are exhausted. Reviewers still want changes in round {m.job.round}: {', '.join(changes)}."
    if old == "approve":
        f = m.read("decision.md", "decision")
        require(f.header["DECISION"] == "ESCALATE", "decision.md doesn't ESCALATE")
        return f.section("Why") or ""
    raise Refused(f"escalating from {old} needs a reason")


def _changes(m: _Move) -> list[str]:
    """Reviewers that want changes, after checking every routed review is present and valid."""
    verdicts = {}
    for r in m.job.reviewers:
        verdicts[r] = m.read(m.round_file(f"review-{r}.md"), "review").header["VERDICT"]
    m.job.reviews = verdicts
    return [r for r, v in verdicts.items() if v == "CHANGES"]


def _body(text: str) -> str:
    """Everything after the header block."""
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""
