"""Processes a crashed run left behind.

Every agent and dev server the core starts runs in its own process group, so
that stopping it stops everything it started. The flip side: when the core
itself is killed, those groups keep running, and an agent keeps spending. So
each one leaves `<name>.pid` next to its log while it runs, and the next
`puxirum run` stops any group whose file is still there, before it starts work.

A pid can be reused by an unrelated program, so a group is only stopped when its
leader still runs the program that was recorded.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

GRACE_S = 5.0


def record(path: Path, pid: int, program: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "program": program}) + "\n", encoding="utf-8")


def forget(path: Path) -> None:
    path.unlink(missing_ok=True)


@contextlib.contextmanager
def tracked(path: Path, pid: int, program: str) -> Iterator[None]:
    record(path, pid, program)
    try:
        yield
    finally:
        forget(path)


def _cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _same_program(pid: int, program: str) -> bool:
    argv = _cmdline(pid)
    return bool(argv) and any(Path(a).name == Path(program).name for a in argv[:2])


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap(paths: Iterable[Path], grace_s: float = GRACE_S) -> list[str]:
    """Stop the groups the files name, if they still run their program. Returns what was stopped."""
    stopped = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid, program = int(data["pid"]), str(data["program"])
        except (OSError, ValueError, KeyError, TypeError):
            forget(path)
            continue
        if _group_alive(pid) and _same_program(pid, program):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGTERM)
            deadline = time.monotonic() + grace_s
            while _group_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
            stopped.append(f"{path.stem} (pid {pid})")
        forget(path)
    return stopped
