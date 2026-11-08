import unittest

from puxirum.config import parse
from puxirum.engine import Engine
from puxirum.forge import FakeForge, ForgeError
from puxirum.git import Git
from puxirum.machine import Refused
from puxirum.runner import FakeRunner
from puxirum.store import Store
from puxirum.world import World, marker

from tests import agents
from tests.gitrepo import Repos, git

CHECKS = "#!/usr/bin/env bash\nset -euo pipefail\nif [ -e bug.txt ]; then echo 'bug found' >&2; exit 1; fi\n"


class EngineBase(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.repo = self.r.main
        self.r.commit(self.repo, {
            ".gitignore": ".worktrees/\n.puxirum/state/\n",
            ".puxirum/checks.sh": CHECKS,
            ".puxirum/config.toml": "",
            "app.txt": "v1\n",
        }, "init")
        self.r.push_main()
        self.forge = FakeForge(operator="op")
        self.messages = []

    def tearDown(self):
        self.r.cleanup()

    def engine(self, scripts, **cfg):
        self.cfg = parse(cfg)
        self.store = Store(self.repo)
        self.world = World(self.repo, self.cfg, self.store, self.forge)
        self.runner = FakeRunner(scripts)
        return Engine(self.world, self.runner, log=self.messages.append)

    def issue(self, title="Editar título", author="ana"):
        return self.forge.add_issue(title, "Quero editar.", author=author).number

    def job(self, n):
        return self.store.find(n)

    def assertMerged(self, n):
        job = self.job(n)
        self.assertEqual(job.stage, "merged", f"{job.stage}: {job.escalations or job.last_error}\n" +
                         "\n".join(self.messages[-15:]))
        self.assertEqual(self.forge.pr(job.pr).state, "MERGED")
        self.assertFalse((self.repo / job.worktree).exists())
        self.assertFalse(Git(self.repo).remote_branch_exists(job.branch))
        self.assertEqual(job.pending, [])
        return job


class EngineTest(EngineBase):
    # ---- the whole pipeline ---------------------------------------------------------------------

    def test_happy_path(self):
        n = self.issue()
        e = self.engine(agents.happy())
        e.run()
        job = self.assertMerged(n)
        self.assertEqual(self.runner.names(), ["intake", "spec", "builder", "reviewer:code", "approver"])
        self.assertEqual((job.round, job.reviewers), (1, {"code": "haiku"}))
        self.assertAlmostEqual(job.cost_usd, 0.05)
        pr = self.forge.pr(job.pr)
        self.assertFalse(pr.draft)
        self.assertTrue(pr.body.startswith(f"Closes #{n}"))
        self.assertEqual(pr.title, "Feature")
        self.assertIn(("merge_pr", job.pr, "squash"), self.forge.calls)
        comments = self.forge.issue(n).comments
        self.assertEqual(len(comments), 1)
        self.assertIn("Puxirum intake: ACCEPT", comments[0].body)
        d = self.store.job_dir(job.id)
        for name in ("issue.md", "intake.md", "spec.md", "build.md", "decision.md", "round-1/checks.md",
                     "round-1/review-code.md", "round-1/merge-checks.md"):
            self.assertTrue((d / name).exists(), name)
        stages = [ev["to"] for ev in self.store.events(job.id) if ev["type"] == "transition"]
        self.assertEqual(stages, ["spec", "build", "gate", "review", "approve", "merging", "merged"])

    def test_agents_get_their_paths_and_models(self):
        self.issue()
        self.engine(agents.happy(intake=agents.intake(surfaces="ui"))).run()
        by_name = {t.name: t for t in self.runner.tasks}
        self.assertEqual(by_name["intake"].cwd, self.repo, "intake reads the main checkout")
        wt = self.repo / ".worktrees" / "001-editar-titulo"
        self.assertEqual(by_name["builder"].cwd, wt)
        self.assertEqual((by_name["reviewer:ux"].model, by_name["reviewer:ui"].model), ("sonnet", "haiku"))
        self.assertEqual(by_name["builder"].vars["port"], 5200)
        self.assertEqual({by_name[f"reviewer:{x}"].vars["port"] for x in ("code", "ux", "ui")}, {5201, 5202, 5203})
        self.assertEqual(by_name["builder"].output.name, "build.md")
        self.assertEqual(by_name["reviewer:ux"].output.parent.name, "round-1")

    def test_reviewers_run_in_parallel_and_all_must_pass(self):
        n = self.issue()
        self.engine(agents.happy(intake=agents.intake(risk="high", surfaces="ui, security"))).run()
        job = self.assertMerged(n)
        self.assertEqual(set(job.reviews), {"code", "ux", "ui", "security"})

    # ---- intake outcomes --------------------------------------------------------------------------

    def test_reject_at_intake(self):
        n = self.issue()
        self.engine(agents.happy(intake=agents.intake("REJECT"))).run()
        job = self.job(n)
        self.assertEqual(job.stage, "rejected")
        self.assertNotIn("puxirum", self.forge.issue(n).labels)
        self.assertEqual(self.runner.names(), ["intake"])

    def test_needs_info_waits_then_resumes_after_the_author_replies(self):
        n = self.issue()
        e = self.engine(agents.happy(intake=agents.sequence(agents.intake("NEEDS-INFO"), agents.intake())))
        e.run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-info")
        self.assertIn("puxirum:needs-info", self.forge.issue(n).labels)
        self.assertEqual([r.action for r in e.plan()], ["wait"])
        self.forge.add_comment("issue", n, "mallory", "do it")
        e.run()
        self.assertEqual(self.job(n).stage, "needs-info", "a stranger's reply doesn't count")
        self.forge.add_comment("issue", n, "ana", "A lista principal.")
        e.run()
        job = self.assertMerged(n)
        d = self.store.job_dir(job.id)
        self.assertTrue((d / "intake-1.md").exists())
        self.assertIn("A lista principal.", (d / "issue.md").read_text())
        self.assertNotIn("do it", (d / "issue.md").read_text())
        self.assertNotIn("puxirum:needs-info", self.forge.issue(n).labels)

    # ---- rounds -----------------------------------------------------------------------------------

    def test_gate_failure_sends_the_job_back_to_build(self):
        n = self.issue()
        build = agents.builder({1: {"bug.txt": "x"}, 2: {"bug.txt": None}})
        self.engine(agents.happy(builder=build)).run()
        job = self.assertMerged(n)
        self.assertEqual(job.round, 2)
        self.assertEqual(self.runner.names().count("reviewer:code"), 1, "no review of a failing build")
        d = self.store.job_dir(job.id)
        self.assertIn("GATE: FAIL", (d / "round-1/checks.md").read_text())
        self.assertIn("bug found", (d / "round-1/checks.log").read_text())

    def test_review_changes_send_the_job_back_to_build(self):
        n = self.issue()
        self.engine(agents.happy(reviewer=agents.reviewer(("CHANGES", "PASS")))).run()
        job = self.assertMerged(n)
        self.assertEqual(job.round, 2)
        self.assertEqual(self.runner.names().count("builder"), 2)

    def test_rounds_run_out_then_feedback_grants_new_ones(self):
        n = self.issue()
        e = self.engine(agents.happy(reviewer=agents.reviewer(("CHANGES", "CHANGES", "CHANGES", "PASS"))))
        e.run()
        job = self.job(n)
        self.assertEqual((job.stage, job.round), ("needs-human", 3))
        self.assertIn("Reviewers still want changes", job.escalations[0]["reason"])
        self.assertIn("puxirum:needs-human", self.forge.issue(n).labels)
        self.assertFalse(self.forge.pr(job.pr).draft, "an escalated PR is marked ready for a person")
        self.assertTrue((self.store.job_dir(job.id) / "escalation-1.md").exists())
        e.feedback(n, "Use the simpler layout.")
        e.run()
        job = self.assertMerged(n)
        self.assertEqual((job.round, job.round_limit), (4, 6))
        self.assertEqual(self.runner.tasks[-3].vars["feedback"], str(self.store.job_dir(job.id) / "feedback-1.md"))

    def test_blocked_builder_escalates(self):
        n = self.issue()
        self.engine(agents.happy(builder=agents.builder(status="BLOCKED"))).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("Needs a product decision", job.escalations[0]["reason"])

    def test_approver_escalates(self):
        n = self.issue()
        self.engine(agents.happy(approver=agents.approver("ESCALATE"))).run()
        self.assertEqual(self.job(n).stage, "needs-human")

    # ---- agents that misbehave -------------------------------------------------------------------

    def test_malformed_file_makes_the_agent_run_again(self):
        def bad(task):
            task.output.write_text("DECISION: ACCEPT\n")
        n = self.issue()
        self.engine(agents.happy(intake=agents.sequence(bad, agents.intake()))).run()
        job = self.assertMerged(n)
        self.assertEqual(self.runner.names()[:2], ["intake", "intake"])
        self.assertTrue((self.store.job_dir(job.id) / "intake.invalid-1.md").exists())
        self.assertEqual(self.runner.tasks[1].vars["retry"], "intake.md: missing header RISK")

    def test_agent_that_keeps_failing_escalates(self):
        n = self.issue()
        self.engine(agents.happy(builder=lambda task: 1)).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("builder agent failed 2 times", job.escalations[0]["reason"])
        self.assertIn("exited with 1", job.escalations[0]["reason"])
        self.assertEqual(self.runner.names().count("builder"), 2)

    def test_a_stale_output_file_is_not_accepted(self):
        n = self.issue()
        first = agents.builder()
        calls = {"n": 0}

        def build(task):
            calls["n"] += 1
            if calls["n"] == 1:
                return first(task)
            # later rounds commit but leave round 1's build.md in place
            agents.commit(task.cwd, {"more.txt": str(calls["n"])}, "more")
        self.engine(agents.happy(builder=build, reviewer=agents.reviewer(("CHANGES", "PASS")))).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("didn't write build.md", job.escalations[0]["reason"])

    def test_builder_leaving_uncommitted_work_is_retried(self):
        def sloppy(task):
            agents.builder()(task)
            (task.cwd / "scratch.txt").write_text("x")
        def tidy(task):
            (task.cwd / "scratch.txt").unlink()
            task.output.write_text("STATUS: READY\n\n" + agents.SUMMARY)
        n = self.issue()
        self.engine(agents.happy(builder=agents.sequence(sloppy, tidy))).run()
        self.assertMerged(n)
        self.assertIn("uncommitted", self.runner.tasks[3].vars["retry"])

    def test_reviewer_that_commits_escalates(self):
        def meddling(task):
            agents.commit(task.cwd, {"sneaky.txt": "x"}, "review fix")
            agents.reviewer()(task)
        n = self.issue()
        self.engine(agents.happy(reviewer=meddling)).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("reviewers must not commit", job.escalations[0]["reason"])

    def test_agent_crash_resumes_in_a_new_engine(self):
        def crash(task):
            agents.commit(task.cwd, {"half.txt": "x"}, "half")
            raise KeyboardInterrupt
        n = self.issue()
        with self.assertRaises(KeyboardInterrupt):
            self.engine(agents.happy(builder=crash)).run()
        self.assertEqual(self.job(n).stage, "build")
        self.engine(agents.happy()).run()
        job = self.assertMerged(n)
        self.assertEqual(job.attempts[f"builder@{job.seq - 5}"], 2)

    # ---- merging ------------------------------------------------------------------------------------

    def test_conflict_with_main_escalates(self):
        def approve_then_main_moves(task):
            agents.approver()(task)
            self.r.commit(self.repo, {"feature-1.txt": "main's version\n"}, "main moved")
            self.r.push_main()
        n = self.issue()
        self.engine(agents.happy(approver=approve_then_main_moves)).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("conflicts with main", job.escalations[0]["reason"])
        self.assertEqual(self.forge.pr(job.pr).state, "OPEN")

    def test_gate_failure_after_syncing_escalates(self):
        def approve_then_main_breaks(task):
            agents.approver()(task)
            self.r.commit(self.repo, {"bug.txt": "x"}, "main broke")
            self.r.push_main()
        n = self.issue()
        self.engine(agents.happy(approver=approve_then_main_breaks)).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("merge-checks.md", job.escalations[0]["reason"])

    def test_merge_refused_by_the_forge_escalates(self):
        n = self.issue()
        self.forge.fail["merge_pr"] = ForgeError("required status checks")
        self.engine(agents.happy()).run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("required status checks", job.escalations[0]["reason"])

    def test_a_person_merging_the_pr_finishes_the_job(self):
        n = self.issue()
        e = self.engine(agents.happy(approver=agents.approver("ESCALATE")))
        e.run()
        job = self.job(n)
        self.forge.mark_ready(job.pr)
        self.forge.merge_pr(job.pr, "merge")
        e.run()
        self.assertMerged(n)
        self.assertNotIn("puxirum:needs-human", self.forge.issue(n).labels)

    # ---- effects ---------------------------------------------------------------------------------------

    def test_a_failing_effect_is_retried_on_the_next_run(self):
        n = self.issue()
        self.forge.fail["create_pr"] = ForgeError("rate limited")
        self.engine(agents.happy()).run()
        job = self.assertMerged(n)
        failed = [ev for ev in self.store.events(job.id) if ev["type"] == "effect-failed"]
        self.assertEqual([ev["kind"] for ev in failed], ["ensure_pr"])
        self.assertEqual([c[0] for c in self.forge.calls].count("create_pr"), 1)

    def test_an_effect_that_keeps_failing_escalates(self):
        n = self.issue()

        def down(*a, **k):
            raise ForgeError("forge is down")
        e = self.engine(agents.happy(), queue={"effect_attempts": 2})
        self.forge.create_pr = down
        e.run()
        e.run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("forge is down", job.escalations[0]["reason"])
        types = [ev["type"] for ev in self.store.events(job.id)]
        self.assertIn("effect-abandoned", types)

    # ---- people --------------------------------------------------------------------------------------------

    def test_reject_an_escalated_job(self):
        n = self.issue()
        e = self.engine(agents.happy(builder=agents.builder(status="BLOCKED")))
        e.run()
        with self.assertRaises(ValueError):
            e.reject(n, " ")
        e.reject(n, "Not worth it.")
        job = self.job(n)
        self.assertEqual(job.stage, "rejected")
        labels = self.forge.issue(n).labels
        self.assertNotIn("puxirum", labels)
        self.assertNotIn("puxirum:needs-human", labels)
        self.assertIn("Not worth it.", self.forge.issue(n).comments[-1].body)
        self.assertFalse((self.repo / job.worktree).exists())

    def test_feedback_and_reject_only_apply_to_waiting_jobs(self):
        n = self.issue()
        e = self.engine(agents.happy(intake=agents.intake("NEEDS-INFO")))
        e.run()
        with self.assertRaises(Refused):
            e.feedback(n, "x")
        e.reject(n, "No reply in a month.")
        self.assertEqual(self.job(n).stage, "rejected")
        with self.assertRaises(Refused):
            e.reject(n, "again")

    def test_escalated_intake_resumes_at_intake(self):
        n = self.issue()
        e = self.engine(agents.happy(intake=lambda task: 2))
        e.run()
        job = self.job(n)
        self.assertEqual((job.stage, job.escalations[0]["from"]), ("needs-human", "intake"))
        self.runner.scripts["intake"] = agents.intake()
        e.feedback(n, "The issue is clear; accept it.")
        self.assertEqual(self.job(n).stage, "intake")
        e.run()
        self.assertMerged(n)

    # ---- the queue -------------------------------------------------------------------------------------------

    def test_concurrency_one_finishes_a_job_before_starting_the_next(self):
        a, b = self.issue("First"), self.issue("Second")
        e = self.engine(agents.happy())
        self.assertEqual([r.action for r in e.plan()], ["new", "hold"])
        e.run()
        self.assertMerged(a)
        self.assertMerged(b)
        jobs = [t.job_id for t in self.runner.tasks]
        self.assertEqual(jobs, sorted(jobs), "every task of the first job ran before the second job's")

    def test_waiting_jobs_do_not_hold_a_slot(self):
        a, b = self.issue("First"), self.issue("Second")
        e = self.engine(agents.happy(intake=agents.sequence(agents.intake("NEEDS-INFO"), agents.intake())))
        e.run()
        self.assertEqual(self.job(a).stage, "needs-info")
        self.assertMerged(b)

    def test_concurrency_two_runs_jobs_side_by_side(self):
        a, b = self.issue("First"), self.issue("Second")
        e = self.engine(agents.happy(), queue={"concurrency": 2})
        self.assertEqual([r.action for r in e.plan()], ["new", "new"])
        e.run()
        self.assertMerged(a)
        self.assertMerged(b)

    def test_closed_or_unlabeled_issues_are_skipped(self):
        a = self.issue()
        e = self.engine(agents.happy(builder=agents.builder(status="BLOCKED")))
        e.run()
        self.forge.issue(a).state = "CLOSED"
        rows = e.plan()
        self.assertEqual([(r.action, r.issue) for r in rows], [("skip", a)])
        self.assertIn("closed", rows[0].note)
        self.forge.add_issue("Unlabeled", labels=())
        self.assertEqual(len(e.plan()), 1)

    def test_run_one_issue(self):
        a, b = self.issue("First"), self.issue("Second")
        e = self.engine(agents.happy(), queue={"concurrency": 2})
        e.run(only=b)
        self.assertMerged(b)
        self.assertEqual(self.store.all()[0].issue, b)
        self.assertEqual(len(self.store.all()), 1, f"#{a} wasn't started")

    def test_comments_are_marked_and_issue_md_hides_markers(self):
        n = self.issue()
        e = self.engine(agents.happy(intake=agents.sequence(agents.intake("NEEDS-INFO"), agents.intake())))
        e.run()
        job = self.job(n)
        body = self.forge.issue(n).comments[0].body
        self.assertTrue(body.startswith(marker(f"{job.id}:1:0")))
        self.forge.add_comment("issue", n, "ana", "ok")
        e.run()
        self.assertNotIn("<!--", (self.store.job_dir(job.id) / "issue.md").read_text())


if __name__ == "__main__":
    unittest.main()


class AppTest(EngineBase):
    """The core runs the dev server for the agents that must see the app."""

    def app_engine(self, scripts, **cfg):
        import socket
        import sys
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1] // 10 * 10
        cfg.setdefault("app", {"command": [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"],
                               "ready_timeout_s": 10})
        cfg.setdefault("ports", {"base": min(base, 64000), "step": 10})
        return self.engine(scripts, **cfg)

    def looks(self, lens, shots=True, verdict="PASS"):
        """A UI reviewer that opens the app and saves a screenshot."""
        import urllib.request

        def run(task):
            url = task.vars["app_url"]
            port = int(url.rsplit(":", 1)[1])
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
            self.seen.append((task.name, url))
            if shots:
                evidence = task.job_dir / f"round-{task.vars['round']}" / "evidence"
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / f"{lens}-375.png").write_bytes(b"\x89PNG")
            agents.reviewer((verdict,))(task)
        return run

    def setUp(self):
        super().setUp()
        self.seen = []

    def ui_scripts(self, **kw):
        return agents.happy(intake=agents.intake(surfaces="ui"), **{
            "reviewer:ux": self.looks("ux"), "reviewer:ui": self.looks("ui"), **kw})

    def test_ui_reviewers_and_builder_get_a_running_app(self):
        n = self.issue()
        seen_builder = []

        def build(task):
            seen_builder.append(task.vars.get("app_url"))
            agents.builder()(task)
        e = self.app_engine(self.ui_scripts(builder=build))
        e.run()
        job = self.assertMerged(n)
        self.assertEqual(sorted(name for name, _ in self.seen), ["reviewer:ui", "reviewer:ux"])
        self.assertEqual(len({url for _, url in self.seen}), 2, "each reviewer gets its own port")
        self.assertTrue(seen_builder[0].startswith("http://localhost:"))
        code = [t for t in self.runner.tasks if t.name == "reviewer:code"][0]
        self.assertNotIn("app_url", code.vars, "the code reviewer doesn't need the app")
        from puxirum import servers
        for _, url in self.seen:
            self.assertFalse(servers.listening(int(url.rsplit(":", 1)[1])), "servers are stopped afterwards")
        self.assertTrue((self.store.job_dir(job.id) / "logs").glob("app-reviewer-ux-r1.log"))

    def test_a_pass_without_screenshots_is_not_accepted(self):
        n = self.issue()
        e = self.app_engine(self.ui_scripts(**{"reviewer:ux": self.looks("ux", shots=False)}))
        e.run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("PASS without screenshots", job.escalations[0]["reason"])
        self.assertEqual(self.runner.names().count("reviewer:ux"), 2)

    def test_screenshots_on_the_second_try_are_accepted(self):
        n = self.issue()
        e = self.app_engine(self.ui_scripts(**{"reviewer:ux": agents.sequence(self.looks("ux", shots=False),
                                                                           self.looks("ux"))}))
        e.run()
        self.assertMerged(n)
        ux = [t for t in self.runner.tasks if t.name == "reviewer:ux"]
        self.assertEqual(len(ux), 2)
        self.assertIn("without screenshots", ux[1].vars["retry"])

    def test_an_app_that_does_not_start_escalates_with_its_log(self):
        n = self.issue()
        e = self.app_engine(self.ui_scripts(), app={"command": ["false", "{port}"], "ready_timeout_s": 5})
        e.run()
        job = self.job(n)
        self.assertEqual(job.stage, "needs-human")
        self.assertIn("the app didn't start for the builder agent", job.escalations[0]["reason"])
        self.assertEqual(self.runner.names().count("builder"), 0, "no agent runs without its app")

    def test_no_app_configured_means_no_server_and_no_evidence_rule(self):
        n = self.issue()
        self.engine(agents.happy(intake=agents.intake(surfaces="ui"))).run()
        self.assertMerged(n)
        self.assertFalse(any("app_url" in t.vars for t in self.runner.tasks))

    def test_a_ui_spec_without_edge_cases_is_sent_back(self):
        def thin_spec(task):
            task.output.write_text(agents.SPEC.format(title="T").replace("## Edge cases\n- Very long titles.\n", "## Edge cases\nNone.\n"))
        n = self.issue()
        self.app_engine(self.ui_scripts(spec=agents.sequence(thin_spec, agents.spec()))).run()
        self.assertMerged(n)
        self.assertIn("Edge cases", self.runner.tasks[2].vars["retry"])
