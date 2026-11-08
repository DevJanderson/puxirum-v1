import os
import time
import unittest

from puxirum import files, gate
from puxirum.config import Config, parse
from puxirum.gate import GateError
from tests.gitrepo import Repos, git

PASSING = "#!/usr/bin/env bash\nset -euo pipefail\necho checking\n"


class GateTest(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.r.commit(self.r.main, {
            ".puxirum/checks.sh": PASSING,
            ".puxirum/config.toml": "",
            ".gitignore": ".worktrees/\nout/\n",
            "src/app.txt": "v1\n",
            "docs/my notes.txt": "x\n",
        }, "init")
        self.r.push_main()
        self.cfg = Config()
        self.wt = self.r.worktree("puxirum/001-x")
        self.out = self.r.main / "out" / "round-1"

    def tearDown(self):
        self.r.cleanup()

    def run_gate(self, cfg=None, **kw):
        return gate.run(cfg or self.cfg, self.r.main, self.wt, self.out, **kw)

    def report(self, name="checks.md"):
        return files.read(self.out / name, "checks")

    def test_pass(self):
        sha = self.r.commit(self.wt, {"src/app.txt": "v2\n"})
        res = self.run_gate()
        self.assertEqual((res.verdict, res.commit, res.exit_code), ("PASS", sha, 0))
        f = self.report()
        self.assertEqual(f.header, {"GATE": "PASS", "COMMIT": sha})
        self.assertIn("checks passed", f.summary[0])
        self.assertIn("checking", (self.out / "checks.log").read_text())

    def test_fail_on_exit_code(self):
        self.r.commit(self.r.main, {".puxirum/checks.sh": "echo boom >&2\nexit 3\n"})
        self.r.commit(self.wt, {"src/app.txt": "v2\n"})
        res = self.run_gate()
        self.assertEqual((res.verdict, res.exit_code), ("FAIL", 3))
        f = self.report()
        self.assertIn("exit 3", f.summary[0])
        self.assertIn("boom", f.section("Checks"))

    def test_uses_the_main_checkouts_script(self):
        cfg = parse({"gate": {"checks": "ci.sh", "protected": []}})
        self.r.commit(self.r.main, {"ci.sh": "exit 1\n"})
        self.r.push_main()
        wt = self.r.worktree("puxirum/002-y")
        self.r.commit(wt, {"ci.sh": "exit 0\n"})
        res = gate.run(cfg, self.r.main, wt, self.out)
        self.assertEqual(res.verdict, "FAIL", "the branch's own ci.sh must not be the one that runs")

    def test_protected_paths(self):
        cases = [
            ({".puxirum/checks.sh": PASSING + "# tweak\n"}, "M .puxirum/checks.sh"),
            ({".puxirum/config.toml": None}, "D .puxirum/config.toml"),
        ]
        for change, hit in cases:
            with self.subTest(hit=hit):
                git(self.wt, "reset", "-q", "--hard", "origin/main")
                self.r.commit(self.wt, change)
                res = self.run_gate()
                self.assertEqual((res.verdict, res.exit_code, res.protected), ("FAIL", 0, [hit]))
                self.assertIn(hit, self.report().section("Protected paths"))

    def test_renaming_a_protected_file_away_fails(self):
        git(self.wt, "mv", ".puxirum/config.toml", "config.toml")
        git(self.wt, "commit", "-q", "-m", "move")
        self.assertEqual(self.run_gate().protected, ["D .puxirum/config.toml"])

    def test_adding_a_file_under_a_protected_pattern_passes(self):
        self.r.commit(self.wt, {".puxirum/roles/new.md": "x\n"})
        self.assertEqual(self.run_gate().verdict, "PASS")

    def test_paths_with_spaces(self):
        cfg = parse({"gate": {"protected": ["docs/my notes.txt"]}})
        self.r.commit(self.wt, {"docs/my notes.txt": "y\n"})
        self.assertEqual(self.run_gate(cfg).protected, ["M docs/my notes.txt"])

    def test_dirty_worktree_fails_without_running(self):
        self.r.commit(self.r.main, {".puxirum/checks.sh": "touch ran\n"})
        self.r.write(self.wt, {"src/app.txt": "uncommitted\n", "new file.txt": "x"})
        res = self.run_gate()
        self.assertEqual((res.verdict, res.exit_code), ("FAIL", None))
        self.assertEqual(sorted(res.dirty), ["new file.txt", "src/app.txt"])
        self.assertFalse((self.wt / "ran").exists())
        self.assertIn("not run", self.report().summary[0])

    def test_notes_files_the_checks_left_behind(self):
        self.r.commit(self.r.main, {".puxirum/checks.sh": "echo built > artifact.txt\n"})
        res = self.run_gate()
        self.assertEqual((res.verdict, res.left_dirty), ("PASS", ["artifact.txt"]))
        self.assertIn("artifact.txt", self.report().section("Notes"))

    def test_timeout_kills_the_whole_process_group(self):
        pidfile = self.r.main / "out" / "child.pid"
        self.r.commit(self.r.main, {".puxirum/checks.sh": f"sleep 60 &\necho $! > '{pidfile}'\nsleep 60\n"})
        self.out.mkdir(parents=True)
        start = time.monotonic()
        res = self.run_gate(timeout_s=0.5)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual((res.verdict, res.timed_out), ("FAIL", True))
        self.assertIn("timed out", self.report().summary[0])
        child = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    def test_background_children_do_not_outlive_a_passing_run(self):
        pidfile = self.r.main / "out" / "child.pid"
        self.r.commit(self.r.main, {".puxirum/checks.sh": f"sleep 60 &\necho $! > '{pidfile}'\n"})
        self.out.mkdir(parents=True)
        self.assertEqual(self.run_gate().verdict, "PASS")
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_env_is_passed(self):
        self.r.commit(self.r.main, {".puxirum/checks.sh": 'test "$PUXIRUM_PORT" = 5210\n'})
        self.assertEqual(self.run_gate(env={"PUXIRUM_PORT": "5210"}).verdict, "PASS")

    def test_merge_report_name(self):
        self.run_gate(merge=True)
        f = self.report("merge-checks.md")
        self.assertIn("before merging", f.summary[2])
        self.assertTrue((self.out / "merge-checks.log").exists())

    def test_errors_that_are_not_the_branchs_fault(self):
        with self.assertRaisesRegex(GateError, "not found"):
            self.run_gate(parse({"gate": {"checks": "missing.sh"}}))
        with self.assertRaisesRegex(GateError, "doesn't exist"):
            gate.run(self.cfg, self.r.main, self.r.main / "nope", self.out)
        with self.assertRaisesRegex(GateError, "rev-parse"):
            self.run_gate(base_ref="origin/nope")


if __name__ == "__main__":
    unittest.main()
