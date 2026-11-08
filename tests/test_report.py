import io
import json
import unittest
from datetime import datetime, timedelta, timezone

from puxirum import cli, report
from puxirum.config import parse
from puxirum.engine import Engine
from puxirum.forge import FakeForge
from puxirum.runner import FakeRunner
from puxirum.store import Store
from puxirum.world import World

from tests import agents
from tests.gitrepo import Repos

T0 = datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)


def at(seconds):
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.r.commit(self.r.main, {".gitignore": ".worktrees/\n.puxirum/state/\n", ".puxirum/checks.sh": "true\n",
                                    "app.txt": "v1\n"}, "init")
        self.r.push_main()
        self.store = Store(self.r.main)
        self.forge = FakeForge(operator="op")

    def tearDown(self):
        self.r.cleanup()

    def fake_job(self, events):
        with self.store.lock():
            job = self.store.create(3, "Melhorar o app", "puxirum/", ".worktrees")
        path = self.store.job_dir(job.id) / "events.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        return self.store.load(job.id)

    def test_active_and_waiting_time(self):
        """Like the pilot's #3: 16 minutes of its 30 were spent waiting for the author."""
        job = self.fake_job([
            {"at": at(0), "type": "created"},
            {"at": at(20), "type": "transition", "from": "intake", "to": "needs-info"},
            {"at": at(1000), "type": "transition", "from": "needs-info", "to": "intake"},
            {"at": at(1020), "type": "transition", "from": "intake", "to": "spec"},
            {"at": at(1800), "type": "transition", "from": "merging", "to": "merged"},
            {"at": at(1810), "type": "transition", "from": "merged", "to": "ignored"},
        ])
        r = report.job_report(self.store, job)
        self.assertEqual((r.active_seconds, r.waiting_seconds), (20 + 800, 980))
        self.assertEqual(r.total_seconds, 1800)

    def test_unfinished_job_counts_until_now(self):
        job = self.fake_job([{"at": at(0), "type": "created"},
                             {"at": at(60), "type": "transition", "from": "intake", "to": "needs-human"}])
        r = report.job_report(self.store, job, until=T0 + timedelta(seconds=600))
        self.assertEqual((r.active_seconds, r.waiting_seconds), (60, 540))

    def test_costs_by_role_and_model_and_unpriced_runs(self):
        job = self.fake_job([
            {"at": at(0), "type": "created"},
            {"at": at(1), "type": "agent", "role": "intake", "lens": None, "model": "sonnet", "cost_usd": 0.05, "seconds": 10},
            {"at": at(2), "type": "agent", "role": "reviewer", "lens": "ux", "model": "sonnet", "cost_usd": 0.20, "seconds": 30},
            {"at": at(3), "type": "agent", "role": "reviewer", "lens": "code", "model": "haiku", "cost_usd": 0.01, "seconds": 5},
            {"at": at(4), "type": "agent", "role": "builder", "lens": None, "model": "sonnet", "cost_usd": None, "seconds": 50},
        ])
        r = report.job_report(self.store, job)
        self.assertAlmostEqual(r.cost_usd, 0.26)
        self.assertEqual((r.agents, r.unpriced, r.agent_seconds), (4, 1, 95))
        self.assertEqual(r.by_role, {"intake": 0.05, "reviewer:ux": 0.20, "reviewer:code": 0.01})
        self.assertAlmostEqual(r.by_model["sonnet"], 0.25)
        text = report.render(self.store, parse({}))
        self.assertIn("$0.26*", text)
        self.assertIn("1 unpriced", text)
        self.assertIn("Coordination:  $0.00", text)

    def engine(self, scripts, **cfg):
        world = World(self.r.main, parse(cfg), self.store, self.forge)
        return Engine(world, FakeRunner(scripts, cost_usd=0.10))

    def test_a_run_is_recorded(self):
        self.forge.add_issue("Editar título", author="ana")
        summary = self.engine(agents.happy()).run()
        self.assertEqual((summary["agents"], summary["unpriced"], summary["coordination_usd"]), (5, 0, 0.0))
        self.assertAlmostEqual(summary["cost_usd"], 0.50)
        self.assertEqual(report.runs(self.store), [summary])
        job = self.store.all()[0]
        self.assertTrue(all(ev["run"] == summary["id"] for ev in self.store.events(job.id) if ev["type"] == "agent"))

    def test_a_run_that_crashes_is_still_recorded(self):
        def crash(task):
            raise KeyboardInterrupt
        self.forge.add_issue("Editar título", author="ana")
        with self.assertRaises(KeyboardInterrupt):
            self.engine(agents.happy(spec=crash)).run()
        (record,) = report.runs(self.store)
        self.assertEqual(record["agents"], 1, "the intake ran before the crash")

    def test_baseline_comparison(self):
        self.forge.add_issue("Editar título", author="ana")
        cfg = {"report": {"baseline_label": "zazencodes pilot", "baseline_usd": 8.53, "baseline_minutes": 78}}
        self.engine(agents.happy(), **cfg).run()
        text = report.render(self.store, parse(cfg))
        self.assertIn("Baseline (zazencodes pilot): $8.53, 1h18m", text)
        self.assertIn("This project:  $0.50 (6% of the baseline)", text)

    def test_cli_report(self):
        self.forge.add_issue("Editar título", author="ana")
        e = self.engine(agents.happy())
        out = io.StringIO()
        cli.main(["run"], make_engine=lambda cwd: e, out=out)
        self.assertIn("This run: 5 agent runs, $0.50", out.getvalue())
        out = io.StringIO()
        cli.main(["report"], make_engine=lambda cwd: e, out=out)
        self.assertIn("001-editar-titulo", out.getvalue())
        out = io.StringIO()
        cli.main(["report", "--json"], make_engine=lambda cwd: e, out=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["jobs"][0]["agents"], 5)
        self.assertEqual(data["coordination_usd"], 0.0)

    def test_no_jobs(self):
        self.assertEqual(report.render(self.store, parse({})), "No jobs yet.\n")


if __name__ == "__main__":
    unittest.main()
