"""Command-line entry point: `puxirum <command>`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable

from puxirum import __version__, bootstrap, config, report
from puxirum.claude import ClaudeRunner
from puxirum.engine import Engine
from puxirum.forge import Forge, GhForge
from puxirum.machine import Refused
from puxirum.prompts import PromptError, Prompts
from puxirum.store import Store, StoreError
from puxirum.world import World


def repo_root(start: Path) -> Path:
    res = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit("puxirum: not inside a git repository")
    return Path(res.stdout.strip())


def default_engine(cwd: Path) -> Engine:
    repo = repo_root(cwd)
    cfg = config.load(repo)
    world = World(repo, cfg, Store(repo), GhForge(cwd=repo))
    runner = ClaudeRunner(prompt_for=Prompts(cfg, repo), command=cfg.agent_command,
                          timeout_s=cfg.agent_timeout_s, budget_usd=cfg.budgets)
    return Engine(world, runner, log=lambda msg: print(msg, file=sys.stderr))


def _text(arg: str | None) -> str:
    return arg if arg is not None else sys.stdin.read()


def _status(engine: Engine, out) -> None:
    rows = engine.plan()
    jobs = {j.issue: j for j in engine.store.all()}
    if not rows:
        print("Nothing in the queue.", file=out)
        return
    table = [("ACTION", "ISSUE", "JOB", "STAGE", "ROUND", "PR", "COST", "NOTE")]
    for r in rows:
        j = jobs.get(r.issue)
        table.append((r.action, f"#{r.issue}", r.job_id or "-", r.stage or "-", str(r.round or "-"),
                      f"#{r.pr}" if r.pr else "-", f"${j.cost_usd:.2f}" if j else "-", r.note))
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]) - 1)]
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)) + "  " + row[-1], file=out)


def main(argv: list[str] | None = None, make_engine: Callable[[Path], Engine] = default_engine,
         make_forge: Callable[[Path], Forge] = lambda repo: GhForge(cwd=repo),
         cwd: Path | None = None, out=None) -> int:
    out = out or sys.stdout
    cwd = cwd or Path.cwd()
    parser = argparse.ArgumentParser(prog="puxirum", description="A deterministic software factory.")
    parser.add_argument("--version", action="version", version=f"puxirum {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="install Puxirum in this repository (never overwrites a file)")
    p_init.add_argument("--no-labels", action="store_true", help="don't create the GitHub labels")
    sub.add_parser("doctor", help="check everything a run needs")
    p_run = sub.add_parser("run", help="work the queue until every job waits or finishes")
    p_run.add_argument("issue", nargs="?", type=int, help="only this issue")
    sub.add_parser("status", help="what each issue and job is doing")
    p_rep = sub.add_parser("report", help="costs and times by job, role, model and run")
    p_rep.add_argument("--json", action="store_true", help="machine-readable output")
    p_fb = sub.add_parser("feedback", help="send an escalated job back to work with your feedback")
    p_fb.add_argument("job", help="job id or issue number")
    p_fb.add_argument("-m", "--message", help="the feedback (default: read stdin)")
    p_rj = sub.add_parser("reject", help="reject a job that waits for you or for the author")
    p_rj.add_argument("job", help="job id or issue number")
    p_rj.add_argument("-m", "--message", help="the reason (default: read stdin)")
    args = parser.parse_args(argv)

    try:
        if args.command in ("init", "doctor"):
            repo = repo_root(cwd)
            if args.command == "init":
                forge = None if args.no_labels else make_forge(repo)
                bootstrap.init(repo, forge, lambda line: print(line, file=out))
                return 0
            results = bootstrap.doctor(repo, make_forge(repo))
            for c in results:
                print(f"{c.level.upper():4}  {c.what}" + (f": {c.detail}" if c.detail else ""), file=out)
            return 1 if any(c.level == "fail" for c in results) else 0
        engine = make_engine(cwd)
        if args.command == "run":
            summary = engine.run(only=args.issue)
            _status(engine, out)
            print(f"\nThis run: {summary['agents']} agent runs, ${summary['cost_usd']:.2f}, "
                  f"{report.duration(summary['wall_seconds'])}", file=out)
        elif args.command == "status":
            _status(engine, out)
        elif args.command == "report":
            text = report.as_json(engine.store) if args.json else report.render(engine.store, engine.cfg)
            print(text, end="", file=out)
        elif args.command == "feedback":
            job = engine.feedback(args.job, _text(args.message))
            print(f"{job.id}: feedback recorded; now {job.stage}", file=out)
        elif args.command == "reject":
            job = engine.reject(args.job, _text(args.message))
            print(f"{job.id}: rejected", file=out)
    except (config.ConfigError, PromptError, Refused, StoreError, ValueError) as e:
        print(f"puxirum: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
