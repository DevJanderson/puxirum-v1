"""The Claude Code runner: one fresh `claude -p` process per agent task.

Each role runs with the least it needs:

- only the built-in tools the role uses (`--tools`); the intake gets no shell;
- `--permission-mode dontAsk` with explicit allow rules, so anything not
  allowed is denied instead of waiting for a person. Writes are allowed only to
  the role's own output (and, for the builder, the worktree);
- no user or project settings, hooks or MCP servers (`--setting-sources ""`,
  `--strict-mcp-config`), so a person's setup can't change an agent's behaviour;
- no forge credentials in its environment: no SSH agent, no credential
  helpers, an empty `gh` config. Even a command that slips past the rules
  can't push, open PRs or merge; only the core talks to GitHub.

The prompt goes in on stdin. The agent streams one JSON event per line
(`--output-format stream-json`) into the job's `logs/`, so its progress can be
followed while it works (`puxirum feed`). The last event is the result, and its
`total_cost_usd` is the cost of the run.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from puxirum.runner import AgentResult, AgentTask

KILL_GRACE_S = 5
STRIPPED_ENV = ("SSH_AUTH_SOCK", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GIT_ASKPASS", "SSH_ASKPASS")
STRIPPED_PREFIXES = ("TUIOS_",)

READ_ONLY_GIT = ("git log:*", "git diff:*", "git show:*", "git status:*", "git branch:*", "git rev-parse:*")
BUILDER_DENY = (
    "git push:*",
    "git remote:*",
    "git config:*",
    "gh:*",
    "git reset --hard origin:*",
    "git rebase:*",
    "git commit --amend:*",
)


@dataclass(frozen=True)
class Policy:
    tools: tuple[str, ...]
    bash_allow: tuple[str, ...] = ()
    bash_deny: tuple[str, ...] = ()
    edits_worktree: bool = False


POLICIES: dict[str, Policy] = {
    "intake": Policy(tools=("Read", "Grep", "Glob", "Write")),
    "spec": Policy(tools=("Read", "Grep", "Glob", "Write", "Bash"), bash_allow=READ_ONLY_GIT + ("ls:*",)),
    "builder": Policy(
        tools=("Read", "Grep", "Glob", "Edit", "Write", "Bash"),
        bash_allow=("*",),
        bash_deny=BUILDER_DENY,
        edits_worktree=True,
    ),
    "reviewer": Policy(
        tools=("Read", "Grep", "Glob", "Write", "Bash"),
        bash_allow=READ_ONLY_GIT
        + ("ls:*", "agent-browser:*", "curl -s http://127.0.0.1:*", "curl -s http://localhost:*"),
    ),
    "approver": Policy(tools=("Read", "Grep", "Glob", "Write", "Bash"), bash_allow=READ_ONLY_GIT),
}


def _abs_rule(tool: str, path: Path, tree: bool = False) -> str:
    """A permission rule for an absolute path (Claude Code writes those with a leading `//`)."""
    p = "/" + str(path.resolve())
    return f"{tool}({p}/**)" if tree else f"{tool}({p})"


def settings_for(task: AgentTask, policy: Policy, extra_allow: tuple[str, ...] = ()) -> dict:
    allow = [
        _abs_rule("Read", task.cwd, tree=True),
        _abs_rule("Read", task.job_dir, tree=True),
        _abs_rule("Edit", task.output),
    ]
    if policy.edits_worktree:
        allow.append(_abs_rule("Edit", task.cwd, tree=True))
    for extra in task.vars.get("writable", ()) or ():
        allow.append(_abs_rule("Edit", Path(extra), tree=True))
    if "Grep" in policy.tools:
        allow.append("Grep")
    if "Glob" in policy.tools:
        allow.append("Glob")
    if "Bash" in policy.tools:
        allow += ["Bash" if b == "*" else f"Bash({b})" for b in policy.bash_allow]
    allow += list(extra_allow)
    deny = [f"Bash({b})" for b in policy.bash_deny]
    deny += [f"Read({p}/**)" for p in SECRET_PATHS]
    settings: dict = {"permissions": {"allow": allow, "deny": deny, "defaultMode": "dontAsk"}}
    if task.role == "builder" and task.vars.get("sandbox"):
        settings["sandbox"] = sandbox_for(task)
    if task.role == "builder" and task.vars.get("checks"):
        # Before the builder finishes, run the checks once and hand any failure back to it.
        command = f"{shlex.quote(sys.executable)} -m puxirum.hook stop-checks"
        timeout = int(task.vars.get("checks_timeout_s") or 1800)
        settings["hooks"] = {"Stop": [{"hooks": [{"type": "command", "command": command, "timeout": timeout}]}]}
    return settings


SECRET_PATHS = ("~/.ssh", "~/.gnupg", "~/.config/gh", "~/.git-credentials", "~/.netrc", "~/.aws", "~/.docker")


def sandbox_for(task: AgentTask) -> dict:
    """The OS-level sandbox for the builder's shell (bubblewrap on Linux).

    Rules on Bash commands can be talked around (`env -u ... git push`); the
    sandbox can't. The shell can't read secrets, can only reach the hosts in
    `network`, and can't run outside the sandbox. It may write the worktree and,
    for `git commit`, only the parts of the main checkout's `.git` a commit on
    this job's branch needs: never `.git/hooks` or `.git/config`, which the core's
    own git would otherwise run or obey outside the sandbox.
    """
    git_dir = Path(task.vars["main_checkout"]) / ".git"
    branch = str(task.vars["branch"])
    writes = [
        str(task.cwd),
        str(git_dir / "objects"),
        str(git_dir / "worktrees" / Path(task.cwd).name),
        str(git_dir / "logs"),
        str((git_dir / "refs" / "heads" / branch).parent),
    ]
    writes += [str(Path(p)) for p in task.vars.get("sandbox_writes") or ()]
    return {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "autoAllowBashIfSandboxed": True,
        "filesystem": {"denyRead": list(SECRET_PATHS), "allowWrite": writes},
        "network": {"allowedDomains": list(task.vars.get("network") or ())},
    }


def agent_env(task: AgentTask, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in (base if base is not None else os.environ).items()
        if k not in STRIPPED_ENV and not k.startswith(STRIPPED_PREFIXES)
    }
    gh_dir = task.job_dir / ".gh-empty"
    gh_dir.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "GIT_SSH_COMMAND": "false",
            "GIT_TERMINAL_PROMPT": "0",
            # No stored credentials, and no signing: an agent's commits are its own, never signed
            # with the person's key (which the sandbox hides anyway). The merge on the forge makes
            # the commit that lands on the base branch.
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "commit.gpgsign",
            "GIT_CONFIG_VALUE_1": "false",
            "GIT_CONFIG_KEY_2": "tag.gpgsign",
            "GIT_CONFIG_VALUE_2": "false",
            "GH_CONFIG_DIR": str(gh_dir),
            "GH_PROMPT_DISABLED": "1",
            "PUXIRUM_JOB": task.job_id,
            "PUXIRUM_ROLE": task.name,
        }
    )
    if task.vars.get("port") is not None:
        env["PUXIRUM_PORT"] = str(task.vars["port"])
    if task.role == "builder" and task.vars.get("checks"):
        package_root = str(Path(__file__).resolve().parents[1])
        env.update(
            {
                "PUXIRUM_WORKTREE": str(task.cwd),
                "PUXIRUM_CHECKS": str(task.vars["checks"]),
                "PUXIRUM_CHECKS_TIMEOUT": str(task.vars.get("checks_timeout_s") or 1800),
                "PYTHONPATH": os.pathsep.join(p for p in (package_root, env.get("PYTHONPATH")) if p),
            }
        )
    return env


@dataclass
class ClaudeRunner:
    """Runs a task as `claude -p`. `prompt_for` renders the role's prompt."""

    prompt_for: Callable[[AgentTask], str]
    command: tuple[str, ...] = ("claude",)
    timeout_s: float = 3600
    budget_usd: dict[str, float] = field(default_factory=dict)  # role -> cap for one run

    def argv(self, task: AgentTask) -> list[str]:
        policy = POLICIES[task.role]
        args = [
            *self.command,
            "-p",
            "--model",
            task.model,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
            "--tools",
            ",".join(policy.tools),
            "--settings",
            json.dumps(settings_for(task, policy)),
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if task.role in self.budget_usd:
            args += ["--max-budget-usd", f"{self.budget_usd[task.role]:.2f}"]
        return args

    def run(self, task: AgentTask) -> AgentResult:
        logs = task.job_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stem = f"{task.name.replace(':', '-')}-r{task.vars.get('round', 0)}-a{task.vars.get('attempt', 1)}"
        out_path, err_path = logs / f"{stem}.jsonl", logs / f"{stem}.err"
        prompt = self.prompt_for(task)
        (logs / f"{stem}.prompt.md").write_text(prompt, encoding="utf-8")
        start = time.monotonic()
        with open(out_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
            proc = subprocess.Popen(
                self.argv(task),
                cwd=task.cwd,
                env=agent_env(task),
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                text=True,
                start_new_session=True,
            )
            assert proc.stdin is not None  # stdin=PIPE
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except BrokenPipeError:
                pass
            try:
                code = proc.wait(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                err.write(f"\npuxirum: stopped after the {self.timeout_s:.0f}s timeout\n")
                code = 124
            else:
                _kill_group(proc, grace=0)  # nothing the agent started (a dev server, a watcher) outlives it
        seconds = time.monotonic() - start
        result = final_result(out_path)
        cost = result.get("total_cost_usd") if isinstance(result.get("total_cost_usd"), (int, float)) else None
        if code == 0 and (not result or result.get("is_error")):
            code = 1  # claude exited 0 but reported an error, or printed no result
        return AgentResult(exit_code=code, seconds=seconds, cost_usd=cost, log=out_path)


def events(path: Path) -> list[dict]:
    """The stream's events, skipping lines that aren't JSON objects (a cut-off last line, stray output)."""
    out: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            out.append(event)
    return out


def final_result(path: Path) -> dict:
    """The run's `result` event, or {} when the agent never got that far."""
    return next((e for e in reversed(events(path)) if e.get("type") == "result"), {})


def _kill_group(proc: subprocess.Popen, grace: float = KILL_GRACE_S) -> None:
    for sig, wait in ((signal.SIGTERM, grace or 0.1), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
