"""Job state on disk: the only code that writes `job.json` and `events.jsonl`.

Layout, under `<repo>/.puxirum/state/`:

    lock                    flock target for every write
    jobs/<job-id>/job.json  the job (rewritten atomically)
    jobs/<job-id>/events.jsonl  append-only timeline

Writers take the store lock, load, change, and save inside it. `save` writes a
temporary file, fsyncs it and renames it over `job.json`, so a crash leaves
either the old or the new job, never half of one.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path(".puxirum") / "state"
SCHEMA = 1
SLUG_WORDS = 4


class StoreError(Exception):
    pass


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Effect:
    """A side effect a transition owes the world, executed after the job is saved.

    `key` is unique per job and makes the effect idempotent: executors use it to
    recognise work that was already done before a crash.
    """

    kind: str
    key: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    id: str
    issue: int
    title: str
    branch: str
    worktree: str
    stage: str = "intake"
    round: int = 0
    round_limit: int = 0
    seq: int = 0
    intake: dict[str, Any] | None = None
    reviewers: dict[str, str] = field(default_factory=dict)
    reviews: dict[str, str] = field(default_factory=dict)
    gate: str | None = None
    head: str | None = None
    pr: int | None = None
    pr_url: str | None = None
    questions: int = 0
    escalations: list[dict[str, Any]] = field(default_factory=list)
    feedback: int = 0
    pending: list[Effect] = field(default_factory=list)
    attempts: dict[str, int] = field(default_factory=dict)  # agent/step key -> runs started
    done: list[str] = field(default_factory=list)  # agent keys whose run finished and wrote its file
    last_error: str | None = None
    cost_usd: float = 0.0
    agent_seconds: float = 0.0
    created: str = field(default_factory=now)
    stage_started: str = field(default_factory=now)
    ended: str | None = None
    schema: int = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        if data.get("schema") != SCHEMA:
            raise StoreError(f"job {data.get('id')}: schema {data.get('schema')}, expected {SCHEMA}")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise StoreError(f"job {data.get('id')}: unknown field {unknown[0]}")
        data = dict(data)
        data["pending"] = [Effect(**e) for e in data.get("pending", [])]
        return cls(**data)


def slugify(title: str) -> str:
    """Up to four ASCII words of the title: "Editar título" → "editar-titulo"."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", ascii_title.lower())[:SLUG_WORDS]
    return "-".join(words) or "issue"


class Store:
    def __init__(self, repo: Path):
        self.repo = repo
        self.root = repo / STATE_DIR
        self.jobs_dir = self.root / "jobs"

    # ---- locking ---------------------------------------------------------------

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive lock over the whole store. Not reentrant."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        with open(self.root / "lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    # ---- reading ----------------------------------------------------------------

    def job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(r"\d{3,}-[a-z0-9-]+", job_id):
            raise StoreError(f"bad job id {job_id!r}")
        return self.jobs_dir / job_id

    def load(self, job_id: str) -> Job:
        path = self.job_dir(job_id) / "job.json"
        try:
            return Job.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise StoreError(f"no job {job_id}") from None

    def all(self) -> list[Job]:
        if not self.jobs_dir.is_dir():
            return []
        return [self.load(p.parent.name) for p in sorted(self.jobs_dir.glob("*/job.json"))]

    def find(self, ref: str | int) -> Job:
        """A job by id, or by issue number."""
        if isinstance(ref, int) or str(ref).isdigit():
            matches = [j for j in self.all() if j.issue == int(ref)]
            if not matches:
                raise StoreError(f"no job for issue #{ref}")
            return matches[-1]
        return self.load(str(ref))

    def events(self, job_id: str) -> list[dict[str, Any]]:
        path = self.job_dir(job_id) / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # ---- writing (callers hold the lock) ----------------------------------------

    def create(self, issue: int, title: str, branch_prefix: str, worktrees_dir: str) -> Job:
        """A new intake job for an issue. One job per issue, ever."""
        jobs = self.all()
        for j in jobs:
            if j.issue == issue:
                raise StoreError(f"issue #{issue} already has job {j.id} ({j.stage})")
        n = max((int(j.id.split("-", 1)[0]) for j in jobs), default=0) + 1
        job_id = f"{n:03d}-{slugify(title)}"
        job = Job(
            id=job_id,
            issue=issue,
            title=title,
            branch=f"{branch_prefix}{job_id}",
            worktree=f"{worktrees_dir}/{job_id}",
        )
        self.job_dir(job_id).mkdir(parents=True)
        self.save(job)
        self.event(job_id, "created", issue=issue, title=title)
        return job

    def save(self, job: Job) -> None:
        d = self.job_dir(job.id)
        d.mkdir(parents=True, exist_ok=True)
        write_atomic(d / "job.json", json.dumps(job.to_dict(), indent=2, ensure_ascii=False) + "\n")

    def event(self, job_id: str, type_: str, **data: Any) -> None:
        line = json.dumps({"at": now(), "type": type_, **data}, ensure_ascii=False)
        with open(self.job_dir(job_id) / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
