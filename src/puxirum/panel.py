"""The web panel's server: `puxirum panel`.

A read-only view of one or more repositories that use Puxirum, for a browser.
It serves the panel's built pages and a small JSON API:

    GET /api/projects                         the repositories it found
    GET /api/projects/<p>/state               everything the Início tab draws
    GET /api/projects/<p>/events              Server-Sent Events: `state` when it changes,
                                              `feed` for each step of a running agent
    GET /api/projects/<p>/jobs/<job>/files/<path>   one of a job's own files, as text

Like the tuios workbench, it only reads the files the core writes; it never
changes a job and needs no credentials, which is what lets it run in a container
with the repositories mounted read-only. It listens on 127.0.0.1 unless told
otherwise.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from puxirum import config, report
from puxirum.feed import STEM, Feed, describe
from puxirum.files import parse_header
from puxirum.machine import ACTIVE, WAITING
from puxirum.store import Job, Store

DEFAULT_PORT = 4410
TICK_S = 1.0
HEARTBEAT_S = 15.0
BACKLOG_STREAMS = 8  # a page that connects sees the steps of the latest agents that already finished...
BACKLOG_STEPS = 60  # ...up to this many steps
MAX_FILE = 256 * 1024
READABLE = {".md", ".json", ".log", ".txt"}

# The line: the stages a job goes through, in order. `kind` is who works there.
LINE: list[dict[str, Any]] = [
    {"id": "intake", "name": "Intake", "kind": "agent", "files": "intake.md", "stages": ["intake", "needs-info"]},
    {"id": "spec", "name": "Spec", "kind": "agent", "files": "spec.md", "stages": ["spec"]},
    {"id": "build", "name": "Build", "kind": "agent", "files": "build.md · commits", "stages": ["build"]},
    {"id": "gate", "name": "Gate", "kind": "core", "files": "checks.sh", "stages": ["gate"]},
    {"id": "review", "name": "Revisão", "kind": "agent", "files": "review-<lente>.md", "stages": ["review"]},
    {"id": "approve", "name": "Aprovação", "kind": "agent", "files": "decision.md", "stages": ["approve"]},
    {"id": "merge", "name": "Merge", "kind": "core", "files": "PR", "stages": ["merging", "merged"]},
]
NODE_OF = {stage: node["id"] for node in LINE for stage in node["stages"]}
# The ways back, drawn as dashed loops. `count` is how many times any job took it.
LOOPS = [
    {"id": "gate", "from": "gate", "to": "build", "label": "o gate falhou"},
    {"id": "review", "from": "review", "to": "build", "label": "pedem mudanças"},
]


# ---- reading a repository --------------------------------------------------------------------


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    repo: Path


def find_projects(root: Path, depth: int = 2) -> list[Project]:
    """Every repository under `root` (or `root` itself) that has Puxirum installed."""
    found: list[Path] = []

    def walk(d: Path, left: int) -> None:
        if (d / ".puxirum" / "config.toml").is_file():
            found.append(d)
            return
        if left == 0:
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            return
        for child in children:
            if child.name not in ("node_modules", "venv", ".venv"):
                walk(child, left - 1)

    walk(root, depth)
    projects, seen = [], set()
    for repo in found:
        pid = re.sub(r"[^a-z0-9-]+", "-", repo.name.lower()).strip("-") or "repo"
        while pid in seen:
            pid += "-2"
        seen.add(pid)
        projects.append(Project(pid, repo.name, repo))
    return projects


def _branch(repo: Path) -> str | None:
    head = repo / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        try:  # a worktree or a submodule: .git is a file
            res = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True)
            return res.stdout.strip() or None
        except OSError:
            return None
    return text.rsplit("/", 1)[-1] if text.startswith("ref:") else text[:8]


def _verdict(path: Path, key: str) -> str | None:
    try:
        return parse_header(path.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError):
        return None


def _rounds(store: Store, job: Job) -> list[dict[str, Any]]:
    d = store.job_dir(job.id)
    rounds = []
    for n in range(1, job.round + 1):
        rd = d / f"round-{n}"
        rounds.append(
            {
                "n": n,
                "gate": _verdict(rd / "checks.md", "GATE"),
                "reviews": {lens: _verdict(rd / f"review-{lens}.md", "VERDICT") for lens in job.reviewers},
            }
        )
    return rounds


def _running(store: Store, job: Job) -> list[dict[str, Any]]:
    """The agents of this job running now: each leaves a pid file beside its log while it runs."""
    logs = store.job_dir(job.id) / "logs"
    agents = []
    for pid_file in sorted(logs.glob("*.pid")) if logs.is_dir() else []:
        m = STEM.match(pid_file.stem)
        if not m:
            continue  # a dev server
        role = m["role"]
        lens = role.split("-", 1)[1] if role.startswith("reviewer-") else None
        agents.append(
            {
                "role": "reviewer" if lens else role,
                "lens": lens,
                "round": int(m["round"]),
                "attempt": int(m["attempt"]),
                "doing": _last_step(pid_file.with_suffix(".jsonl"), store, job),
            }
        )
    return agents


def _last_step(stream: Path, store: Store, job: Job) -> str | None:
    try:
        with open(stream, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().splitlines()
    except OSError:
        return None
    roots = (store.repo, store.job_dir(job.id), store.repo / job.worktree)
    for raw in reversed(lines):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if isinstance(event, dict):
            steps = describe(event, roots)
            if steps:
                return steps[-1]
    return None


def _files(store: Store, job: Job) -> list[dict[str, Any]]:
    d = store.job_dir(job.id)
    out = []
    for path in sorted(d.rglob("*")):
        rel = path.relative_to(d).as_posix()
        if not path.is_file() or rel.startswith("logs/") or "/evidence/" in f"/{rel}" or path.suffix not in READABLE:
            continue
        if rel in ("job.json", "events.jsonl") or rel.endswith(".log"):
            continue
        out.append({"path": rel, "bytes": path.stat().st_size})
    return out


def job_view(store: Store, job: Job) -> dict[str, Any]:
    events = store.events(job.id)
    transitions = [e for e in events if e.get("type") == "transition"]
    node = NODE_OF.get(job.stage)
    if node is None:  # waiting for a person, or rejected: shown where it stopped
        stopped = next((e["from"] for e in reversed(transitions) if e.get("to") == job.stage), "intake")
        node = NODE_OF.get(stopped, "intake")
    r = report.job_report(store, job)
    waiting = "author" if job.stage == "needs-info" else "you" if job.stage == "needs-human" else None
    reason = None
    if job.stage == "needs-human":
        reason = job.escalations[-1]["reason"] if job.escalations else job.last_error
    return {
        "id": job.id,
        "issue": job.issue,
        "title": job.title,
        "stage": job.stage,
        "node": node,
        "active": job.stage in ACTIVE,
        "waiting": waiting,
        "reason": " ".join(str(reason).split()) if reason else None,
        "round": job.round,
        "round_limit": job.round_limit,
        "risk": (job.intake or {}).get("risk"),
        "surfaces": (job.intake or {}).get("surfaces", []),
        "reviewers": job.reviewers,
        "pr": job.pr,
        "pr_url": job.pr_url,
        "cost_usd": round(r.cost_usd, 4),
        "active_seconds": round(r.active_seconds),
        "waiting_seconds": round(r.waiting_seconds),
        "by_role": {k: round(v, 4) for k, v in r.by_role.items()},
        "loops": {
            "gate": sum(1 for e in transitions if (e["from"], e["to"]) == ("gate", "build")),
            "review": sum(1 for e in transitions if (e["from"], e["to"]) == ("review", "build")),
            "feedback": sum(1 for e in transitions if e["from"] == "needs-human" and e["to"] != "rejected"),
            "questions": sum(1 for e in transitions if e["to"] == "needs-info"),
        },
        "rounds": _rounds(store, job),
        "running": _running(store, job),
        "timeline": [{"at": e["at"], "from": e["from"], "to": e["to"]} for e in transitions],
        "files": _files(store, job),
        "created": job.created,
        "stage_started": job.stage_started,
        "ended": job.ended,
    }


def state(project: Project) -> dict[str, Any]:
    """Everything the Início tab draws, from the job files alone."""
    store = Store(project.repo)
    try:
        cfg = config.load(project.repo)
        label, problem = cfg.queue_label, None
    except config.ConfigError as e:
        label, problem = None, str(e)
    jobs = [job_view(store, j) for j in store.all()]
    jobs.sort(key=lambda j: (not j["active"], j["waiting"] is None, -j["issue"]))
    loops = [{**loop, "count": sum(j["loops"][loop["id"]] for j in jobs)} for loop in LOOPS]
    return {
        "project": {"id": project.id, "name": project.name, "branch": _branch(project.repo), "label": label},
        "problem": problem,
        "line": [{k: v for k, v in node.items()} for node in LINE],
        "loops": loops,
        "jobs": jobs,
        "totals": {
            "active": sum(1 for j in jobs if j["active"]),
            "waiting": sum(1 for j in jobs if j["stage"] in WAITING),
            "merged": sum(1 for j in jobs if j["stage"] == "merged"),
            "rejected": sum(1 for j in jobs if j["stage"] == "rejected"),
            "cost_usd": round(sum(j["cost_usd"] for j in jobs), 4),
            "coordination_usd": 0.0,
        },
    }


def job_file(project: Project, job_id: str, rel: str) -> str:
    """One of a job's own files. Raises LookupError for anything outside the job's folder or not shown."""
    store = Store(project.repo)
    d = store.job_dir(job_id).resolve()  # job_dir refuses an id that isn't one
    path = (d / rel).resolve()
    if d not in path.parents or not path.is_file():
        raise LookupError(rel)
    shown = {f["path"] for f in _files(store, store.load(job_id))}
    if path.relative_to(d).as_posix() not in shown:
        raise LookupError(rel)
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(MAX_FILE)


# ---- HTTP -----------------------------------------------------------------------------------


class Panel:
    def __init__(self, root: Path, web: Path | None):
        self.root, self.web = root, web
        self._projects: list[Project] = []
        self._found_at = 0.0
        self._lock = threading.Lock()

    def projects(self) -> list[Project]:
        with self._lock:
            if time.monotonic() - self._found_at > 30:
                self._projects, self._found_at = find_projects(self.root), time.monotonic()
            return self._projects

    def project(self, pid: str) -> Project:
        for p in self.projects():
            if p.id == pid:
                return p
        self._found_at = 0.0  # a repository set up since the last look
        for p in self.projects():
            if p.id == pid:
                return p
        raise LookupError(pid)


def handler_for(panel: Panel) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "puxirum-panel"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
            pass

        def do_GET(self) -> None:  # noqa: N802 - the base class's name
            path = unquote(urlparse(self.path).path)
            try:
                if path.startswith("/api/"):
                    self._api(path[len("/api/") :].strip("/").split("/"))
                else:
                    self._static(path)
            except LookupError:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _api(self, parts: list[str]) -> None:
            if parts == ["projects"]:
                body = [{"id": p.id, "name": p.name, "branch": _branch(p.repo)} for p in panel.projects()]
                return self._send(HTTPStatus.OK, body)
            if len(parts) < 3 or parts[0] != "projects":
                raise LookupError(parts)
            project = panel.project(parts[1])
            if parts[2:] == ["state"]:
                return self._send(HTTPStatus.OK, state(project))
            if parts[2:] == ["events"]:
                return self._events(project)
            if len(parts) >= 6 and parts[2] == "jobs" and parts[4] == "files":
                try:
                    text = job_file(project, parts[3], "/".join(parts[5:]))
                except Exception as e:  # noqa: BLE001 - a bad id or path is a 404, never a trace
                    raise LookupError(parts) from e
                return self._send(HTTPStatus.OK, text, "text/plain; charset=utf-8")
            raise LookupError(parts)

        def _events(self, project: Project) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for name, data in watch(project):
                if name:
                    payload = json.dumps(data, ensure_ascii=False)
                    self.wfile.write(f"event: {name}\ndata: {payload}\n\n".encode())
                else:
                    self.wfile.write(b": still here\n\n")
                self.wfile.flush()

        def _static(self, path: str) -> None:
            if panel.web is None:
                raise LookupError(path)
            web = panel.web.resolve()
            target = (web / path.lstrip("/")).resolve()
            if web not in target.parents or not target.is_file():
                target = web / "index.html"  # the app's own routes, like /medicao
            if not target.is_file():
                raise LookupError(path)
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(HTTPStatus.OK, target.read_bytes(), kind)

        def _send(self, status: HTTPStatus, body: Any, kind: str = "application/json") -> None:
            if isinstance(body, bytes):
                data = body
            elif kind == "application/json":
                data = json.dumps(body, ensure_ascii=False).encode()
            else:
                data = str(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def watch(project: Project, tick_s: float = TICK_S, heartbeat_s: float = HEARTBEAT_S) -> Iterator[tuple[str, Any]]:
    """`("state", ...)` now and whenever it changes, then `("backlog", ...)` with the latest steps so far, then
    `("feed", ...)` per new agent step, and `("", None)` to keep alive. A page replaces its steps with the backlog,
    so reconnecting does not repeat them."""
    feed = Feed(Store(project.repo), replay=BACKLOG_STREAMS)
    last = state(project)
    yield "state", last
    # Each step is stamped with the last write to its agent's stream: the steps carry no time of their own.
    history = sorted(feed.steps(), key=lambda step: _mtime(step[0]))[-BACKLOG_STEPS:]
    yield "backlog", [{"at": _clock(_mtime(path)), "who": who, "text": text} for path, who, text in history]
    quiet = 0.0
    while True:
        current = state(project)
        if current != last:
            last, quiet = current, 0.0
            yield "state", current
        steps = [{"at": _clock(time.time()), "who": who, "text": text} for who, text in feed.entries()]
        if steps:
            quiet = 0.0
            yield "feed", steps
        quiet += tick_s
        if quiet >= heartbeat_s:
            quiet = 0.0
            yield "", None
        time.sleep(tick_s)


def _clock(at: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(at))


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()


def default_web() -> Path | None:
    """The built pages: shipped beside this module when installed, or in the source tree after a build."""
    for candidate in (Path(__file__).parent / "web", Path(__file__).resolve().parents[2] / "panel" / "web" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def serve(root: Path, host: str, port: int, web: Path | None, out=sys.stdout) -> None:
    panel = Panel(root, web)
    server = ThreadingHTTPServer((host, port), handler_for(panel))
    server.daemon_threads = True
    names = ", ".join(p.name for p in panel.projects()) or "none yet"
    print(f"puxirum panel on http://{host}:{server.server_address[1]}  (projects: {names})", file=out, flush=True)
    if web is None:
        print("no built pages found: only the API is served (build panel/web, or pass --web)", file=out, flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="puxirum panel", description="Serve the read-only web panel.")
    p.add_argument("--projects", type=Path, help="look for repositories with Puxirum under this folder")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--web", type=Path, help="the built pages (default: the ones shipped with Puxirum)")
    args = p.parse_args(argv)
    root = args.projects or Path.cwd()
    serve(root.resolve(), args.host, args.port, args.web or default_web())
    return 0
