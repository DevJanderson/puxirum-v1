"""Real git repositories in a temporary folder: a bare `origin` and a main checkout."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


# Code under test runs git with the process environment: give it the same identity.
os.environ.update(GIT_ENV)


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr}")
    return res.stdout.strip()


class Repos:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.origin = root / "origin.git"
        self.main = root / "main"
        git(root, "init", "--bare", "-b", "main", str(self.origin))
        git(root, "clone", str(self.origin), str(self.main))
        git(self.main, "checkout", "-b", "main")

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def write(self, cwd: Path, files: dict[str, str | None]) -> None:
        for name, text in files.items():
            path = cwd / name
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)

    def commit(self, cwd: Path, files: dict[str, str | None], msg: str = "change") -> str:
        self.write(cwd, files)
        git(cwd, "add", "-A")
        git(cwd, "commit", "-q", "-m", msg)
        return git(cwd, "rev-parse", "HEAD")

    def push_main(self) -> None:
        git(self.main, "push", "-q", "origin", "main")
        git(self.main, "fetch", "-q", "origin")

    def worktree(self, branch: str) -> Path:
        path = self.main / ".worktrees" / branch.replace("/", "-")
        git(self.main, "worktree", "add", "-q", "-b", branch, str(path), "origin/main")
        return path
