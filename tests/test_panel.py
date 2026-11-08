import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from puxirum import orphans, panel
from puxirum.store import Store


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.repo = self.root / "app"
        (self.repo / ".puxirum").mkdir(parents=True)
        (self.repo / ".puxirum/config.toml").write_text('[queue]\nlabel = "fila"\n')
        (self.repo / ".git").mkdir()
        (self.repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
        self.store = Store(self.repo)
        self.project = panel.Project("app", "app", self.repo)

    def tearDown(self):
        self._dir.cleanup()

    def job(self, issue, title, stage, transitions=(), **fields):
        with self.store.lock():
            job = self.store.create(issue, title, "puxirum/", ".worktrees")
            job.stage = stage
            for k, v in fields.items():
                setattr(job, k, v)
            self.store.save(job)
        for a, b in transitions:
            self.store.event(job.id, "transition", **{"from": a, "to": b, "seq": 1, "reason": None})
        return job

    def write(self, job, rel, text):
        path = self.store.job_dir(job.id) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class StateTest(Base):
    def test_a_job_in_review_with_its_rounds_and_ways_back(self):
        job = self.job(
            7,
            "Dark mode",
            "review",
            transitions=[
                ("intake", "spec"),
                ("spec", "build"),
                ("build", "gate"),
                ("gate", "build"),
                ("build", "gate"),
                ("gate", "review"),
                ("review", "build"),
                ("build", "gate"),
                ("gate", "review"),
            ],
            round=2,
            round_limit=3,
            reviewers={"code": "haiku", "ux": "sonnet"},
            intake={"decision": "ACCEPT", "risk": "medium", "surfaces": ["ui"], "rescoped": False},
        )
        self.write(job, "round-1/checks.md", "GATE: FAIL\n\n## Summary\n- x\n")
        self.write(job, "round-2/checks.md", "GATE: PASS\nCOMMIT: " + "a" * 40 + "\n\n## Summary\n- x\n")
        self.write(job, "round-2/review-code.md", "VERDICT: PASS\n\n## Summary\n- x\n")
        self.write(job, "spec.md", "# Dark mode\n")
        self.write(
            job,
            "logs/reviewer-ux-r2-a1.jsonl",
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Read", "input": {"file_path": str(self.repo / "src/app.ts")}}
                        ]
                    },
                }
            )
            + "\n",
        )
        orphans.record(self.store.job_dir(job.id) / "logs/reviewer-ux-r2-a1.pid", 1, "claude")

        s = panel.state(self.project)
        self.assertEqual(s["project"], {"id": "app", "name": "app", "branch": "main", "label": "fila"})
        (j,) = s["jobs"]
        self.assertEqual((j["node"], j["active"], j["waiting"], j["risk"]), ("review", True, None, "medium"))
        self.assertEqual(j["loops"], {"gate": 1, "review": 1, "feedback": 0, "questions": 0})
        self.assertEqual(j["rounds"][0], {"n": 1, "gate": "FAIL", "reviews": {"code": None, "ux": None}})
        self.assertEqual(j["rounds"][1]["reviews"], {"code": "PASS", "ux": None}, "ux still working")
        self.assertEqual(
            j["running"], [{"role": "reviewer", "lens": "ux", "round": 2, "attempt": 1, "doing": "Read src/app.ts"}]
        )
        self.assertEqual(
            [f["path"] for f in j["files"]],
            ["round-1/checks.md", "round-2/checks.md", "round-2/review-code.md", "spec.md"],
        )
        self.assertEqual({lp["id"]: lp["count"] for lp in s["loops"]}, {"gate": 1, "review": 1})
        self.assertEqual(s["totals"]["active"], 1)
        self.assertEqual(
            [n["id"] for n in s["line"]], ["intake", "spec", "build", "gate", "review", "approve", "merge"]
        )

    def test_waiting_and_finished_jobs_sit_where_they_stopped(self):
        self.job(1, "Old", "merged", transitions=[("merging", "merged")], pr=3)
        self.job(2, "Vague", "needs-info", transitions=[("intake", "needs-info")])
        self.job(
            3,
            "Stuck",
            "needs-human",
            transitions=[("gate", "needs-human")],
            escalations=[{"from": "gate", "reason": "gate failed\n after sync"}],
        )
        jobs = {j["issue"]: j for j in panel.state(self.project)["jobs"]}
        self.assertEqual((jobs[1]["node"], jobs[1]["active"]), ("merge", False))
        self.assertEqual((jobs[2]["node"], jobs[2]["waiting"], jobs[2]["loops"]["questions"]), ("intake", "author", 1))
        self.assertEqual(
            (jobs[3]["node"], jobs[3]["waiting"], jobs[3]["reason"]), ("gate", "you", "gate failed after sync")
        )
        self.assertEqual([j["issue"] for j in panel.state(self.project)["jobs"]], [3, 2, 1], "waiting before done")

    def test_a_broken_config_is_reported_not_raised(self):
        (self.repo / ".puxirum/config.toml").write_text("[queue\n")
        s = panel.state(self.project)
        self.assertIsNotNone(s["problem"])
        self.assertIsNone(s["project"]["label"])


class FileTest(Base):
    def test_only_the_jobs_own_shown_files(self):
        job = self.job(1, "x", "build")
        self.write(job, "spec.md", "the spec")
        self.write(job, "logs/builder-r1-a1.prompt.md", "a prompt")
        self.write(job, "round-1/evidence/shot.md", "evidence")
        (self.repo / ".puxirum/secret.md").write_text("no")
        self.assertEqual(panel.job_file(self.project, job.id, "spec.md"), "the spec")
        for rel in (
            "logs/builder-r1-a1.prompt.md",
            "job.json",
            "events.jsonl",
            "../../../secret.md",
            "round-1/evidence/shot.md",
            "nope.md",
        ):
            with self.assertRaises(LookupError, msg=rel):
                panel.job_file(self.project, job.id, rel)

    def test_a_bad_job_id_is_refused(self):
        with self.assertRaises(Exception):  # noqa: B017 - the store refuses it before any path is built
            panel.job_file(self.project, "../app", "spec.md")


class FindTest(Base):
    def test_finds_repositories_with_puxirum(self):
        (self.root / "other/.git").mkdir(parents=True)
        (self.root / "nested/deep/.puxirum").mkdir(parents=True)
        (self.root / "nested/deep/.puxirum/config.toml").write_text("")
        (self.root / "node_modules/x/.puxirum").mkdir(parents=True)
        (self.root / "node_modules/x/.puxirum/config.toml").write_text("")
        found = panel.find_projects(self.root)
        self.assertEqual(
            [(p.id, p.repo.relative_to(self.root).as_posix()) for p in found], [("app", "app"), ("deep", "nested/deep")]
        )
        self.assertEqual([p.id for p in panel.find_projects(self.repo)], ["app"], "the root itself")


class WatchTest(Base):
    def test_state_first_then_feed_steps_and_heartbeats(self):
        job = self.job(1, "x", "build", round=1)
        stream = self.store.job_dir(job.id) / "logs/builder-r1-a1.jsonl"
        stream.parent.mkdir(parents=True)
        stream.write_text("")
        events = panel.watch(self.project, tick_s=0.01, heartbeat_s=0.02)
        name, data = next(events)
        self.assertEqual(name, "state")
        self.assertEqual(data["jobs"][0]["issue"], 1)
        self.assertEqual(next(events), ("backlog", []), "nothing done yet")
        stream.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]},
                }
            )
            + "\n"
        )
        name, data = next(events)
        self.assertEqual(name, "feed")
        self.assertEqual([(s["who"], s["text"]) for s in data], [("#1 builder r1", "$ npm test")])
        self.assertEqual(next(events), ("", None), "nothing new: a heartbeat")
        self.store.event(job.id, "transition", **{"from": "build", "to": "gate", "seq": 2, "reason": None})
        self.assertEqual(next(events)[0], "state")

    def test_a_page_that_connects_late_gets_the_latest_finished_steps(self):
        job = self.job(1, "x", "gate", round=1)
        stream = self.store.job_dir(job.id) / "logs/builder-r1-a1.jsonl"
        stream.parent.mkdir(parents=True)
        step = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]},
        }
        done = {"type": "result", "total_cost_usd": 0.1, "duration_ms": 60000}
        stream.write_text(json.dumps(step) + "\n" + json.dumps(done) + "\n")
        events = panel.watch(self.project, tick_s=0.01, heartbeat_s=1)
        self.assertEqual(next(events)[0], "state")
        name, data = next(events)
        self.assertEqual(name, "backlog")
        self.assertEqual([s["text"] for s in data], ["$ npm test", "✓ done · US$ 0.10 · 1m00s"])
        self.assertEqual({s["who"] for s in data}, {"#1 builder r1"})


class HttpTest(Base):
    def setUp(self):
        super().setUp()
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<!doctype html><title>Puxirum</title>")
        (self.web / "app.js").write_text("console.log(1)")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), panel.handler_for(panel.Panel(self.root, self.web)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as res:
            return res.status, res.headers["Content-Type"], res.read().decode()

    def test_api_and_pages(self):
        job = self.job(4, "Edit title", "spec")
        self.write(job, "intake.md", "DECISION: ACCEPT\n")
        status, kind, body = self.get("/api/projects")
        self.assertEqual(
            (status, kind, json.loads(body)),
            (200, "application/json", [{"id": "app", "name": "app", "branch": "main"}]),
        )
        self.assertEqual(json.loads(self.get("/api/projects/app/state")[2])["jobs"][0]["stage"], "spec")
        self.assertEqual(self.get(f"/api/projects/app/jobs/{job.id}/files/intake.md")[2], "DECISION: ACCEPT\n")
        self.assertEqual(self.get("/app.js")[2], "console.log(1)")
        self.assertIn("<title>Puxirum", self.get("/app/medicao")[2], "the app's own routes get the page")

    def test_not_found(self):
        job = self.job(4, "x", "spec")
        for path in (
            "/api/projects/nope/state",
            f"/api/projects/app/jobs/{job.id}/files/job.json",
            "/api/nothing",
            "/api/projects/app/jobs/..%2F..%2Fx/files/a.md",
        ):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as e:
                self.get(path)
            self.assertEqual(e.exception.code, 404)
            e.exception.close()

    def test_the_event_stream_starts_with_the_state(self):
        self.job(1, "x", "intake")
        with urllib.request.urlopen(self.base + "/api/projects/app/events", timeout=5) as res:
            self.assertEqual(res.headers["Content-Type"], "text/event-stream")
            self.assertEqual(res.readline(), b"event: state\n")
            self.assertEqual(json.loads(res.readline()[len(b"data: ") :])["jobs"][0]["issue"], 1)


if __name__ == "__main__":
    unittest.main()
