"""The code-hosting forge: issues, comments, labels and pull requests.

`Forge` is the interface the core uses. `GhForge` talks to GitHub through the
`gh` CLI; `FakeForge` keeps everything in memory for tests and dry runs. Every
mutating call is safe to repeat: adding a label twice or closing a closed PR is
not an error.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class ForgeError(Exception):
    pass


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    created_at: str


@dataclass
class Issue:
    number: int
    title: str
    body: str
    author: str
    url: str
    state: str = "OPEN"  # OPEN | CLOSED
    labels: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)


@dataclass
class PullRequest:
    number: int
    url: str
    head: str
    base: str
    title: str
    body: str
    state: str = "OPEN"  # OPEN | CLOSED | MERGED
    draft: bool = True
    comments: list[Comment] = field(default_factory=list)


class Forge(Protocol):
    def operator(self) -> str: ...
    def list_issues(self, label: str) -> list[Issue]: ...
    def issue(self, number: int) -> Issue: ...
    def comment(self, on: str, number: int, body: str) -> None: ...
    def comments(self, on: str, number: int) -> list[Comment]: ...
    def set_labels(self, issue: int, add: list[str], remove: list[str]) -> None: ...
    def find_prs(self, head: str) -> list[PullRequest]: ...
    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool) -> PullRequest: ...
    def pr(self, number: int) -> PullRequest: ...
    def mark_ready(self, number: int) -> None: ...
    def close_pr(self, number: int) -> None: ...
    def merge_pr(self, number: int, method: str) -> None: ...
    def labels(self) -> list[str]: ...
    def create_label(self, name: str, color: str, description: str) -> None: ...


# ---- In-memory forge ---------------------------------------------------------------


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FakeForge:
    """A forge in memory. `calls` records every mutating call, for assertions."""

    def __init__(self, operator: str = "operator"):
        self._operator = operator
        self.issues: dict[int, Issue] = {}
        self.prs: dict[int, PullRequest] = {}
        self.calls: list[tuple] = []
        self.fail: dict[str, Exception] = {}  # method name -> exception to raise once
        self._next = 1
        self.repo_labels: dict[str, tuple[str, str]] = {}

    # test helpers
    def add_issue(self, title: str, body: str = "", author: str = "author", labels=("puxirum",)) -> Issue:
        n = self._number()
        issue = Issue(n, title, body, author, f"https://forge.test/issues/{n}", labels=list(labels))
        self.issues[n] = issue
        return issue

    def add_comment(self, on: str, number: int, author: str, body: str) -> None:
        self._target(on, number).comments.append(Comment(author, body, _stamp()))

    def _number(self) -> int:
        n, self._next = self._next, self._next + 1
        return n

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise self.fail.pop(name)

    def _target(self, on: str, number: int):
        store = self.issues if on == "issue" else self.prs
        if number not in store:
            raise ForgeError(f"no {on} #{number}")
        return store[number]

    # Forge
    def operator(self) -> str:
        return self._operator

    def list_issues(self, label: str) -> list[Issue]:
        return [i for i in self.issues.values() if i.state == "OPEN" and label in i.labels]

    def issue(self, number: int) -> Issue:
        return self._target("issue", number)

    def comment(self, on: str, number: int, body: str) -> None:
        self._maybe_fail("comment")
        self.calls.append(("comment", on, number))
        self._target(on, number).comments.append(Comment(self._operator, body, _stamp()))

    def comments(self, on: str, number: int) -> list[Comment]:
        return list(self._target(on, number).comments)

    def set_labels(self, issue: int, add: list[str], remove: list[str]) -> None:
        self._maybe_fail("set_labels")
        self.calls.append(("set_labels", issue, tuple(add), tuple(remove)))
        i = self._target("issue", issue)
        i.labels = [lb for lb in i.labels if lb not in remove] + [lb for lb in add if lb not in i.labels]

    def find_prs(self, head: str) -> list[PullRequest]:
        return [p for p in self.prs.values() if p.head == head and p.state == "OPEN"]

    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool) -> PullRequest:
        self._maybe_fail("create_pr")
        self.calls.append(("create_pr", head))
        n = self._number()
        pr = PullRequest(n, f"https://forge.test/pull/{n}", head, base, title, body, draft=draft)
        self.prs[n] = pr
        return pr

    def pr(self, number: int) -> PullRequest:
        return self._target("pr", number)

    def mark_ready(self, number: int) -> None:
        self.calls.append(("mark_ready", number))
        self._target("pr", number).draft = False

    def close_pr(self, number: int) -> None:
        self.calls.append(("close_pr", number))
        pr = self._target("pr", number)
        if pr.state == "OPEN":
            pr.state = "CLOSED"

    def merge_pr(self, number: int, method: str) -> None:
        self._maybe_fail("merge_pr")
        self.calls.append(("merge_pr", number, method))
        pr = self._target("pr", number)
        if pr.state != "OPEN":
            raise ForgeError(f"PR #{number} is {pr.state}")
        pr.state = "MERGED"

    def labels(self) -> list[str]:
        return list(self.repo_labels)

    def create_label(self, name: str, color: str, description: str) -> None:
        self.calls.append(("create_label", name))
        self.repo_labels[name] = (color, description)


# ---- GitHub through the gh CLI -------------------------------------------------------


Runner = Callable[[list[str]], str]


def gh_runner(cwd: Path | None = None) -> Runner:
    def run(args: list[str]) -> str:
        res = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
        if res.returncode != 0:
            raise ForgeError(f"`gh {' '.join(args)}` failed: {(res.stderr or res.stdout).strip()}")
        return res.stdout
    return run


def _comments(raw: list[dict]) -> list[Comment]:
    return [Comment((c.get("author") or {}).get("login", ""), c.get("body", ""), c.get("createdAt", "")) for c in raw]


class GhForge:
    """GitHub through `gh`, run in the repository's directory so `gh` picks the repo."""

    ISSUE_FIELDS = "number,title,body,author,url,state,labels,comments"
    PR_FIELDS = "number,url,headRefName,baseRefName,title,body,state,isDraft,comments"

    def __init__(self, cwd: Path | None = None, run: Runner | None = None):
        self._run = run or gh_runner(cwd)
        self._operator: str | None = None

    def _json(self, *args: str):
        return json.loads(self._run(list(args)))

    def operator(self) -> str:
        if self._operator is None:
            self._operator = self._run(["api", "user", "--jq", ".login"]).strip()
        return self._operator

    def _issue(self, d: dict) -> Issue:
        return Issue(d["number"], d["title"], d.get("body") or "", (d.get("author") or {}).get("login", ""),
                     d["url"], d.get("state", "OPEN"), [lb["name"] for lb in d.get("labels", [])],
                     _comments(d.get("comments", [])))

    def _pr(self, d: dict) -> PullRequest:
        return PullRequest(d["number"], d["url"], d["headRefName"], d["baseRefName"], d.get("title", ""),
                           d.get("body") or "", d["state"], d.get("isDraft", False), _comments(d.get("comments", [])))

    def list_issues(self, label: str) -> list[Issue]:
        rows = self._json("issue", "list", "--label", label, "--state", "open", "--limit", "500",
                          "--json", "number,title,body,author,url,state,labels")
        return [self._issue(r) for r in rows]

    def issue(self, number: int) -> Issue:
        return self._issue(self._json("issue", "view", str(number), "--json", self.ISSUE_FIELDS))

    def comment(self, on: str, number: int, body: str) -> None:
        self._run([on, "comment", str(number), "--body", body])

    def comments(self, on: str, number: int) -> list[Comment]:
        return _comments(self._json(on, "view", str(number), "--json", "comments")["comments"])

    def set_labels(self, issue: int, add: list[str], remove: list[str]) -> None:
        current = set(self.issue(issue).labels)
        add = [lb for lb in add if lb not in current]
        remove = [lb for lb in remove if lb in current]
        if not add and not remove:
            return
        args = ["issue", "edit", str(issue)]
        if add:
            args += ["--add-label", ",".join(add)]
        if remove:
            args += ["--remove-label", ",".join(remove)]
        self._run(args)

    def find_prs(self, head: str) -> list[PullRequest]:
        rows = self._json("pr", "list", "--head", head, "--state", "open", "--json", self.PR_FIELDS)
        return [self._pr(r) for r in rows]

    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool) -> PullRequest:
        args = ["pr", "create", "--head", head, "--base", base, "--title", title, "--body", body]
        self._run(args + (["--draft"] if draft else []))
        prs = self.find_prs(head)
        if len(prs) != 1:
            raise ForgeError(f"expected one open PR from {head} after creating it, found {len(prs)}")
        return prs[0]

    def pr(self, number: int) -> PullRequest:
        return self._pr(self._json("pr", "view", str(number), "--json", self.PR_FIELDS))

    def mark_ready(self, number: int) -> None:
        if self.pr(number).draft:
            self._run(["pr", "ready", str(number)])

    def close_pr(self, number: int) -> None:
        if self.pr(number).state == "OPEN":
            self._run(["pr", "close", str(number)])

    def merge_pr(self, number: int, method: str) -> None:
        self._run(["pr", "merge", str(number), f"--{method}"])

    def labels(self) -> list[str]:
        return [r["name"] for r in self._json("label", "list", "--limit", "500", "--json", "name")]

    def create_label(self, name: str, color: str, description: str) -> None:
        self._run(["label", "create", name, "--color", color, "--description", description, "--force"])
