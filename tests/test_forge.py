import json
import unittest

from puxirum.forge import FakeForge, ForgeError, GhForge


class FakeForgeTest(unittest.TestCase):
    def test_issues_labels_and_prs(self):
        f = FakeForge()
        a = f.add_issue("A")
        f.add_issue("B", labels=())
        self.assertEqual([i.number for i in f.list_issues("puxirum")], [a.number])
        f.set_labels(a.number, ["x"], ["puxirum"])
        f.set_labels(a.number, ["x"], ["puxirum"])
        self.assertEqual(f.issue(a.number).labels, ["x"])
        pr = f.create_pr("b", "main", "t", "body", draft=True)
        self.assertEqual(f.find_prs("b"), [pr])
        f.mark_ready(pr.number)
        f.merge_pr(pr.number, "squash")
        self.assertEqual((pr.draft, pr.state), (False, "MERGED"))
        self.assertEqual(f.find_prs("b"), [])
        with self.assertRaises(ForgeError):
            f.merge_pr(pr.number, "squash")
        f.close_pr(pr.number)
        self.assertEqual(pr.state, "MERGED", "closing a merged PR does nothing")

    def test_injected_failure_happens_once(self):
        f = FakeForge()
        a = f.add_issue("A")
        f.fail["comment"] = ForgeError("down")
        with self.assertRaises(ForgeError):
            f.comment("issue", a.number, "x")
        f.comment("issue", a.number, "x")
        self.assertEqual(len(f.issue(a.number).comments), 1)


class GhForgeTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.replies = {}

    def run_gh(self, args):
        self.calls.append(args)
        for prefix, reply in self.replies.items():
            if " ".join(args).startswith(prefix):
                return reply() if callable(reply) else reply
        return ""

    def issue_json(self, labels):
        return json.dumps(
            {
                "number": 3,
                "title": "T",
                "body": None,
                "author": {"login": "ana"},
                "url": "u",
                "state": "OPEN",
                "labels": [{"name": n} for n in labels],
                "comments": [{"author": {"login": "bob"}, "body": "hi", "createdAt": "2026-01-01T00:00:00Z"}],
            }
        )

    def test_issue_parsing(self):
        self.replies["issue view 3"] = self.issue_json(["puxirum"])
        i = GhForge(run=self.run_gh).issue(3)
        self.assertEqual((i.author, i.body, i.labels), ("ana", "", ["puxirum"]))
        self.assertEqual(i.comments[0].author, "bob")

    def test_set_labels_only_sends_the_difference(self):
        self.replies["issue view 3"] = self.issue_json(["puxirum", "old"])
        g = GhForge(run=self.run_gh)
        g.set_labels(3, ["puxirum", "new"], ["old", "absent"])
        self.assertEqual(self.calls[-1], ["issue", "edit", "3", "--add-label", "new", "--remove-label", "old"])
        self.calls.clear()
        g.set_labels(3, ["puxirum"], ["absent"])
        self.assertEqual([c[:2] for c in self.calls], [["issue", "view"]], "nothing to change, no edit")

    def test_create_pr_reads_back_the_single_open_pr(self):
        pr = {
            "number": 9,
            "url": "u",
            "headRefName": "puxirum/001-x",
            "baseRefName": "main",
            "title": "t",
            "body": "b",
            "state": "OPEN",
            "isDraft": True,
            "comments": [],
        }
        self.replies["pr list"] = json.dumps([pr])
        got = GhForge(run=self.run_gh).create_pr("puxirum/001-x", "main", "t", "b", draft=True)
        self.assertEqual(got.number, 9)
        self.assertIn("--draft", self.calls[0])
        self.replies["pr list"] = json.dumps([pr, {**pr, "number": 10}])
        with self.assertRaises(ForgeError):
            GhForge(run=self.run_gh).create_pr("puxirum/001-x", "main", "t", "b", draft=True)

    def test_ready_and_close_check_state_first(self):
        pr = {"number": 9, "url": "u", "headRefName": "h", "baseRefName": "main", "state": "MERGED", "isDraft": False}
        self.replies["pr view 9"] = json.dumps(pr)
        g = GhForge(run=self.run_gh)
        g.mark_ready(9)
        g.close_pr(9)
        self.assertEqual([c[:2] for c in self.calls], [["pr", "view"], ["pr", "view"]])

    def test_operator_is_cached(self):
        self.replies["api user"] = "dev\n"
        g = GhForge(run=self.run_gh)
        self.assertEqual((g.operator(), g.operator()), ("dev", "dev"))
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
