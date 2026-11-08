import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from puxirum.claude import POLICIES, ClaudeRunner, agent_env, settings_for
from puxirum.runner import AgentTask

FAKE = Path(__file__).with_name("fake_claude.py")


class ClaudeRunnerTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.worktree = root / "repo" / ".worktrees" / "001-x"
        self.job_dir = root / "repo" / ".puxirum" / "state" / "jobs" / "001-x"
        self.worktree.mkdir(parents=True)
        self.job_dir.mkdir(parents=True)
        self.record = root / "record.json"
        self.env = mock.patch.dict(
            os.environ,
            {
                "FAKE_CLAUDE_RECORD": str(self.record),
                "SSH_AUTH_SOCK": "/run/agent.sock",
                "GH_TOKEN": "secret",
                "TUIOS_SESSION": "s",
                "TUIOS_PANE_ID": "p",
                "HOME_KEEP": "yes",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._dir.cleanup()

    def task(self, role="builder", lens=None, output="build.md", **vars_):
        return AgentTask(
            role=role,
            lens=lens,
            job_id="001-x",
            model="sonnet",
            cwd=self.worktree,
            job_dir=self.job_dir,
            output=self.job_dir / output,
            vars={"round": 1, "attempt": 1, "port": 5200, **vars_},
        )

    def runner(self, **kw):
        return ClaudeRunner(prompt_for=lambda t: f"You are the {t.name}.", command=(sys.executable, str(FAKE)), **kw)

    def run_fake(self, task=None, mode="ok", **kw):
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_MODE": mode}):
            result = self.runner(**kw).run(task or self.task())
        rec = json.loads(self.record.read_text()) if self.record.exists() else None
        return result, rec

    def flag(self, argv, name):
        return argv[argv.index(name) + 1]

    # ---- the command line ------------------------------------------------------------------

    def test_argv(self):
        _, rec = self.run_fake(budget_usd={"builder": 4})
        argv = rec["argv"]
        self.assertEqual(argv[0], "-p")
        self.assertEqual(self.flag(argv, "--model"), "sonnet")
        self.assertEqual(self.flag(argv, "--output-format"), "json")
        self.assertEqual(self.flag(argv, "--permission-mode"), "dontAsk")
        self.assertEqual(self.flag(argv, "--setting-sources"), "")
        self.assertEqual(self.flag(argv, "--max-budget-usd"), "4.00")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(json.loads(self.flag(argv, "--settings"))["permissions"]["defaultMode"], "dontAsk")

    def test_prompt_goes_on_stdin_and_is_logged(self):
        _, rec = self.run_fake()
        self.assertEqual(rec["prompt"], "You are the builder.")
        self.assertNotIn("You are the builder.", " ".join(rec["argv"]))
        self.assertEqual((self.job_dir / "logs" / "builder-r1-a1.prompt.md").read_text(), "You are the builder.")
        self.assertEqual(rec["cwd"], str(self.worktree))

    # ---- permissions -------------------------------------------------------------------------

    def rules(self, task):
        return settings_for(task, POLICIES[task.role])["permissions"]

    def test_intake_has_no_shell_and_writes_only_its_file(self):
        task = self.task("intake", output="intake.md")
        self.assertNotIn("Bash", POLICIES["intake"].tools)
        rules = self.rules(task)
        self.assertFalse([r for r in rules["allow"] if r.startswith("Bash")])
        edits = [r for r in rules["allow"] if r.startswith("Edit")]
        self.assertEqual(edits, [f"Edit(/{self.job_dir}/intake.md)"])

    def test_builder_edits_the_worktree_but_cannot_reach_the_remote(self):
        rules = self.rules(self.task())
        self.assertIn(f"Edit(/{self.worktree}/**)", rules["allow"])
        self.assertIn("Bash", rules["allow"])
        for denied in ("Bash(git push:*)", "Bash(gh:*)", "Bash(git remote:*)", "Bash(git rebase:*)"):
            self.assertIn(denied, rules["deny"])

    def test_reviewer_reads_and_browses_but_does_not_edit_code(self):
        rules = self.rules(
            self.task("reviewer", "ux", "round-1/review-ux.md", writable=[str(self.job_dir / "round-1" / "evidence")])
        )
        self.assertNotIn(f"Edit(/{self.worktree}/**)", rules["allow"])
        self.assertIn("Bash(agent-browser:*)", rules["allow"])
        self.assertIn(f"Edit(/{self.job_dir}/round-1/evidence/**)", rules["allow"])
        self.assertNotIn("Bash", rules["allow"], "no blanket shell")
        self.assertNotIn("Edit", POLICIES["reviewer"].tools)

    def sandboxed(self, **vars_):
        main = self.worktree.parent.parent
        return self.task(sandbox=True, main_checkout=str(main), branch="puxirum/001-x", **vars_), main / ".git"

    def test_builder_shell_runs_in_the_os_sandbox(self):
        task, git_dir = self.sandboxed(network=["registry.npmjs.org"], sandbox_writes=["/cache"])
        sb = settings_for(task, POLICIES["builder"])["sandbox"]
        self.assertEqual((sb["enabled"], sb["failIfUnavailable"], sb["allowUnsandboxedCommands"]), (True, True, False))
        self.assertIn("~/.ssh", sb["filesystem"]["denyRead"])
        self.assertEqual(sb["network"]["allowedDomains"], ["registry.npmjs.org"])
        writes = sb["filesystem"]["allowWrite"]
        self.assertIn(str(self.worktree), writes)
        self.assertIn(str(git_dir / "refs" / "heads" / "puxirum"), writes, "only its own branch's refs")
        self.assertIn("/cache", writes)
        for never in ("hooks", "config", "refs"):
            self.assertNotIn(str(git_dir / never), writes)
        self.assertFalse(any(w in (str(git_dir), str(git_dir.parent)) for w in writes))

    def test_sandbox_is_for_the_builder_and_can_be_turned_off(self):
        task, _ = self.sandboxed()
        self.assertNotIn("sandbox", settings_for(self.task(), POLICIES["builder"]))
        reviewer = AgentTask(
            "reviewer", "code", "001-x", "haiku", self.worktree, self.job_dir, self.job_dir / "r.md", dict(task.vars)
        )
        self.assertNotIn("sandbox", settings_for(reviewer, POLICIES["reviewer"]))

    def test_no_role_may_read_secrets_with_its_tools(self):
        for role in POLICIES:
            deny = self.rules(self.task(role, lens="code" if role == "reviewer" else None))["deny"]
            self.assertIn("Read(~/.ssh/**)", deny, role)

    def test_absolute_rules_use_a_double_slash(self):
        rules = self.rules(self.task())
        self.assertTrue(all(r.split("(", 1)[1].startswith("//") for r in rules["allow"] if "(/" in r))

    # ---- environment ----------------------------------------------------------------------------

    def test_agent_has_no_forge_credentials(self):
        _, rec = self.run_fake()
        env = rec["env"]
        for gone in ("SSH_AUTH_SOCK", "GH_TOKEN", "TUIOS_SESSION", "TUIOS_PANE_ID"):
            self.assertNotIn(gone, env)
        self.assertEqual(env["HOME_KEEP"], "yes")
        self.assertEqual((env["GIT_SSH_COMMAND"], env["GIT_TERMINAL_PROMPT"]), ("false", "0"))
        self.assertEqual(list(Path(env["GH_CONFIG_DIR"]).iterdir()), [])
        self.assertEqual((env["PUXIRUM_JOB"], env["PUXIRUM_ROLE"], env["PUXIRUM_PORT"]), ("001-x", "builder", "5200"))

    def test_git_cannot_push_over_ssh_or_use_stored_credentials(self):
        env = agent_env(self.task())
        start = time.monotonic()
        res = subprocess.run(
            ["git", "ls-remote", "git@github.com:octocat/Hello-World.git"],
            env=env,
            capture_output=True,
            text=True,
            cwd=self.worktree,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertLess(time.monotonic() - start, 10, "fails at once, without touching the network")
        res = subprocess.run(
            ["git", "config", "--get-all", "credential.helper"],
            env=env,
            capture_output=True,
            text=True,
            cwd=self.worktree,
        )
        self.assertEqual(res.stdout.strip().splitlines()[-1:] or [""], [""], "the last helper is the empty reset")

    # ---- results --------------------------------------------------------------------------------

    def test_success_reports_cost(self):
        result, _ = self.run_fake()
        self.assertEqual((result.exit_code, result.cost_usd), (0, 0.123))
        self.assertEqual(json.loads(result.log.read_text())["num_turns"], 3)

    def test_errors(self):
        for mode, code, cost in (("fail", 1, 0.2), ("is_error", 1, 0.1), ("garbage", 1, None)):
            with self.subTest(mode=mode):
                result, _ = self.run_fake(mode=mode)
                self.assertEqual((result.exit_code, result.cost_usd), (code, cost))

    def test_timeout_stops_the_agent(self):
        start = time.monotonic()
        result, _ = self.run_fake(mode="sleep", timeout_s=0.5)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(result.exit_code, 124)
        self.assertIn("timeout", (self.job_dir / "logs" / "builder-r1-a1.err").read_text())

    def test_nothing_the_agent_started_outlives_it(self):
        pidfile = self.job_dir / "child.pid"
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_PID": str(pidfile)}):
            result, _ = self.run_fake(mode="child")
        self.assertEqual(result.exit_code, 0)
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_logs_are_per_role_round_and_attempt(self):
        self.run_fake(self.task("reviewer", "ux", "round-2/review-ux.md", round=2, attempt=2))
        self.assertTrue((self.job_dir / "logs" / "reviewer-ux-r2-a2.json").exists())


if __name__ == "__main__":
    unittest.main()
