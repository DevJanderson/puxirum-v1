import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from puxirum import hook
from puxirum.claude import POLICIES, agent_env, settings_for
from puxirum.runner import AgentTask
from tests.gitrepo import Repos


class StopChecksTest(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.r.commit(self.r.main, {"app.txt": "v1\n"}, "init")
        self.checks = self.r.main.parent / "checks.sh"
        self.checks.write_text("test ! -e bug.txt || { echo 'bug found'; exit 1; }\n")
        self.env = {"PUXIRUM_WORKTREE": str(self.r.main), "PUXIRUM_CHECKS": str(self.checks)}

    def tearDown(self):
        self.r.cleanup()

    def test_passes_when_checks_pass_and_tree_is_clean(self):
        self.assertEqual(hook.stop_checks({}, self.env), (0, ""))

    def test_blocks_once_when_checks_fail(self):
        self.r.commit(self.r.main, {"bug.txt": "x"}, "bug")
        code, msg = hook.stop_checks({}, self.env)
        self.assertEqual(code, 2)
        self.assertIn("bug found", msg)
        self.assertIn("STATUS: BLOCKED", msg)
        self.assertEqual(hook.stop_checks({"stop_hook_active": True}, self.env), (0, ""), "the second stop goes through")

    def test_blocks_a_dirty_worktree(self):
        (self.r.main / "scratch.txt").write_text("x")
        code, msg = hook.stop_checks({}, self.env)
        self.assertEqual(code, 2)
        self.assertIn("scratch.txt", msg)

    def test_does_nothing_outside_a_builder(self):
        self.assertEqual(hook.stop_checks({}, {}), (0, ""))

    def test_command_line(self):
        self.r.commit(self.r.main, {"bug.txt": "x"}, "bug")
        src = str(Path(hook.__file__).resolve().parents[1])
        res = subprocess.run([sys.executable, "-m", "puxirum.hook", "stop-checks"], input=json.dumps({}),
                             capture_output=True, text=True, env={**os.environ, **self.env, "PYTHONPATH": src})
        self.assertEqual(res.returncode, 2)
        self.assertIn("bug found", res.stderr)


class BuilderSettingsTest(unittest.TestCase):
    def task(self, role, tmp):
        return AgentTask(role=role, lens=None, job_id="001-x", model="sonnet", cwd=tmp, job_dir=tmp / "job",
                         output=tmp / "job" / "build.md", vars={"checks": "/repo/.puxirum/checks.sh",
                                                                 "checks_timeout_s": 600})

    def test_only_the_builder_gets_the_stop_hook(self):
        tmp = Path(self.id().replace(".", "_"))
        builder = settings_for(self.task("builder", tmp), POLICIES["builder"])
        stop = builder["hooks"]["Stop"][0]["hooks"][0]
        self.assertIn("-m puxirum.hook stop-checks", stop["command"])
        self.assertEqual(stop["timeout"], 600)
        self.assertNotIn("hooks", settings_for(self.task("approver", tmp), POLICIES["approver"]))

    def test_builder_env_points_the_hook_at_the_worktree(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = agent_env(self.task("builder", Path(d)), base={"PATH": "/usr/bin"})
        self.assertEqual(env["PUXIRUM_CHECKS"], "/repo/.puxirum/checks.sh")
        self.assertEqual(env["PUXIRUM_WORKTREE"], d)
        self.assertTrue(Path(env["PYTHONPATH"].split(os.pathsep)[0], "puxirum", "hook.py").exists())


if __name__ == "__main__":
    unittest.main()
