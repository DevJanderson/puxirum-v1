import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from puxirum.store import Effect, Job, Store, StoreError, slugify


def _bump(repo: str, times: int) -> None:
    store = Store(Path(repo))
    for _ in range(times):
        with store.lock():
            job = store.load("001-x")
            job.seq += 1
            store.save(job)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.repo = Path(self._dir.name)
        self.store = Store(self.repo)

    def tearDown(self):
        self._dir.cleanup()

    def create(self, issue=1, title="Mostrar contador"):
        with self.store.lock():
            return self.store.create(issue, title, "puxirum/", ".worktrees")

    def test_create_assigns_sequential_ids(self):
        a = self.create(4, "Editar título da tarefa")
        b = self.create(9, "Dark mode!")
        self.assertEqual(a.id, "001-editar-titulo-da-tarefa")
        self.assertEqual(b.id, "002-dark-mode")
        self.assertEqual(a.branch, "puxirum/001-editar-titulo-da-tarefa")
        self.assertEqual(a.worktree, ".worktrees/001-editar-titulo-da-tarefa")
        self.assertEqual((a.stage, a.round, a.seq), ("intake", 0, 0))
        self.assertEqual([e["type"] for e in self.store.events(a.id)], ["created"])

    def test_one_job_per_issue(self):
        self.create(1)
        with self.assertRaises(StoreError):
            self.create(1, "again")

    def test_round_trip(self):
        job = self.create()
        job.pending = [Effect(kind="push", key="001:1:0", args={"branch": "b"})]
        job.escalations = [{"from": "build", "reason": "x"}]
        with self.store.lock():
            self.store.save(job)
        self.assertEqual(self.store.load(job.id), job)
        self.assertIsInstance(self.store.load(job.id).pending[0], Effect)

    def test_find_by_issue_or_id(self):
        job = self.create(7)
        self.assertEqual(self.store.find(7).id, job.id)
        self.assertEqual(self.store.find("7").id, job.id)
        self.assertEqual(self.store.find(job.id).id, job.id)
        with self.assertRaises(StoreError):
            self.store.find(8)

    def test_refuses_bad_ids_and_unknown_fields(self):
        with self.assertRaises(StoreError):
            self.store.load("../etc")
        job = self.create()
        path = self.store.job_dir(job.id) / "job.json"
        data = json.loads(path.read_text())
        path.write_text(json.dumps({**data, "surprise": 1}))
        with self.assertRaises(StoreError):
            self.store.load(job.id)
        path.write_text(json.dumps({**data, "schema": 99}))
        with self.assertRaises(StoreError):
            self.store.load(job.id)

    def test_save_leaves_no_temp_files(self):
        job = self.create()
        with self.store.lock():
            self.store.save(job)
        self.assertEqual(sorted(p.name for p in self.store.job_dir(job.id).iterdir()), ["events.jsonl", "job.json"])

    def test_lock_serialises_writers_across_processes(self):
        with self.store.lock():
            self.store.save(Job(id="001-x", issue=1, title="x", branch="b", worktree="w"))
        ctx = multiprocessing.get_context("fork")
        procs = [ctx.Process(target=_bump, args=(str(self.repo), 50)) for _ in range(4)]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(self.store.load("001-x").seq, 200)


class SlugTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Ação: editar título"), "acao-editar-titulo")
        self.assertEqual(slugify("one two three four five"), "one-two-three-four")
        self.assertEqual(slugify("!!!"), "issue")


if __name__ == "__main__":
    unittest.main()
