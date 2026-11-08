"""The live feed: one line per step of every running agent.

Each agent streams its events into `jobs/<job>/logs/<role>-r<round>-a<attempt>.jsonl`.
The feed follows those files and turns each event into a short line, such as

    14:02:11  #7 builder r2        Edit src/list.ts
    14:02:40  #7 builder r2        ✓ done · US$ 0.09 · 1m40s

It only reads files the runner already writes, so it can run anywhere: in the
workbench's Agentes pane, or by hand with `puxirum feed`. A line cut off in the
middle of a write is read on the next poll, once it is whole.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from puxirum.report import duration
from puxirum.store import Store

STEM = re.compile(r"^(?P<role>[a-z]+(?:-[a-z]+)?)-r(?P<round>\d+)-a(?P<attempt>\d+)$")
MAX_TEXT = 90
COLOURS = (36, 35, 33, 32, 34, 31)


def _short(text: str, limit: int = MAX_TEXT) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _path(value: object, roots: Sequence[Path]) -> str:
    """The path relative to the deepest root it is under: the job's folder, the worktree or the repository."""
    p = str(value or "")
    for root in sorted(roots, key=lambda r: -len(str(r))):
        base = f"{root}/"
        if p.startswith(base):
            return p[len(base) :]
    return p


def describe(event: dict, roots: Path | Sequence[Path] = ()) -> list[str]:
    """The lines one stream event is worth; most events are worth none."""
    roots = (roots,) if isinstance(roots, Path) else tuple(roots)
    kind = event.get("type")
    if kind == "assistant":
        lines = []
        for part in (event.get("message") or {}).get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "tool_use":
                continue
            name, args = str(part.get("name") or "?"), part.get("input") or {}
            if name in ("Read", "Edit", "Write", "NotebookEdit"):
                lines.append(f"{name} {_path(args.get('file_path') or args.get('notebook_path'), roots)}")
            elif name == "Bash":
                lines.append(_short(f"$ {args.get('command', '')}"))
            elif name in ("Grep", "Glob"):
                lines.append(_short(f"{name} {args.get('pattern', '')}"))
            else:
                lines.append(name)
        return lines
    if kind == "result":
        cost = event.get("total_cost_usd")
        seconds = (event.get("duration_ms") or 0) / 1000
        tail = (f" · US$ {cost:.2f}" if isinstance(cost, (int, float)) else "") + f" · {duration(seconds)}"
        lines = [f"⛔ denied {_short(_denial(d), 60)}" for d in event.get("permission_denials") or []]
        if event.get("is_error"):
            lines.append(f"✗ {event.get('subtype') or 'error'}{tail}")
        else:
            lines.append(f"✓ done{tail}")
        return lines
    return []


def _denial(d: object) -> str:
    if not isinstance(d, dict):
        return str(d)
    args = d.get("tool_input") or {}
    detail = args.get("command") or args.get("file_path") or ""
    return f"{d.get('tool_name', '?')} {detail}".strip()


@dataclass
class _Tail:
    path: Path
    label: str
    roots: tuple[Path, ...]
    offset: int = 0


@dataclass
class Feed:
    """Follows every agent stream under a store. `poll` returns the new lines since the last call."""

    store: Store
    colour: bool = False
    width: Callable[[], int | None] = lambda: None  # the pane's width, to keep each step on one line
    clock: Callable[[], float] = time.time
    replay: int = 0  # how many of the agents that already finished, the latest ones, to read again from the start
    _tails: dict[Path, _Tail] = field(default_factory=dict)
    _issues: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Agents that already finished are history, but for the latest `replay` of them; the others start from their
        # first line.
        finished = [p for p in self._streams() if _finished(p)]
        recent = set(sorted(finished, key=_mtime)[-self.replay :]) if self.replay else set()
        for path in self._streams():
            tail = self._tail(path)
            if path in finished and path not in recent:
                tail.offset = path.stat().st_size

    def _streams(self) -> list[Path]:
        jobs = self.store.jobs_dir
        return sorted(jobs.glob("*/logs/*.jsonl")) if jobs.is_dir() else []

    def _tail(self, path: Path) -> _Tail:
        if path not in self._tails:
            job_id = path.parent.parent.name
            m = STEM.match(path.stem)
            role = m["role"].replace("-", ":") if m else path.stem
            rnd = f" r{m['round']}" if m else ""
            issue = self._issue(job_id)
            roots = (self.store.repo, self.store.job_dir(job_id), *self._worktree(job_id))
            self._tails[path] = _Tail(path, f"#{issue} {role}{rnd}" if issue else f"{job_id} {role}{rnd}", roots)
        return self._tails[path]

    def _issue(self, job_id: str) -> int | None:
        if job_id not in self._issues:
            try:
                self._issues[job_id] = self.store.load(job_id).issue
            except Exception:  # noqa: BLE001 - a job being written right now is labelled by its id
                return None
        return self._issues[job_id]

    def _worktree(self, job_id: str) -> tuple[Path, ...]:
        try:
            return (self.store.repo / self.store.load(job_id).worktree,)
        except Exception:  # noqa: BLE001
            return ()

    def steps(self) -> list[tuple[Path, str, str]]:
        """The new steps since the last call, as (stream, label, text)."""
        out = []
        for path in self._streams():
            tail = self._tail(path)
            for event in _read_new(tail):
                for text in describe(event, tail.roots):
                    out.append((path, tail.label, text))
        return out

    def entries(self) -> list[tuple[str, str]]:
        """The new steps since the last call, as (label, text)."""
        return [(label, text) for _, label, text in self.steps()]

    def poll(self) -> list[str]:
        new = self.entries()
        width = max([len(t.label) for t in self._tails.values()] + [18])
        return [self._line(label, text, width) for label, text in new]

    def _line(self, label: str, text: str, width: int) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(self.clock()))
        cols = self.width()
        if cols:
            room = max(cols - len(stamp) - width - 4, 10)
            text = text if len(text) <= room else text[: room - 1] + "…"
        if not self.colour:
            return f"{stamp}  {label.ljust(width)}  {text}"
        colour = COLOURS[sum(map(ord, label.split(" ")[0])) % len(COLOURS)]
        return f"\x1b[2m{stamp}\x1b[0m  \x1b[{colour}m{label.ljust(width)}\x1b[0m  {text}"

    def follow(self, interval_s: float = 0.5) -> Iterator[str]:
        while True:
            yield from self.poll()
            time.sleep(interval_s)


def _read_new(tail: _Tail) -> list[dict]:
    try:
        with open(tail.path, "rb") as f:
            f.seek(tail.offset)
            chunk = f.read()
    except OSError:
        return []
    end = chunk.rfind(b"\n")
    if end < 0:
        return []
    tail.offset += end + 1
    events = []
    for raw in chunk[: end + 1].splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _finished(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            last = f.read().rstrip(b"\n").rsplit(b"\n", 1)[-1]
        return json.loads(last).get("type") == "result"
    except (OSError, ValueError, AttributeError):
        return False
