"""`puxirum init` and `puxirum doctor`.

`init` installs Puxirum in a repository without ever overwriting a file: it only
creates what is missing. `doctor` checks everything a run needs and says what
to fix.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from puxirum import config
from puxirum.config import Config
from puxirum.forge import Forge

CONFIG_TEMPLATE = """\
# Puxirum configuration. Every key is optional; the values shown are the defaults.

[queue]
# label = "puxirum"                         # issues with this label are the queue
# needs_info_label = "puxirum:needs-info"
# needs_human_label = "puxirum:needs-human"
# concurrency = 1                           # jobs worked on at the same time
# max_rounds = 3                            # build → gate → review rounds before a person decides
# agent_attempts = 2                        # runs of one agent before the job escalates
# effect_attempts = 3                       # failures of one GitHub/git action before the job escalates

[git]
# base = "main"
# merge_method = "squash"                   # merge | squash | rebase
# branch_prefix = "puxirum/"
# worktrees_dir = ".worktrees"

[gate]
# checks = ".puxirum/checks.sh"             # run from the main checkout inside each job's worktree
# timeout_s = 1800
# protected = [".puxirum/checks.sh", ".puxirum/config.toml", ".puxirum/roles/*"]

[ports]
# base = 5200                               # each job gets base + (n - 1) % 100 * step
# step = 10

[models]
# intake = "sonnet"
# spec = "sonnet"
# builder = "sonnet"
# approver = "sonnet"

[app]
# The core starts the dev server for the builder (on UI changes) and the UX/UI reviewers.
# setup = ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"]
# command = ["npm", "run", "dev", "--", "--port", "{port}", "--strictPort"]
# ready_timeout_s = 60

[report]
# A reference to compare against in `puxirum report`, such as an earlier factory's run.
# baseline_label = "previous factory"
# baseline_usd = 8.53
# baseline_minutes = 78

[agents]
# command = ["claude"]
# timeout_s = 3600                          # per agent run
# sandbox = true                            # the builder's shell runs in Claude Code's OS sandbox
# network = ["registry.npmjs.org"]          # hosts the builder's shell may reach (default: none)
# sandbox_writes = ["~/.npm"]               # extra paths it may write, such as a package cache
# [agents.budget_usd]                       # cap for one run of each role
# intake = 0.5
# spec = 1.0
# builder = 4.0
# reviewer = 1.5
# approver = 1.0

# Reviewers by risk, plus extra reviewers by surface. Uncomment to replace the defaults.
# [routing.risk]
# low = { code = "haiku" }
# medium = { code = "sonnet" }
# high = { code = "sonnet" }
# [routing.surfaces]
# ui = { ux = "sonnet", ui = "haiku" }
# security = { security = "opus" }
"""

CHECKS_TEMPLATE = """\
#!/usr/bin/env bash
# Puxirum's gate runs this script from the main checkout, inside each job's worktree,
# after every build and again before merging. Exit 0 only when the branch is good:
# install dependencies, then lint, typecheck, test and build.
set -euo pipefail

echo "Edit .puxirum/checks.sh: add this project's checks." >&2
exit 1
"""

IGNORES = (".puxirum/state/", ".worktrees/")

LABELS = {  # name attribute -> (color, description)
    "queue_label": ("1d76db", "Puxirum: work this issue"),
    "needs_info_label": ("fbca04", "Puxirum: waiting for the author"),
    "needs_human_label": ("d93f0b", "Puxirum: waiting for a person's decision"),
}


def init(repo: Path, forge: Forge | None, out: Callable[[str], None]) -> None:
    d = repo / ".puxirum"
    d.mkdir(exist_ok=True)
    (d / "roles").mkdir(exist_ok=True)
    _create(repo, ".puxirum/config.toml", CONFIG_TEMPLATE, out)
    if _create(repo, ".puxirum/checks.sh", CHECKS_TEMPLATE, out):
        (d / "checks.sh").chmod(0o755)

    gitignore = repo / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = text.splitlines()
    missing = [p for p in IGNORES if p not in lines]
    if missing:
        sep = "" if not text or text.endswith("\n") else "\n"
        gitignore.write_text(text + sep + "\n".join(missing) + "\n", encoding="utf-8")
        out(f"added to .gitignore: {', '.join(missing)}")

    cfg = config.load(repo)
    if forge is not None:
        existing = set(forge.labels())
        for attr, (color, description) in LABELS.items():
            name = getattr(cfg, attr)
            if name not in existing:
                forge.create_label(name, color, description)
                out(f"created label {name}")
    out("next: edit .puxirum/checks.sh, commit .puxirum/ and .gitignore, then run `puxirum doctor`")


def _create(repo: Path, rel: str, text: str, out: Callable[[str], None]) -> bool:
    path = repo / rel
    if path.exists():
        out(f"kept {rel} (already exists)")
        return False
    path.write_text(text, encoding="utf-8")
    out(f"created {rel}")
    return True


# ---- doctor ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    level: str  # ok | warn | fail
    what: str
    detail: str = ""


def doctor(repo: Path, forge: Forge, which: Callable[[str], str | None] = shutil.which) -> list[Check]:
    checks: list[Check] = []

    def add(level: str, what: str, detail: str = "") -> None:
        checks.append(Check(level, what, detail))

    if sys.version_info >= (3, 11):
        add("ok", f"python {sys.version.split()[0]}")
    else:
        add("fail", "python 3.11 or newer", sys.version.split()[0])

    try:
        cfg: Config | None = config.load(repo)
        add("ok", ".puxirum/config.toml is valid")
    except config.ConfigError as e:
        cfg = None
        add("fail", ".puxirum/config.toml", str(e))

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)

    if git("remote", "get-url", "origin").returncode == 0:
        add("ok", "git remote origin")
    else:
        add("fail", "git remote origin", "add the GitHub repository as `origin`")

    if cfg is not None:
        checks_path = repo / cfg.checks
        if not checks_path.is_file():
            add("fail", cfg.checks, "missing; run `puxirum init`")
        elif checks_path.read_text(encoding="utf-8") == CHECKS_TEMPLATE:
            add("fail", cfg.checks, "still the template; add this project's checks")
        else:
            add("ok", f"{cfg.checks} exists")
        if git("ls-remote", "--exit-code", "--heads", "origin", cfg.base_branch).returncode == 0:
            add("ok", f"origin/{cfg.base_branch} exists")
        else:
            add("fail", f"origin/{cfg.base_branch}", "the base branch isn't on origin")
        for rel in (".puxirum/state/x", f"{cfg.worktrees_dir}/x"):
            if git("check-ignore", "-q", rel).returncode == 0:
                add("ok", f"{rel.rsplit('/', 1)[0]}/ is ignored by git")
            else:
                add("fail", f"{rel.rsplit('/', 1)[0]}/ is ignored by git", "add it to .gitignore")
        tracked = git("ls-files", "--error-unmatch", cfg.checks).returncode == 0
        add("ok" if tracked else "warn", f"{cfg.checks} is committed",
            "" if tracked else "commit it so every worktree's gate uses the same checks")

    if which("gh") is None:
        add("fail", "gh CLI", "install it: https://cli.github.com")
    else:
        try:
            add("ok", f"gh is signed in as {forge.operator()}")
            if cfg is not None:
                names = set(forge.labels())
                for attr in LABELS:
                    name = getattr(cfg, attr)
                    add("ok" if name in names else "fail", f"label {name}",
                        "" if name in names else "run `puxirum init`")
        except Exception as e:  # noqa: BLE001 - any gh failure is a doctor finding
            add("fail", "gh can reach GitHub", str(e).splitlines()[0] if str(e) else type(e).__name__)

    for tool, phase in (("claude", "Phase 2 runner"), ("tuios", "Phase 3 workbench")):
        if which(tool):
            add("ok", f"{tool} found")
        else:
            add("warn", f"{tool} not found", f"needed by the {phase}")
    if cfg is not None and cfg.sandbox:
        missing = [tool for tool in ("bwrap", "socat") if which(tool) is None]
        add("fail" if missing else "ok", "builder sandbox",
            f"install {' and '.join(missing)} (pacman -S bubblewrap socat), or set [agents] sandbox = false"
            if missing else "bwrap and socat found")
    return checks
