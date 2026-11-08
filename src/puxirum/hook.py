"""Claude Code hooks Puxirum installs for its agents.

`stop-checks` is the builder's Stop hook. When the builder tries to finish, it
runs the project's checks in the worktree and checks the worktree is clean. On
a failure it blocks the stop once (exit 2), so the builder sees the output and
can fix it in the same run instead of costing a whole gate round. A second stop
always goes through: the gate has the final word.

Run as `python -m puxirum.hook stop-checks`, with PUXIRUM_WORKTREE and
PUXIRUM_CHECKS in the environment and the hook event on stdin.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

TAIL_LINES = 40


def stop_checks(event: dict, env: dict[str, str], timeout_s: float = 1800) -> tuple[int, str]:
    if event.get("stop_hook_active"):
        return 0, ""
    worktree, checks = env.get("PUXIRUM_WORKTREE"), env.get("PUXIRUM_CHECKS")
    if not worktree or not checks:
        return 0, ""
    status = subprocess.run(["git", "status", "--porcelain"], cwd=worktree, capture_output=True, text=True)
    if status.stdout.strip():
        return 2, (
            "The worktree has uncommitted changes, and the coordinator refuses a dirty worktree. "
            "Commit them or remove them, then finish:\n\n" + status.stdout.strip()
        )
    try:
        res = subprocess.run(
            ["bash", checks], cwd=worktree, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL
        )
    except subprocess.TimeoutExpired:
        return 2, f"The checks didn't finish within {timeout_s:.0f}s. The gate will fail too; find out why."
    if res.returncode != 0:
        tail = "\n".join((res.stdout + res.stderr).rstrip().splitlines()[-TAIL_LINES:])
        return 2, (
            f"`bash {checks}` fails in your worktree (exit {res.returncode}), so the gate will reject this "
            "build. Fix it, or write STATUS: BLOCKED in build.md if you can't.\n\n" + tail
        )
    return 0, ""


def main(argv: list[str]) -> int:
    if argv != ["stop-checks"]:
        print("usage: python -m puxirum.hook stop-checks", file=sys.stderr)
        return 1
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    timeout = float(os.environ.get("PUXIRUM_CHECKS_TIMEOUT", "1800"))
    code, message = stop_checks(event, dict(os.environ), timeout)
    if message:
        print(message, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
