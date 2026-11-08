"""Costs and times, from the jobs' event logs.

Every agent run is an `agent` event with its cost, seconds, model and the run
it belonged to. Every stage change is a `transition` event. From those:

- per job: cost by role and by model, agent time, active time (in stages that
  hold a slot) and waiting time (for the author or a person);
- per run (`puxirum run`): cost, wall-clock time and agent runs. The
  coordination itself is deterministic Python, so it costs nothing; the report
  says so explicitly, because in an LLM-coordinated factory it was most of the
  bill.

Runs whose cost the runner couldn't read are counted as `unpriced`, never as 0.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from puxirum.config import Config
from puxirum.machine import ACTIVE, TERMINAL
from puxirum.store import Job, Store, now, write_atomic


def parse_time(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@dataclass
class JobReport:
    id: str
    issue: int
    stage: str
    round: int
    agents: int = 0
    unpriced: int = 0
    cost_usd: float = 0.0
    agent_seconds: float = 0.0
    active_seconds: float = 0.0
    waiting_seconds: float = 0.0
    by_role: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)

    @property
    def total_seconds(self) -> float:
        return self.active_seconds + self.waiting_seconds


def job_report(store: Store, job: Job, until: datetime | None = None) -> JobReport:
    r = JobReport(job.id, job.issue, job.stage, job.round)
    by_role: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    events = store.events(job.id)
    for ev in events:
        if ev["type"] != "agent":
            continue
        r.agents += 1
        r.agent_seconds += ev.get("seconds") or 0.0
        cost = ev.get("cost_usd")
        if cost is None:
            r.unpriced += 1
            continue
        r.cost_usd += cost
        name = f"{ev['role']}:{ev['lens']}" if ev.get("lens") else ev["role"]
        by_role[name] += cost
        by_model[ev.get("model") or "?"] += cost
    r.by_role, r.by_model = dict(by_role), dict(by_model)

    # Time in each stage, from the creation and the transitions.
    marks = [(parse_time(ev["at"]), ev["to"]) for ev in events if ev["type"] == "transition"]
    created = next((parse_time(ev["at"]) for ev in events if ev["type"] == "created"), None)
    if created is not None:
        stage, since = "intake", created
        end = until or datetime.now(UTC)
        for at, to in marks + [(end, None)]:
            if stage in TERMINAL:
                break
            span = max((at - since).total_seconds(), 0.0)
            if stage in ACTIVE:
                r.active_seconds += span
            else:
                r.waiting_seconds += span
            if to is None:
                break
            stage, since = to, at
    return r


# ---- runs ------------------------------------------------------------------------------------


def runs_dir(store: Store) -> Path:
    return store.root / "runs"


def write_run(store: Store, run_id: str, started: str, only: int | None) -> dict:
    """Summarise one `puxirum run` from the agent events it produced."""
    agents, unpriced, cost, jobs = 0, 0, 0.0, set()
    for job in store.all():
        for ev in store.events(job.id):
            if ev["type"] == "agent" and ev.get("run") == run_id:
                agents += 1
                jobs.add(job.id)
                if ev.get("cost_usd") is None:
                    unpriced += 1
                else:
                    cost += ev["cost_usd"]
    ended = now()
    record = {
        "id": run_id, "started": started, "ended": ended, "only": only,
        "wall_seconds": (parse_time(ended) - parse_time(started)).total_seconds(),
        "agents": agents, "unpriced": unpriced, "cost_usd": round(cost, 6), "coordination_usd": 0.0,
        "jobs": sorted(jobs),
    }
    d = runs_dir(store)
    d.mkdir(parents=True, exist_ok=True)
    write_atomic(d / f"{run_id}.json", json.dumps(record, indent=2) + "\n")
    return record


def runs(store: Store) -> list[dict]:
    d = runs_dir(store)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


# ---- text -------------------------------------------------------------------------------------


def duration(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def render(store: Store, cfg: Config) -> str:
    jobs = [job_report(store, j) for j in store.all()]
    lines = []
    if not jobs:
        return "No jobs yet.\n"
    header = ("JOB", "ISSUE", "STAGE", "ROUND", "AGENTS", "COST", "ACTIVE", "WAITING")
    rows = [header] + [(r.id, f"#{r.issue}", r.stage, str(r.round), str(r.agents),
                        f"${r.cost_usd:.2f}" + ("*" if r.unpriced else ""),
                        duration(r.active_seconds), duration(r.waiting_seconds)) for r in jobs]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    lines += ["  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in rows]

    total = sum(r.cost_usd for r in jobs)
    unpriced = sum(r.unpriced for r in jobs)
    by_role: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    for r in jobs:
        for k, v in r.by_role.items():
            by_role[k] += v
        for k, v in r.by_model.items():
            by_model[k] += v
    lines += ["", f"Agents:        ${total:.2f} in {sum(r.agents for r in jobs)} runs"
              + (f" ({unpriced} unpriced, marked *)" if unpriced else "")]
    lines += ["Coordination:  $0.00 (deterministic; no model involved)"]
    lines += [f"Total:         ${total:.2f}"]
    if by_role:
        lines += ["", "By role:  " + ", ".join(f"{k} ${v:.2f}"
                                               for k, v in sorted(by_role.items(), key=lambda x: -x[1]))]
        lines += ["By model: " + ", ".join(f"{k} ${v:.2f}" for k, v in sorted(by_model.items(), key=lambda x: -x[1]))]
    all_runs = runs(store)
    if all_runs:
        wall = sum(r["wall_seconds"] for r in all_runs)
        lines += ["", f"Runs: {len(all_runs)}, wall-clock {duration(wall)}"]
    if cfg.baseline_usd is not None:
        lines += ["", f"Baseline ({cfg.baseline_label}): ${cfg.baseline_usd:.2f}"
                  + (f", {duration(cfg.baseline_minutes * 60)}" if cfg.baseline_minutes else "")]
        ratio = total / cfg.baseline_usd if cfg.baseline_usd else 0
        lines += [f"This project:  ${total:.2f} ({ratio:.0%} of the baseline)"
                  + (f", {duration(sum(r['wall_seconds'] for r in all_runs))} of runs" if all_runs else "")]
    return "\n".join(lines) + "\n"


def as_json(store: Store) -> str:
    jobs = []
    for j in store.all():
        r = job_report(store, j)
        jobs.append({**r.__dict__, "total_seconds": r.total_seconds})
    return json.dumps({"jobs": jobs, "runs": runs(store), "coordination_usd": 0.0}, indent=2) + "\n"
