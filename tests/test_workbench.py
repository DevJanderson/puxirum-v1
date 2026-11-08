import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from puxirum import cli
from puxirum.config import parse
from puxirum.engine import Engine
from puxirum.forge import FakeForge
from puxirum.runner import FakeRunner
from puxirum.store import Store
from puxirum.tuios import Tuios
from puxirum.workbench import Workbench, dashboard, snapshot
from puxirum.world import World
from tests import agents
from tests.fake_tuios import FakeDaemon
from tests.gitrepo import Repos


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.repo = Path(self._dir.name)
        self.store = Store(self.repo)
        self.cfg = parse({})
        self.d = FakeDaemon()
        self.core = self.d.add_window("Puxirum", workspace=5)
        self.logs = []

    def tearDown(self):
        self._dir.cleanup()

    def bench(self):
        return Workbench(Tuios("work", self.core, self.d), self.store, self.cfg, log=self.logs.append)

    def job(self, issue, title, stage="intake", **fields):
        with self.store.lock():
            job = self.store.create(issue, title, "puxirum/", ".worktrees")
            job.stage = stage
            for k, v in fields.items():
                setattr(job, k, v)
            self.store.save(job)
        return job

    def surface(self):
        (sid,) = self.d.surfaces
        return self.d.surfaces[sid]

    def verbs(self, name):
        return [p for v, p in self.d.calls if v == name]


class LayoutTest(Base):
    def below(self):
        """The core's log and the feed, the two panes the core split off."""
        split = {info["beside"][1]: w for w, info in self.d.windows.items() if info.get("beside")}
        return split.get("down"), split.get("right")

    def test_open_builds_the_layout(self):
        self.bench().open()
        self.assertEqual(self.d.workspace_names, {5: "puxirum"})
        s = self.surface()
        panel = s["window"]
        self.assertEqual(self.d.windows[panel]["workspace"], 5, "on the core's workspace, not the person's")
        log, feed = self.below()
        self.assertEqual(self.d.windows[log]["beside"], (panel, "down"))
        self.assertEqual(self.d.windows[feed]["beside"], (log, "right"))
        (tail,) = self.d.windows[log]["typed"]
        self.assertEqual(tail, f"exec tail -n 200 -F {self.repo}/.puxirum/state/run.log\n")
        self.assertTrue((self.repo / ".puxirum/state/run.log").exists(), "tail starts on a file that is there")
        (typed,) = self.d.windows[feed]["typed"]
        self.assertTrue(typed.startswith(f"cd {self.repo} && exec env PYTHONPATH="))
        self.assertTrue(typed.endswith(" -m puxirum.cli feed\n"))
        self.assertIn("puxirum · 0 ativos", self.d.notes[self.core])

    def test_a_second_run_reuses_the_panes(self):
        self.bench().open()
        windows = set(self.d.windows)
        self.bench().open()
        self.assertEqual(set(self.d.windows), windows)
        self.assertEqual(len(self.verbs("tml-open")), 1)
        self.assertEqual(len(self.verbs("tml-replace")), 1, "the document is refreshed in place")

    def test_closed_panes_are_opened_again(self):
        self.bench().open()
        _, feed = self.below()
        del self.d.windows[feed]
        self.bench().open()
        self.assertEqual(len(self.verbs("split-window")), 4, "the log and the feed come back together")
        self.assertEqual(len(self.d.windows), 4, "the lone log pane was closed first")
        self.assertEqual(len(self.verbs("tml-open")), 1, "the dashboard was still there")

        b = self.bench()
        b.open()
        del self.d.windows[self.surface()["window"]]
        self.job(1, "x")
        b.refresh()
        self.assertEqual(len(self.verbs("tml-open")), 2, "a closed dashboard comes back on the next refresh")

    def test_a_dashboard_another_pane_opened_is_replaced(self):
        self.bench().open()
        old = dict(self.d.windows)
        self.d.fail["tml-replace"] = "not_owner"
        self.bench().open()
        self.assertEqual(len(self.verbs("tml-open")), 2)
        self.assertEqual(len([w for w in self.d.windows if w in old]), 1, "only the core pane is left of the old ones")
        self.assertEqual(len(self.d.windows), 4)

    def test_panes_from_another_session_are_not_reused(self):
        self.bench().open()
        other = Workbench(Tuios("other", self.core, self.d), self.store, self.cfg)
        other.open()
        self.assertEqual(len(self.verbs("tml-open")), 2)

    def test_a_crowded_workspace_is_mentioned(self):
        self.d.add_window("vim", workspace=5)
        self.bench().open()
        self.assertTrue(any("other pane" in m for m in self.logs))


class RefreshTest(Base):
    def test_data_arrives_as_a_patch_not_as_tml(self):
        self.job(3, "Fix <b> & </state> stuff", stage="build", round=1)
        self.bench().open()
        s = self.surface()
        self.assertNotIn("stuff", s["doc"])
        self.assertEqual(s["state"]["jobs"][0]["job"], "#3 Fix <b> & </state> stuff")
        self.assertEqual(s["state"]["active"], 1)

    def test_refresh_patches_only_what_changed(self):
        b = self.bench()
        b.open()
        before = len(self.verbs("tml-patch"))
        b.refresh()
        self.assertEqual(len(self.verbs("tml-patch")), before, "nothing changed")
        self.job(4, "New", stage="spec")
        b.refresh()
        self.assertEqual(len(self.verbs("tml-patch")), before + 1)
        self.assertEqual(self.surface()["state"]["active"], 1)

    def test_a_job_waiting_for_a_person_reaches_the_inbox_once(self):
        job = self.job(6, "Export CSV", stage="needs-human", escalations=[{"reason": "gate failed after sync"}])
        b = self.bench()
        b.open()
        b.refresh()
        b.refresh()
        self.bench().refresh()  # a new run remembers
        self.assertEqual(len(self.d.asks), 1)
        question, options = self.d.asks[0]
        self.assertIn("#6 aguarda você: gate failed after sync", question)
        self.assertEqual(options, ["ok"])
        with self.store.lock():
            job = self.store.load(job.id)
            job.stage, job.stage_started = "needs-info", "2026-11-08T12:00:00Z"
            self.store.save(job)
        b.refresh()
        self.assertEqual(len(self.d.asks), 2, "a new wait is a new item")
        self.assertIn("aguarda o autor", self.d.asks[1][0])

    def test_a_failing_tuios_never_stops_the_run(self):
        b = self.bench()
        b.open()
        self.d.fail["tml-patch"] = "rate_limited"
        self.job(1, "x")
        b.refresh()
        self.assertTrue(any("rate_limited" in m for m in self.logs))


class SnapshotTest(Base):
    def test_rows_attention_and_order(self):
        self.job(1, "Old", stage="merged", pr=31)
        self.job(2, "Waiting", stage="needs-info")
        self.job(3, "Building", stage="build", round=2)
        s = snapshot(self.store, self.cfg)
        self.assertEqual([r["job"] for r in s["jobs"]], ["#3 Building", "#2 Waiting", "#1 Old"])
        self.assertEqual(s["jobs"][0]["stage"], "build")
        self.assertEqual(s["jobs"][0]["round"], "2")
        self.assertEqual(s["jobs"][2]["pr"], "#31")
        self.assertEqual((s["active"], s["waiting"], s["merged"], s["empty"]), (1, 1, 1, False))
        self.assertEqual(s["attention"], [{"job": "#2 Waiting", "why": "o intake fez perguntas na issue"}])

    def test_empty(self):
        s = snapshot(self.store, self.cfg)
        self.assertTrue(s["empty"])
        self.assertEqual(s["jobs"], [])

    def test_the_document_binds_every_value(self):
        doc = dashboard()
        for key in ("active", "waiting", "merged", "cost", "empty"):
            self.assertIn(f"{{state.{key}}}", doc)
        for key in ("jobs", "roles", "attention"):
            self.assertIn(f'"state.{key}"', doc)


class RunTest(unittest.TestCase):
    """`puxirum run` keeps the workbench up to date and ends with the final state."""

    def test_run_with_a_workbench(self):
        r = Repos()
        self.addCleanup(r.cleanup)
        r.commit(r.main, {".gitignore": ".worktrees/\n.puxirum/state/\n", ".puxirum/checks.sh": "true\n"}, "init")
        r.push_main()
        forge = FakeForge(operator="op")
        forge.add_issue("Editar título", author="ana")
        world = World(r.main, parse({}), Store(r.main), forge)
        engine = Engine(world, FakeRunner(agents.happy(), cost_usd=0.1))
        d = FakeDaemon()
        core = d.add_window("Puxirum", workspace=2)
        bench = Workbench(Tuios("work", core, d), engine.store, engine.cfg)
        out = io.StringIO()
        cli.main(["run"], make_engine=lambda cwd: engine, make_workbench=lambda e: bench, out=out)
        (sid,) = d.surfaces
        state = d.surfaces[sid]["state"]
        self.assertEqual((state["merged"], state["active"]), (1, 0))
        self.assertEqual(state["cost"], "US$ 0.50")

    def test_a_second_run_is_refused(self):
        r = Repos()
        self.addCleanup(r.cleanup)
        engine = Engine(World(r.main, parse({}), Store(r.main), FakeForge(operator="op")), FakeRunner(agents.happy()))
        err = io.StringIO()
        with engine.store.run_lock(), unittest.mock.patch("sys.stderr", err):
            code = cli.main(["run", "--no-workbench"], make_engine=lambda cwd: engine, out=io.StringIO())
            code_wb = cli.main(
                ["workbench"],
                make_engine=lambda cwd: engine,
                make_workbench=lambda e: unittest.mock.Mock(),
                out=io.StringIO(),
            )
        self.assertEqual((code, code_wb), (1, 1))
        self.assertIn("another `puxirum run` is working", err.getvalue())

    def test_workbench_command(self):
        engine = unittest.mock.MagicMock()
        bench = unittest.mock.Mock()
        out = io.StringIO()
        self.assertEqual(
            cli.main(["workbench"], make_engine=lambda cwd: engine, make_workbench=lambda e: bench, out=out), 0
        )
        bench.open.assert_called_once_with()
        with unittest.mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.main(["workbench"], make_engine=lambda cwd: engine, make_workbench=lambda e: None), 1)

    def test_the_log_goes_to_the_run_log_too(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state" / "run.log"
            with unittest.mock.patch("sys.stderr", io.StringIO()) as err:
                log = cli.logger(path)
                log("001-x: new job for #1")
                log("001-x: merged")
            self.assertEqual(err.getvalue(), "001-x: new job for #1\n001-x: merged\n")
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertRegex(lines[0], r"^\d\d:\d\d:\d\d  001-x: new job for #1$")

    def test_no_workbench_flag(self):
        called = []
        engine = unittest.mock.MagicMock()
        engine.run.return_value = {"agents": 0, "cost_usd": 0.0, "wall_seconds": 0}
        engine.plan.return_value = []
        engine.store.all.return_value = []
        cli.main(
            ["run", "--no-workbench"], make_engine=lambda cwd: engine, make_workbench=called.append, out=io.StringIO()
        )
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
