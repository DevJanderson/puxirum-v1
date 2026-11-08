"""Fake agents: functions that do an agent's job deterministically, for FakeRunner."""

from __future__ import annotations

from pathlib import Path

from puxirum.runner import AgentTask

from tests.gitrepo import git

SUMMARY = "## Summary\n- one\n- two\n- three\n"
SPEC = (
    "# {title}\n\n" + SUMMARY
    + "\n## Context\nx\n\n## Requirements\nx\n\n## Acceptance criteria\n1. Works.\n\n## Edge cases\n- Very long titles.\n\n## Out of scope\nx\n\n## Assumptions\nx\n"
)


def intake(decision="ACCEPT", risk="low", surfaces="none"):
    def run(task: AgentTask):
        if decision == "ACCEPT":
            head = f"DECISION: ACCEPT\nRISK: {risk}\nSURFACES: {surfaces}\nRESCOPED: no\n\n"
            task.output.write_text(head + SUMMARY)
        elif decision == "NEEDS-INFO":
            task.output.write_text("DECISION: NEEDS-INFO\n\n" + SUMMARY + "\n## Questions\n1. Which list?\n")
        else:
            task.output.write_text("DECISION: REJECT\n\n" + SUMMARY + "\n## Reason\nOut of scope.\n")
    return run


def spec(title="Feature"):
    def run(task: AgentTask):
        task.output.write_text(SPEC.format(title=title))
    return run


def builder(files_by_round=None, status="READY"):
    """Commit `files_by_round[round]` (or a default change) in the worktree and write build.md."""
    def run(task: AgentTask):
        rnd = task.vars["round"]
        changes = (files_by_round or {}).get(rnd, {f"feature-{rnd}.txt": f"round {rnd}\n"})
        if status == "READY":
            commit(Path(task.cwd), changes, f"round {rnd}")
            task.output.write_text("STATUS: READY\n\n" + SUMMARY)
        else:
            task.output.write_text("STATUS: BLOCKED\n\n" + SUMMARY + "\n## Blocked\nNeeds a product decision.\n")
    return run


def reviewer(verdicts=("PASS",)):
    """Verdict per round, repeating the last one."""
    def run(task: AgentTask):
        v = verdicts[min(task.vars["round"], len(verdicts)) - 1]
        findings = "None." if v == "PASS" else "1. app.txt:1 broken"
        task.output.write_text(f"VERDICT: {v}\n\n" + SUMMARY + f"\n## Findings\n{findings}\n")
    return run


def approver(decision="APPROVE"):
    def run(task: AgentTask):
        task.output.write_text(f"DECISION: {decision}\n\n" + SUMMARY + "\n## Why\nChecked.\n")
    return run


def happy(**overrides):
    scripts = {"intake": intake(), "spec": spec(), "builder": builder(), "reviewer": reviewer(),
               "approver": approver()}
    scripts.update(overrides)
    return scripts


def commit(cwd: Path, changes: dict[str, str | None], msg: str) -> str:
    for name, text in changes.items():
        path = cwd / name
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


def sequence(*scripts):
    """A script that runs the next of `scripts` each time, repeating the last."""
    calls = {"n": 0}

    def run(task: AgentTask):
        i = min(calls["n"], len(scripts) - 1)
        calls["n"] += 1
        return scripts[i](task)
    return run
