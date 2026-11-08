import copy
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from puxirum.config import Config
from puxirum.machine import STAGES, TERMINAL, TRANSITIONS, Refused, advance
from puxirum.store import Effect, Job

SUMMARY = "## Summary\n- one\n- two\n- three\n"
SHA1, SHA2 = "1" * 40, "2" * 40
SPEC = (
    "# Editar título\n\n"
    + SUMMARY
    + "\n## Context\nx\n\n## Requirements\nx\n\n## Acceptance criteria\n1. Works.\n\n## Out of scope\nx\n\n## Assumptions\nx\n"
)
INTAKE_ACCEPT = "DECISION: ACCEPT\nRISK: low\nSURFACES: ui\nRESCOPED: no\n\n" + SUMMARY
INTAKE_INFO = "DECISION: NEEDS-INFO\n\n" + SUMMARY + "\n## Questions\n1. Which?\n"
INTAKE_REJECT = "DECISION: REJECT\n\n" + SUMMARY + "\n## Reason\nNo.\n"
BUILD_READY = "STATUS: READY\n\n" + SUMMARY
BUILD_BLOCKED = "STATUS: BLOCKED\n\n" + SUMMARY + "\n## Blocked\nchecks.sh is protected.\n"


def checks(result, sha=SHA1):
    return f"GATE: {result}\nCOMMIT: {sha}\n\n" + SUMMARY


def review(verdict):
    findings = "None." if verdict == "PASS" else "1. a.ts:1 broken"
    return f"VERDICT: {verdict}\n\n" + SUMMARY + f"\n## Findings\n{findings}\n"


def decision(d):
    return f"DECISION: {d}\n\n" + SUMMARY + "\n## Why\nBecause.\n"


@dataclass
class FakeFacts:
    sha: str = SHA1
    clean: bool = True
    ahead: int = 1
    merged: bool = False
    replied: bool = True
    slot: bool = True

    def head(self):
        return self.sha

    def worktree_clean(self):
        return self.clean

    def commits_ahead(self):
        return self.ahead

    def pr_merged(self):
        return self.merged

    def author_replied(self):
        return self.replied

    def slot_available(self):
        return self.slot


class MachineTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.cfg = Config()
        self.facts = FakeFacts()

    def tearDown(self):
        self._dir.cleanup()

    # ---- helpers --------------------------------------------------------------

    def job(self, stage, **kw):
        base = dict(
            id="004-editar-titulo",
            issue=4,
            title="Editar título",
            branch="puxirum/004-editar-titulo",
            worktree=".worktrees/004-editar-titulo",
            stage=stage,
        )
        if stage not in ("intake", "needs-info"):
            base.update(reviewers={"code": "haiku", "ux": "sonnet"}, round=1, round_limit=3, head=SHA1)
        base.update(kw)
        return Job(**base)

    def write(self, name, text):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def go(self, job, target, **kw):
        return advance(job, target, cfg=self.cfg, job_dir=self.dir, facts=self.facts, **kw)

    def refused(self, job, target, fragment, **kw):
        with self.assertRaises(Refused) as cm:
            self.go(job, target, **kw)
        self.assertIn(fragment, str(cm.exception))

    def kinds(self, effects):
        return [e.kind for e in effects]

    # ---- legality -----------------------------------------------------------------

    def test_every_illegal_transition_is_refused(self):
        for old in STAGES:
            for target in STAGES:
                legal = target in TRANSITIONS[old] or (target == "merged" and old not in TERMINAL)
                if legal:
                    continue
                with self.subTest(old=old, target=target):
                    self.refused(self.job(old), target, "not a legal transition")

    def test_terminal_stages_have_no_moves(self):
        for stage in TERMINAL:
            self.assertEqual(TRANSITIONS[stage], frozenset())

    def test_unknown_stage(self):
        self.refused(self.job("intake"), "done", "unknown stage")

    def test_pending_effects_block_moves(self):
        self.write("intake.md", INTAKE_ACCEPT)
        job = self.job("intake", pending=[Effect(kind="push", key="k")])
        self.refused(job, "spec", "pending effect")

    def test_reason_only_for_escalation(self):
        with self.assertRaises(ValueError):
            self.go(self.job("spec"), "build", reason="x")

    def test_advance_is_pure(self):
        self.write("intake.md", INTAKE_ACCEPT)
        job = self.job("intake")
        before = copy.deepcopy(job)
        listing = sorted(self.dir.rglob("*"))
        new, _ = self.go(job, "spec")
        self.assertEqual(job, before, "the input job is not mutated")
        self.assertEqual(sorted(self.dir.rglob("*")), listing, "no file is written")
        self.assertEqual(new.seq, 1)

    def test_effect_keys_are_unique_and_tied_to_seq(self):
        self.write("intake.md", INTAKE_ACCEPT)
        _, effects = self.go(self.job("intake", seq=6), "spec")
        self.assertEqual([e.key for e in effects], [f"004-editar-titulo:7:{i}" for i in range(len(effects))])

    # ---- intake ---------------------------------------------------------------------

    def test_intake_accept(self):
        self.write("intake.md", INTAKE_ACCEPT)
        job, effects = self.go(self.job("intake"), "spec")
        self.assertEqual(job.stage, "spec")
        self.assertEqual(job.reviewers, {"code": "haiku", "ux": "sonnet", "ui": "haiku"})
        self.assertEqual(job.intake, {"decision": "ACCEPT", "risk": "low", "surfaces": ["ui"], "rescoped": False})
        self.assertEqual(self.kinds(effects), ["comment", "worktree_add"])
        self.assertEqual(effects[0].args["on"], "issue")
        self.assertIn("risk low, surfaces: ui", effects[0].args["body"])
        self.assertEqual(effects[1].args, {"path": job.worktree, "branch": job.branch, "base": "main"})
        self.assertIsNone(job.ended)

    def test_intake_proofs(self):
        self.refused(self.job("intake"), "spec", "intake.md doesn't exist")
        self.write("intake.md", INTAKE_INFO)
        self.refused(self.job("intake"), "spec", "not ACCEPT")
        self.write("intake.md", "DECISION: ACCEPT\n\n" + SUMMARY)
        self.refused(self.job("intake"), "spec", "malformed")
        self.write("intake.md", INTAKE_ACCEPT.replace("SURFACES: ui", "SURFACES: db"))
        self.refused(self.job("intake"), "spec", "can't be routed")

    def test_intake_needs_info(self):
        self.write("intake.md", INTAKE_INFO)
        job, effects = self.go(self.job("intake"), "needs-info")
        self.assertEqual((job.stage, job.questions), ("needs-info", 1))
        self.assertIsNotNone(job.ended)
        self.assertEqual(self.kinds(effects), ["comment", "labels"])
        self.assertEqual(effects[1].args["add"], ["puxirum:needs-info"])

    def test_intake_reject(self):
        self.write("intake.md", INTAKE_REJECT)
        job, effects = self.go(self.job("intake"), "rejected")
        self.assertEqual(job.stage, "rejected")
        self.assertEqual(self.kinds(effects), ["comment", "labels"], "no worktree to remove")
        self.assertEqual(effects[1].args["remove"], ["puxirum"])
        self.write("intake.md", INTAKE_ACCEPT)
        self.refused(self.job("intake"), "rejected", "not REJECT")

    def test_intake_escalates_only_with_reason(self):
        self.refused(self.job("intake"), "needs-human", "needs a reason")
        job, _ = self.go(self.job("intake"), "needs-human", reason="intake.md malformed twice")
        self.assertEqual(job.escalations[0]["from"], "intake")

    # ---- needs-info ---------------------------------------------------------------------

    def test_needs_info_resumes_after_reply(self):
        job = self.job("needs-info", questions=1, intake={"decision": "NEEDS-INFO"})
        self.facts.replied = False
        self.refused(job, "intake", "hasn't replied")
        self.facts.replied, self.facts.slot = True, False
        self.refused(job, "intake", "no free slot")
        self.facts.slot = True
        new, effects = self.go(job, "intake")
        self.assertEqual(new.stage, "intake")
        self.assertIsNone(new.intake)
        self.assertEqual(self.kinds(effects), ["archive", "refresh_issue", "labels"])
        self.assertEqual(effects[0].args, {"src": "intake.md", "dst": "intake-1.md"})

    # ---- spec and build -------------------------------------------------------------------

    def test_spec_starts_round_one(self):
        job = self.job("spec", round=0, round_limit=0)
        self.refused(job, "build", "spec.md doesn't exist")
        self.write("spec.md", SPEC.replace("1. Works.", "Works."))
        self.refused(job, "build", "malformed")
        self.write("spec.md", SPEC)
        new, effects = self.go(job, "build")
        self.assertEqual((new.round, new.round_limit, effects), (1, 3, []))

    def test_build_to_gate(self):
        self.write("spec.md", SPEC)
        job = self.job("build", head=None)
        self.write("build.md", BUILD_BLOCKED)
        self.refused(job, "gate", "not READY")
        self.write("build.md", BUILD_READY)
        self.facts.clean = False
        self.refused(job, "gate", "uncommitted")
        self.facts.clean, self.facts.ahead = True, 0
        self.refused(job, "gate", "no commits")
        self.facts.ahead = 2
        new, effects = self.go(job, "gate")
        self.assertEqual(new.head, SHA1)
        self.assertEqual(self.kinds(effects), ["push", "ensure_pr"])
        self.assertEqual(effects[1].args["title"], "Editar título")
        self.assertTrue(effects[1].args["body"].startswith("Closes #4\n"))
        _, effects = self.go(self.job("build", pr=12), "gate")
        self.assertEqual(self.kinds(effects), ["push"], "an existing PR updates with the push")

    def test_build_blocked_escalates(self):
        self.write("build.md", BUILD_BLOCKED)
        job, effects = self.go(self.job("build", pr=12), "needs-human")
        self.assertIn("checks.sh is protected", job.escalations[0]["reason"])
        self.assertEqual(self.kinds(effects), ["write_file", "pr_ready", "comment", "labels"])
        self.assertEqual(effects[0].args["name"], "escalation-1.md")
        self.assertEqual(effects[2].args["on"], "pr")
        self.write("build.md", BUILD_READY)
        self.refused(self.job("build"), "needs-human", "isn't BLOCKED")
        job, _ = self.go(self.job("build"), "needs-human", reason="the builder crashed twice")
        self.assertEqual(job.escalations[0]["reason"], "the builder crashed twice")

    # ---- gate ------------------------------------------------------------------------------

    def test_gate_pass(self):
        job = self.job("gate")
        self.refused(job, "review", "round-1/checks.md doesn't exist")
        self.write("round-1/checks.md", checks("PASS", SHA2))
        self.refused(job, "review", "checks.md is for 2222222")
        self.write("round-1/checks.md", checks("PASS"))
        self.facts.sha = SHA2
        self.refused(job, "review", "checks.md is for 1111111")
        self.facts.sha = SHA1
        new, _ = self.go(job, "review")
        self.assertEqual(new.gate, "PASS")
        self.assertEqual(new.reviews, {"code": "pending", "ux": "pending"})

    def test_gate_head_must_match_the_build(self):
        self.write("round-1/checks.md", checks("PASS", SHA2))
        self.facts.sha = SHA2
        self.refused(self.job("gate"), "review", "HEAD moved since the build")

    def test_gate_fail(self):
        self.write("round-1/checks.md", checks("FAIL"))
        self.refused(self.job("gate"), "review", "didn't pass")
        new, _ = self.go(self.job("gate"), "build")
        self.assertEqual((new.round, new.gate), (2, None))
        self.refused(self.job("gate"), "needs-human", "rounds remain")
        self.write("round-3/checks.md", checks("FAIL"))
        last = self.job("gate", round=3)
        self.refused(last, "build", "was the last")
        new, _ = self.go(last, "needs-human")
        self.assertIn("last allowed round", new.escalations[0]["reason"])

    # ---- review ------------------------------------------------------------------------------

    def test_review_needs_every_valid_review(self):
        job = self.job("review")
        self.write("round-1/review-code.md", review("PASS"))
        self.refused(job, "approve", "review-ux.md doesn't exist")
        self.write("round-1/review-ux.md", "VERDICT: PASS\n")
        self.refused(job, "approve", "review-ux.md is malformed")

    def test_review_pass(self):
        self.write("round-1/review-code.md", review("PASS"))
        self.write("round-1/review-ux.md", review("PASS"))
        new, _ = self.go(self.job("review"), "approve")
        self.assertEqual(new.reviews, {"code": "PASS", "ux": "PASS"})
        self.refused(self.job("review"), "build", "every review passed")
        self.facts.sha = SHA2
        self.refused(self.job("review"), "approve", "reviewers must not commit")

    def test_review_changes(self):
        self.write("round-1/review-code.md", review("PASS"))
        self.write("round-1/review-ux.md", review("CHANGES"))
        self.refused(self.job("review"), "approve", "want CHANGES: ux")
        new, _ = self.go(self.job("review"), "build")
        self.assertEqual(new.round, 2)
        self.refused(self.job("review"), "needs-human", "rounds remain")
        self.write("round-3/review-code.md", review("PASS"))
        self.write("round-3/review-ux.md", review("CHANGES"))
        new, _ = self.go(self.job("review", round=3), "needs-human")
        self.assertIn("ux", new.escalations[0]["reason"])

    # ---- approve and merging ------------------------------------------------------------------

    def test_approve(self):
        self.refused(self.job("approve"), "merging", "decision.md doesn't exist")
        self.write("decision.md", decision("APPROVE"))
        new, effects = self.go(self.job("approve"), "merging")
        self.assertEqual((new.stage, effects), ("merging", []))
        self.refused(self.job("approve"), "needs-human", "doesn't ESCALATE")
        self.facts.sha = SHA2
        self.refused(self.job("approve"), "merging", "HEAD moved")

    def test_approver_escalates(self):
        self.write("decision.md", decision("ESCALATE"))
        self.refused(self.job("approve"), "merging", "not APPROVE")
        new, _ = self.go(self.job("approve"), "needs-human")
        self.assertEqual(new.escalations[0]["reason"], "Because.")

    def test_merging_escalates_only_with_reason(self):
        self.refused(self.job("merging", pr=12), "needs-human", "needs a reason")
        new, _ = self.go(self.job("merging", pr=12), "needs-human", reason="conflict with main")
        self.assertEqual(new.stage, "needs-human")

    # ---- merged ---------------------------------------------------------------------------------

    def test_merged_needs_a_merged_pr(self):
        self.refused(self.job("merging"), "merged", "isn't merged")
        self.refused(self.job("merging", pr=12), "merged", "isn't merged")
        self.facts.merged = True
        new, effects = self.go(self.job("merging", pr=12), "merged")
        self.assertEqual(new.stage, "merged")
        self.assertIsNotNone(new.ended)
        self.assertEqual(self.kinds(effects), ["delete_remote_branch", "worktree_remove"])

    def test_merged_by_a_person_mid_round(self):
        self.facts.merged = True
        for stage in ("build", "gate", "review", "approve"):
            with self.subTest(stage=stage):
                new, _ = self.go(self.job(stage, pr=12), "merged")
                self.assertEqual(new.stage, "merged")
        _, effects = self.go(self.job("needs-human", pr=12), "merged")
        self.assertEqual(self.kinds(effects), ["delete_remote_branch", "labels", "worktree_remove"])
        self.assertEqual(effects[1].args["remove"], ["puxirum:needs-human"])

    # ---- needs-human -----------------------------------------------------------------------------

    def escalated(self, frm="review", **kw):
        return self.job(
            "needs-human",
            escalations=[{"from": frm, "round": 3, "reason": "x", "at": "t"}],
            round=3,
            round_limit=3,
            **kw,
        )

    def test_feedback_resumes_build_with_new_rounds(self):
        job = self.escalated()
        self.refused(job, "build", "send feedback first")
        self.write("feedback-1.md", "# Feedback 1\n\nUse option B.\n")
        self.refused(job, "spec", "resumes at build")
        self.facts.slot = False
        self.refused(job, "build", "no free slot")
        self.facts.slot = True
        new, effects = self.go(job, "build")
        self.assertEqual((new.stage, new.round, new.round_limit, new.feedback), ("build", 4, 6, 1))
        self.assertEqual(self.kinds(effects), ["labels"])
        self.assertEqual(effects[0].args["remove"], ["puxirum:needs-human"])
        self.refused(new.__class__(**{**new.__dict__, "stage": "needs-human"}), "build", "send feedback first")

    def test_feedback_resumes_intake_and_spec_where_they_failed(self):
        self.write("feedback-1.md", "# Feedback 1\n\nx\n")
        new, effects = self.go(self.escalated("intake"), "intake")
        self.assertEqual(new.stage, "intake")
        self.assertEqual(effects[0].args, {"src": "intake.md", "dst": "intake-h1.md"})
        new, _ = self.go(self.escalated("spec"), "spec")
        self.assertEqual((new.stage, new.round), ("spec", 3))

    def test_reject_waiting_job(self):
        job = self.escalated(pr=12)
        self.refused(job, "rejected", "puxirum reject")
        self.write("rejection.md", "REJECTED-BY: dev\n\nNot worth it.\n")
        new, effects = self.go(job, "rejected")
        self.assertEqual(new.stage, "rejected")
        self.assertEqual(
            self.kinds(effects), ["comment", "labels", "pr_close", "delete_remote_branch", "worktree_remove"]
        )
        self.assertIn("Not worth it.", effects[0].args["body"])
        self.assertEqual(effects[1].args["remove"], ["puxirum", "puxirum:needs-human"])

    def test_reject_needs_info_job(self):
        self.write("rejection.md", "REJECTED-BY: dev\n\nNo reply.\n")
        _, effects = self.go(self.job("needs-info"), "rejected")
        self.assertEqual(self.kinds(effects), ["comment", "labels"])
        self.assertEqual(effects[1].args["remove"], ["puxirum", "puxirum:needs-info"])

    def test_second_escalation_needs_second_feedback(self):
        self.write("feedback-1.md", "# Feedback 1\n\nx\n")
        job = self.job(
            "needs-human",
            round=4,
            round_limit=6,
            feedback=1,
            escalations=[
                {"from": "review", "round": 3, "reason": "x", "at": "t"},
                {"from": "build", "round": 4, "reason": "y", "at": "t"},
            ],
        )
        self.refused(job, "build", "send feedback first")
        self.write("feedback-2.md", "# Feedback 2\n\ny\n")
        new, _ = self.go(job, "build")
        self.assertEqual((new.feedback, new.round_limit), (2, 7))


if __name__ == "__main__":
    unittest.main()
