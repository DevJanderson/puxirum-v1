"""Role prompts: templates plus the values of one task.

Templates are Markdown with `{{name}}` placeholders. Every placeholder must get a
value and every value is plain text: there is no logic in templates. Anything
conditional (a retry note, the previous round's files) is worked out here and
handed over as text, possibly empty. A placeholder without a value is an error,
never an empty string.

The defaults ship in `puxirum/roles/`. A project can replace any of them with a
file of the same name in `.puxirum/roles/` (a protected path, so a job's branch
can't change the prompts that judge it).
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from puxirum import files
from puxirum.claude import POLICIES
from puxirum.config import Config
from puxirum.files import MalformedFile
from puxirum.runner import AgentTask

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
LENS_TITLES = {"code": "code", "ux": "user experience", "ui": "visual design", "security": "security"}
ROLE_TITLES = {"intake": "intake", "spec": "specification", "builder": "builder", "approver": "approver"}


class PromptError(Exception):
    pass


def template(repo: Path, name: str) -> str:
    """The project's override in .puxirum/roles/<name>.md, or the default."""
    override = repo / ".puxirum" / "roles" / f"{name}.md"
    if override.is_file():
        return override.read_text(encoding="utf-8")
    resource = resources.files("puxirum").joinpath("roles", f"{name}.md")
    if not resource.is_file():
        raise PromptError(f"no template {name}.md")
    return resource.read_text(encoding="utf-8")


def render(text: str, values: dict[str, object], where: str = "template") -> str:
    missing = sorted({m.group(1) for m in PLACEHOLDER.finditer(text)} - set(values))
    if missing:
        raise PromptError(f"{where}: no value for {', '.join('{{' + m + '}}' for m in missing)}")
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


class Prompts:
    def __init__(self, cfg: Config, repo: Path):
        self.cfg = cfg
        self.repo = repo

    def __call__(self, task: AgentTask) -> str:
        values = self.values(task)
        name = task.role
        if task.role == "reviewer":
            values["lens_guide"] = render(template(self.repo, f"lenses/{task.lens}"), values, f"lenses/{task.lens}.md")
        body = render(template(self.repo, name), values, f"{name}.md")
        common = render(template(self.repo, "_common"), values, "_common.md")
        return f"{common.rstrip()}\n\n{body.strip()}\n"

    # ---- values --------------------------------------------------------------------------

    def values(self, task: AgentTask) -> dict[str, object]:
        v = task.vars
        d = task.job_dir
        rnd = int(v.get("round") or 0)
        round_dir = d / f"round-{rnd}"
        base = self.cfg.base_branch
        surfaces = v.get("surfaces") or []
        out: dict[str, object] = {
            "job_id": task.job_id,
            "issue": v["issue"],
            "branch": v["branch"],
            "round": rnd,
            "output": task.output,
            "worktree": v["worktree"],
            "main_checkout": v["main_checkout"],
            "base": base,
            "base_ref": f"origin/{base}",
            "job_dir": d,
            "issue_md": d / "issue.md",
            "intake_md": d / "intake.md",
            "spec_md": d / "spec.md",
            "build_md": d / "build.md",
            "round_dir": round_dir,
            "evidence_dir": round_dir / "evidence",
            "checks": Path(v["main_checkout"]) / self.cfg.checks,
            "protected": ", ".join(f"`{p}`" for p in self.cfg.protected) or "none",
            "risk": v.get("risk") or "unknown",
            "job_surfaces": ", ".join(surfaces) or "none",
            "surface_options": ", ".join(f"`{s}`" for s in self.cfg.surface_reviewers) or "none",
            "role_title": ROLE_TITLES.get(task.role) or f"{LENS_TITLES.get(task.lens or '', task.lens)} reviewer",
            "lens_title": LENS_TITLES.get(task.lens or "", task.lens or ""),
            "write_scope": self._write_scope(task),
            "shell_note": self._shell_note(task),
            "retry_note": self._retry_note(v.get("retry")),
            "previous_intakes": self._previous_intakes(d),
            "edge_cases_rule": self._edge_cases_rule(surfaces),
            "round_inputs": self._round_inputs(d, rnd, v.get("feedback")),
            "previous_review": self._previous_review(d, rnd, task.lens),
            "app_note": self._app_note(task),
        }
        return out

    def _write_scope(self, task: AgentTask) -> str:
        if task.role == "builder":
            return "You also change code inside the worktree. Nothing outside the worktree, apart from that file."
        if task.role == "reviewer":
            evidence = task.job_dir / f"round-{task.vars.get('round')}" / "evidence"
            return f"You may also save screenshots in `{evidence}`."
        return "Nothing else."

    @staticmethod
    def _shell_note(task: AgentTask) -> str:
        """For a role whose shell only runs listed commands: say which, and how to call them."""
        policy = POLICIES[task.role]
        if "Bash" not in policy.tools:
            return "- You have no shell. Read files with the Read, Grep and Glob tools."
        if "*" in policy.bash_allow:
            return ""
        allowed = ", ".join(f"`{b.removesuffix(':*').removesuffix('*')}`" for b in policy.bash_allow if b != "cd:*")
        return (
            f"- Your shell runs only these commands: {allowed}. Anything else is refused. Run one command per "
            "call, optionally after `cd <dir> && `: no shell variables, no `;`, and no pipes into other "
            "programs. Read files with the Read, Grep and Glob tools, never with `cat`, `sed` or `head`."
        )

    @staticmethod
    def _retry_note(retry: str | None) -> str:
        if not retry:
            return ""
        quoted = "\n".join(f"> {line}" for line in str(retry).splitlines())
        return (
            "\n## Your previous attempt was rejected\n\n"
            f"The coordinator rejected your last attempt at this task:\n\n{quoted}\n\n"
            "Fix that in this attempt. The rest of this task is unchanged.\n"
        )

    @staticmethod
    def _previous_intakes(d: Path) -> str:
        earlier = sorted(d.glob("intake-*.md"))
        if not earlier:
            return ""
        paths = ", ".join(f"`{p}`" for p in earlier)
        return (
            f"3. Earlier intake decisions for this issue: {paths}. The author or the operator has replied "
            "since; decide again with the new information."
        )

    @staticmethod
    def _edge_cases_rule(surfaces: list[str]) -> str:
        if "ui" in surfaces:
            return (
                'This change has a user interface, so `## Edge cases` is required and can\'t say "None.": '
                "list each case the builder must handle and the reviewers must try, such as no items, many "
                "items, very long text, keyboard-only use, a 375px-wide screen and every theme the app has."
            )
        return "Write `None.` under `## Edge cases` when the change has no user-facing behaviour."

    @staticmethod
    def _round_inputs(d: Path, rnd: int, feedback: str | None) -> str:
        items: list[str] = []
        prev = d / f"round-{rnd - 1}"
        if rnd > 1 and prev.is_dir():
            items.append(f"`{d / 'build.md'}`: your file from the earlier rounds. Its `## Log` is the history.")
            gate_failed = False
            try:
                gate_failed = files.read(prev / "checks.md", "checks").header["GATE"] == "FAIL"
            except (FileNotFoundError, MalformedFile):
                pass
            if gate_failed:
                items.append(
                    f"`{prev / 'checks.md'}` and `{prev / 'checks.log'}`: the checks failed on your "
                    "last round. Fix that first."
                )
            else:
                for review in sorted(prev.glob("review-*.md")):
                    try:
                        if files.read(review, "review").header["VERDICT"] == "CHANGES":
                            items.append(f"`{review}`: asks for changes. Address every finding.")
                    except MalformedFile:
                        continue
        if feedback:
            k = Path(feedback).stem.split("-", 1)[1]
            escalation = d / f"escalation-{k}.md"
            items.append(
                f"`{feedback}`: a person's decision after the job escalated (see `{escalation}`). "
                "Where it disagrees with the spec or a review, the person wins."
            )
        return "\n".join(f"{i}. {text}" for i, text in enumerate(items, start=3))

    @staticmethod
    def _previous_review(d: Path, rnd: int, lens: str | None) -> str:
        if not lens:
            return ""
        for n in range(rnd - 1, 0, -1):
            path = d / f"round-{n}" / f"review-{lens}.md"
            if path.is_file():
                return (
                    f"5. `{path}`: your own review of round {n}. Check each of its findings: say which are "
                    "fixed, and keep the ones that aren't."
                )
        return ""

    @staticmethod
    def _app_note(task: AgentTask) -> str:
        url = task.vars.get("app_url")
        session = f"{task.job_id}-{task.lens or task.role}"
        if url:
            return (
                f"The coordinator is running the app for this job at {url}. Look at it with the `agent-browser` "
                f"CLI (run `agent-browser skills get core` first), writing `--session {session}` out in full "
                f"on every call, and run `agent-browser --session {session} close` when you're done. "
                "Don't start another server, and don't sign in or submit real data."
            )
        return (
            "No app is running for this job. If a criterion can only be seen on a page, say in your file that "
            "you couldn't see it; don't claim you did."
        )
