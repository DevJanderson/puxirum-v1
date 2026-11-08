import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from puxirum import cli
from puxirum.feed import Feed, describe
from puxirum.store import Store


def tool(name, **args):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": args}]}}


RESULT = {"type": "result", "is_error": False, "total_cost_usd": 0.0912, "duration_ms": 100_000}


class DescribeTest(unittest.TestCase):
    def test_tool_calls(self):
        wt = Path("/repo/.worktrees/007-x")
        self.assertEqual(
            describe(tool("Edit", file_path="/repo/.worktrees/007-x/src/list.ts"), wt), ["Edit src/list.ts"]
        )
        self.assertEqual(describe(tool("Read", file_path="/elsewhere/spec.md"), wt), ["Read /elsewhere/spec.md"])
        self.assertEqual(describe(tool("Bash", command="npm test\n  --silent")), ["$ npm test --silent"])
        self.assertEqual(describe(tool("Grep", pattern="TODO")), ["Grep TODO"])
        self.assertEqual(describe(tool("TodoWrite", todos=[])), ["TodoWrite"])
        long = describe(tool("Bash", command="x" * 500))[0]
        self.assertLessEqual(len(long), 90)
        self.assertTrue(long.endswith("…"))

    def test_text_and_tool_results_are_not_steps(self):
        text = {"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking aloud"}]}}
        self.assertEqual(describe(text), [])
        self.assertEqual(describe({"type": "user", "message": {"content": [{"type": "tool_result"}]}}), [])
        self.assertEqual(describe({"type": "system", "subtype": "init"}), [])

    def test_results(self):
        self.assertEqual(describe(RESULT), ["✓ done · US$ 0.09 · 1m40s"])
        failed = {"type": "result", "is_error": True, "subtype": "error_max_budget_usd", "total_cost_usd": 0.5}
        self.assertEqual(describe(failed), ["✗ error_max_budget_usd · US$ 0.50 · 0m00s"])
        denied = {**RESULT, "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "git push"}}]}
        self.assertEqual(describe(denied)[0], "⛔ denied Bash git push")


class FeedTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.repo = Path(self._dir.name)
        self.store = Store(self.repo)
        with self.store.lock():
            self.job = self.store.create(7, "Add dark mode", "puxirum/", ".worktrees")
        self.logs = self.store.job_dir(self.job.id) / "logs"
        self.logs.mkdir()

    def tearDown(self):
        self._dir.cleanup()

    def feed(self):
        return Feed(self.store, clock=lambda: 0)

    def write(self, name, *events, partial=""):
        with open(self.logs / name, "a") as f:
            f.write("".join(json.dumps(e) + "\n" for e in events) + partial)

    def text(self, lines):
        return [re.split(r"\s{2,}", line)[-1] for line in lines]

    def test_follows_new_steps_with_a_label(self):
        self.write("builder-r2-a1.jsonl", {"type": "system"})
        feed = self.feed()
        self.assertEqual(feed.poll(), [])
        self.write("builder-r2-a1.jsonl", tool("Bash", command="npm test"))
        (line,) = feed.poll()
        self.assertIn("#7 builder r2", line)
        self.assertTrue(line.endswith("$ npm test"))
        self.assertEqual(feed.poll(), [], "each step once")

    def test_paths_are_relative_to_the_job_the_worktree_or_the_repo(self):
        feed = self.feed()
        job_dir = self.store.job_dir(self.job.id)
        self.write(
            "intake-r0-a1.jsonl",
            tool("Read", file_path=f"{job_dir}/issue.md"),
            tool("Read", file_path=f"{self.repo}/calc.py"),
            tool("Edit", file_path=f"{self.repo}/{self.job.worktree}/calc.py"),
        )
        self.assertEqual(self.text(feed.poll()), ["Read issue.md", "Read calc.py", "Edit calc.py"])

    def test_reviewer_lenses_and_parallel_agents(self):
        feed = self.feed()
        self.write("reviewer-ux-r1-a1.jsonl", tool("Read", file_path="spec.md"))
        self.write("reviewer-code-r1-a2.jsonl", RESULT)
        lines = feed.poll()
        self.assertTrue(any("#7 reviewer:ux r1" in line for line in lines))
        self.assertTrue(any("#7 reviewer:code r1" in line and "✓ done" in line for line in lines))

    def test_finished_agents_are_history_but_running_ones_are_shown_from_the_start(self):
        self.write("spec-r0-a1.jsonl", tool("Read", file_path="intake.md"), RESULT)
        self.write("builder-r1-a1.jsonl", tool("Read", file_path="spec.md"))
        self.assertEqual(self.text(self.feed().poll()), ["Read spec.md"])

    def test_a_line_cut_off_mid_write_waits_until_it_is_whole(self):
        feed = self.feed()
        whole = json.dumps(tool("Edit", file_path="a.py"))
        self.write("builder-r1-a1.jsonl", partial=whole[:20])
        self.assertEqual(feed.poll(), [])
        self.write("builder-r1-a1.jsonl", partial=whole[20:] + "\nnot json\n")
        self.assertEqual(self.text(feed.poll()), ["Edit a.py"])

    def test_each_step_fits_the_pane(self):
        self.write("builder-r1-a1.jsonl", tool("Bash", command="y" * 80))
        (line,) = Feed(self.store, clock=lambda: 0, width=lambda: 60).poll()
        self.assertLessEqual(len(line), 60)
        self.assertTrue(line.endswith("…"))

    def test_colour_only_when_asked(self):
        self.write("builder-r1-a1.jsonl", tool("Read", file_path="x"))
        self.assertNotIn("\x1b[", self.feed().poll()[0])
        self.assertIn("\x1b[", Feed(self.store, colour=True).poll()[0])

    def test_cli_once(self):
        self.write("builder-r1-a1.jsonl", tool("Read", file_path="spec.md"))

        class E:
            store = self.store

        out = io.StringIO()
        self.assertEqual(cli.main(["feed", "--once"], make_engine=lambda cwd: E, out=out), 0)
        self.assertIn("Read spec.md", out.getvalue())


if __name__ == "__main__":
    unittest.main()
