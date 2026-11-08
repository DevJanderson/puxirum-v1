"""The deterministic gate: does the job's branch pass the project's checks?

The gate runs the *main checkout's* checks script inside the job's worktree, so
a branch can never change the checks it is judged by. It fails when:

- the worktree has uncommitted changes (the result wouldn't belong to a commit);
- the branch modified, deleted or renamed away a file matching a protected
  pattern (creating new files is fine);
- the checks script exits non-zero or runs past the timeout.

It writes `round-N/checks.md` (or `merge-checks.md`) with the verdict and the
commit it tested, plus the full log in `checks.log`. Problems that are not the
branch's fault (no checks script, a broken repository) raise GateError instead
of producing a verdict.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from puxirum.config import Config

TAIL_LINES = 80
KILL_GRACE_S = 5


class GateError(Exception):
    """The gate couldn't run; this says nothing about the branch."""


@dataclass
class GateResult:
    verdict: str
    commit: str
    exit_code: int | None
    seconds: float
    timed_out: bool = False
    dirty: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    left_dirty: list[str] = field(default_factory=list)


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
    if res.returncode != 0:
        raise GateError(f"`git {' '.join(args)}` failed in {cwd}: {res.stderr.strip()}")
    return res.stdout


def dirty_paths(worktree: Path) -> list[str]:
    """Paths with uncommitted or untracked changes."""
    out = _git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = [e for e in out.split("\0") if e]
    paths, skip = [], False
    for e in entries:
        if skip:  # the second path of a rename entry
            skip = False
            continue
        paths.append(e[3:])
        skip = e[0] in "RC"
    return paths


def protected_changes(cfg: Config, worktree: Path, base_ref: str) -> list[str]:
    """Existing protected files the branch modified, deleted or renamed away, as `<status> <path>`."""
    out = _git(worktree, "diff", "--name-status", "-z", "--no-renames", f"{base_ref}...HEAD")
    fields_ = out.split("\0")
    hits = []
    for status, path in zip(fields_[0::2], fields_[1::2], strict=False):
        if status and status[0] != "A" and cfg.is_protected(path):
            hits.append(f"{status[0]} {path}")
    return hits


def run(
    cfg: Config,
    repo: Path,
    worktree: Path,
    out_dir: Path,
    *,
    merge: bool = False,
    base_ref: str | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float | None = None,
) -> GateResult:
    """Run the gate for the worktree's HEAD and write the report into `out_dir`."""
    checks = repo / cfg.checks
    if not checks.is_file():
        raise GateError(f"{cfg.checks} not found in the main checkout")
    if not worktree.is_dir():
        raise GateError(f"worktree {worktree} doesn't exist")
    base_ref = base_ref or f"origin/{cfg.base_branch}"
    _git(worktree, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "merge-checks" if merge else "checks"
    log_path = out_dir / f"{name}.log"

    commit = _git(worktree, "rev-parse", "HEAD").strip()
    dirty = dirty_paths(worktree)
    protected = protected_changes(cfg, worktree, base_ref)

    if dirty:
        log_path.write_text("checks not run: the worktree has uncommitted changes\n", encoding="utf-8")
        result = GateResult("FAIL", commit, None, 0.0, dirty=dirty, protected=protected)
    else:
        code, seconds, timed_out = _run_checks(checks, worktree, log_path, env, timeout_s or cfg.gate_timeout_s)
        left_dirty = dirty_paths(worktree)
        ok = code == 0 and not timed_out and not protected
        result = GateResult("PASS" if ok else "FAIL", commit, code, seconds, timed_out=timed_out,
                            protected=protected, left_dirty=left_dirty)

    _write_report(out_dir / f"{name}.md", log_path, result, merge, cfg)
    return result


def _run_checks(checks: Path, worktree: Path, log_path: Path, env: dict[str, str] | None,
                timeout_s: float) -> tuple[int | None, float, bool]:
    """Run the checks script in its own process group, killing the whole group on timeout."""
    start = time.monotonic()
    full_env = {**os.environ, **(env or {})}
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(["bash", str(checks)], cwd=worktree, env=full_env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code: int | None = proc.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            code = None
        else:
            # The script is done; don't leave its background children running.
            _kill_group(proc, grace=0)
    return code, time.monotonic() - start, timed_out


def _kill_group(proc: subprocess.Popen, grace: float = KILL_GRACE_S) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace or 0.1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _write_report(path: Path, log_path: Path, r: GateResult, merge: bool, cfg: Config) -> None:
    secs = f"{r.seconds:.0f}s"
    if r.dirty:
        checks_line = "checks not run: the worktree has uncommitted changes"
    elif r.timed_out:
        checks_line = f"checks timed out after {secs} and were stopped"
    elif r.exit_code == 0:
        checks_line = f"checks passed in {secs}"
    else:
        checks_line = f"checks failed with exit {r.exit_code} in {secs}"
    summary = [
        checks_line,
        "Protected paths: " + ("changed: " + ", ".join(r.protected) if r.protected else "none changed"),
        f"Commit {r.commit[:7]}" + (f", synced with the latest {cfg.base_branch} before merging" if merge else ""),
    ]
    lines = log_path.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()
    tail = "\n".join(lines[-TAIL_LINES:])
    parts = [
        f"GATE: {r.verdict}\nCOMMIT: {r.commit}\n",
        "## Summary\n" + "\n".join(f"- {s}" for s in summary) + "\n",
        "## Protected paths\n" + ("\n".join(f"- {p}" for p in r.protected) if r.protected else "None changed.") + "\n",
    ]
    if r.dirty:
        parts.append("## Uncommitted changes\n" + "\n".join(f"- {p}" for p in r.dirty) + "\n")
    if r.left_dirty:
        parts.append("## Notes\nThe checks left these paths changed in the worktree:\n"
                     + "\n".join(f"- {p}" for p in r.left_dirty) + "\n")
    parts.append(f"## Checks\n{checks_line}. Last {min(len(lines), TAIL_LINES)} lines of {log_path.name}:\n\n"
                 f"```\n{tail}\n```\n")
    path.write_text("\n".join(parts), encoding="utf-8")
