"""Git operations on the main checkout and the job worktrees.

Every operation is safe to repeat after a crash: adding a worktree that already
exists on the right branch, removing one that is gone, or deleting a remote
branch that was already deleted all succeed without doing anything.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from puxirum.gate import dirty_paths

REMOTE = "origin"


class GitError(Exception):
    pass


class Git:
    def __init__(self, repo: Path):
        self.repo = repo

    def run(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        res = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True,
                             env={**os.environ, "LC_ALL": "C"})  # untranslated output, same on every machine
        if check and res.returncode != 0:
            raise GitError(f"`git {' '.join(args)}` failed: {(res.stderr or res.stdout).strip()}")
        return res

    def out(self, *args: str, cwd: Path | None = None) -> str:
        return self.run(*args, cwd=cwd).stdout.strip()

    def path(self, worktree: str) -> Path:
        return self.repo / worktree

    # ---- facts --------------------------------------------------------------------------

    def head(self, worktree: str) -> str:
        return self.out("rev-parse", "HEAD", cwd=self.path(worktree))

    def is_clean(self, worktree: str) -> bool:
        return not dirty_paths(self.path(worktree))

    def commits_ahead(self, worktree: str, base: str) -> int:
        return int(self.out("rev-list", "--count", f"{REMOTE}/{base}..HEAD", cwd=self.path(worktree)))

    def local_branch_exists(self, branch: str) -> bool:
        return self.run("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0

    def remote_branch_exists(self, branch: str) -> bool:
        return bool(self.out("ls-remote", "--heads", REMOTE, f"refs/heads/{branch}"))

    # ---- actions --------------------------------------------------------------------------

    def fetch(self, *refs: str) -> None:
        self.run("fetch", "--quiet", REMOTE, *refs)

    def worktree_add(self, worktree: str, branch: str, base: str) -> None:
        path = self.path(worktree)
        self.run("worktree", "prune")
        if path.exists():
            current = self.out("rev-parse", "--abbrev-ref", "HEAD", cwd=path)
            if current != branch:
                raise GitError(f"{worktree} exists but is on {current}, not {branch}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.local_branch_exists(branch):
            self.run("worktree", "add", "--quiet", str(path), branch)
        else:
            self.fetch(base)
            self.run("worktree", "add", "--quiet", "-b", branch, str(path), f"{REMOTE}/{base}")

    def worktree_remove(self, worktree: str, branch: str) -> None:
        path = self.path(worktree)
        if path.exists():
            self.run("worktree", "remove", "--force", str(path))
        self.run("worktree", "prune")
        if self.local_branch_exists(branch):
            self.run("branch", "-D", branch)

    def push(self, worktree: str, branch: str) -> None:
        """Push the job branch. Never forced: a rewritten history fails here."""
        self.run("push", "--quiet", "-u", REMOTE, f"HEAD:refs/heads/{branch}", cwd=self.path(worktree))

    def delete_remote_branch(self, branch: str) -> None:
        if self.remote_branch_exists(branch):
            self.run("push", "--quiet", REMOTE, "--delete", branch)

    def sync_with_base(self, worktree: str, base: str) -> tuple[bool, str]:
        """Merge the latest remote base into the job branch. On a conflict, abort and return the output."""
        path = self.path(worktree)
        self.fetch(base)
        res = self.run("merge", "--no-edit", f"{REMOTE}/{base}", cwd=path, check=False)
        if res.returncode != 0:
            self.run("merge", "--abort", cwd=path, check=False)
            return False, (res.stdout + res.stderr).strip()
        return True, res.stdout.strip()
