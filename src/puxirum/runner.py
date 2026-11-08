"""The runner: how an agent gets run. Phase 1 has only the interface and a fake.

An agent gets a task (its role, the paths it reads, the one file it writes) and
returns when it is done. The core never reads the agent's conversation: it
reads the output file and checks it against the contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class AgentTask:
    role: str  # intake | spec | builder | reviewer | approver
    lens: str | None  # the reviewer's lens (code, ux, ui, security); None for other roles
    job_id: str
    model: str
    cwd: Path  # where the agent works: the main checkout for intake, the worktree otherwise
    job_dir: Path
    output: Path  # the one file the agent writes
    vars: dict[str, Any] = field(default_factory=dict)  # issue, branch, base, round, port, retry, feedback...

    @property
    def name(self) -> str:
        return f"{self.role}:{self.lens}" if self.lens else self.role


@dataclass(frozen=True)
class AgentResult:
    exit_code: int
    seconds: float
    cost_usd: float | None = None
    log: Path | None = None


class Runner(Protocol):
    def run(self, task: AgentTask) -> AgentResult: ...


Script = Callable[[AgentTask], int | None]


class FakeRunner:
    """Runs a Python function per role instead of an agent. `scripts` maps a task
    name (`intake`, `builder`, `reviewer:ux`...) or a role to a function that does
    the agent's work and returns an exit code (None means 0)."""

    def __init__(self, scripts: dict[str, Script], cost_usd: float = 0.01):
        self.scripts = scripts
        self.cost_usd = cost_usd
        self.tasks: list[AgentTask] = []

    def run(self, task: AgentTask) -> AgentResult:
        self.tasks.append(task)
        script = self.scripts.get(task.name) or self.scripts.get(task.role)
        if script is None:
            raise KeyError(f"no fake script for {task.name}")
        start = time.monotonic()
        code = script(task)
        return AgentResult(0 if code is None else code, time.monotonic() - start, self.cost_usd)

    def names(self) -> list[str]:
        return [t.name for t in self.tasks]
