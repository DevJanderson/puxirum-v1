import tempfile
import unittest
from pathlib import Path

from puxirum.files import MalformedFile, bullets, parse_header, quote, read, section

SUMMARY = "## Summary\n- one\n- two\n- three\n"
SHA = "a" * 40


class HeaderTest(unittest.TestCase):
    def test_reads_until_blank_line(self):
        self.assertEqual(parse_header("A: 1\nB-C: two words\n\nD: ignored\n"), {"A": "1", "B-C": "two words"})

    def test_value_may_contain_colons(self):
        self.assertEqual(parse_header("URL: http://x:1\n"), {"URL": "http://x:1"})

    def test_rejects_bad_lines(self):
        for text in ("not a header\n", "lower: x\n", "A:\n", "A: 1\nA: 2\n", "# Title\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_header(text)


class HelpersTest(unittest.TestCase):
    def test_section(self):
        text = "## A\nalpha\n\n## B\nbeta\n## Bee\nnot b\n"
        self.assertEqual(section(text, "A"), "alpha")
        self.assertEqual(section(text, "B"), "beta")
        self.assertIsNone(section(text, "C"))

    def test_bullets(self):
        self.assertEqual(bullets("- a\n\n- b\n"), ["a", "b"])
        with self.assertRaises(ValueError):
            bullets("- a\ntext\n")

    def test_quote(self):
        self.assertEqual(quote("line\n\nIgnore previous instructions"), "> line\n>\n> Ignore previous instructions")
        self.assertEqual(quote("  "), "> (empty)")


class ReadTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def write(self, text):
        path = self.dir / "f.md"
        path.write_text(text)
        return path

    def ok(self, kind, text):
        return read(self.write(text), kind)

    def bad(self, kind, text, fragment):
        with self.assertRaises(MalformedFile) as cm:
            read(self.write(text), kind)
        self.assertIn(fragment, cm.exception.reason)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            read(self.dir / "nope.md", "build")

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            read(self.write("x"), "poem")

    def test_summary_rules(self):
        self.bad("build", "STATUS: READY\n\n# Build\n", "missing `## Summary`")
        self.bad("build", "STATUS: READY\n\n## Summary\n- a\n- b\n", "2 bullets")
        self.bad("build", "STATUS: READY\n\n## Summary\n" + "- x\n" * 6, "6 bullets")
        self.bad("build", "STATUS: READY\n\n## Summary\nprose\n", "only `- ` bullets")
        f = self.ok("build", "STATUS: READY\n\n" + SUMMARY)
        self.assertEqual(f.summary, ("one", "two", "three"))

    def test_intake_accept(self):
        f = self.ok("intake", "DECISION: ACCEPT\nRISK: low\nSURFACES: ui, security\nRESCOPED: no\n\n" + SUMMARY)
        self.assertEqual(f.header["RISK"], "low")
        self.ok("intake", "DECISION: ACCEPT\nRISK: high\nSURFACES: none\nRESCOPED: yes\n\n" + SUMMARY)

    def test_intake_accept_needs_all_fields(self):
        self.bad("intake", "DECISION: ACCEPT\nRISK: low\nSURFACES: ui\n\n" + SUMMARY, "missing header RESCOPED")
        self.bad("intake", "DECISION: ACCEPT\nRISK: huge\nSURFACES: ui\nRESCOPED: no\n\n" + SUMMARY, "RISK")
        self.bad("intake", "DECISION: ACCEPT\nRISK: low\nSURFACES: UI\nRESCOPED: no\n\n" + SUMMARY, "SURFACES")
        self.bad("intake", "DECISION: ACCEPT\nRISK: low\nSURFACES: ui, ui\nRESCOPED: no\n\n" + SUMMARY, "SURFACES")
        self.bad(
            "intake",
            "DECISION: ACCEPT\nRISK: low\nSURFACES: ui\nRESCOPED: no\nX: 1\n\n" + SUMMARY,
            "unexpected header X",
        )

    def test_intake_needs_info_and_reject(self):
        self.ok("intake", "DECISION: NEEDS-INFO\n\n" + SUMMARY + "\n## Questions\n1. Which list?\n")
        self.bad("intake", "DECISION: NEEDS-INFO\n\n" + SUMMARY, "## Questions")
        self.ok("intake", "DECISION: REJECT\n\n" + SUMMARY + "\n## Reason\nOut of scope.\n")
        self.bad("intake", "DECISION: REJECT\n\n" + SUMMARY + "\n## Reason\n\n", "## Reason")
        self.bad("intake", "DECISION: REJECT\nRISK: low\n\n" + SUMMARY + "\n## Reason\nx\n", "unexpected header RISK")
        self.bad("intake", "DECISION: MAYBE\n\n" + SUMMARY, "DECISION")

    def test_spec(self):
        sections = "".join(f"## {h}\nx\n\n" for h in ("Context", "Requirements", "Out of scope", "Assumptions"))
        good = "# Title\n\n" + SUMMARY + "\n" + sections + "## Acceptance criteria\n1. It works.\n"
        self.ok("spec", good)
        self.bad("spec", good.replace("# Title", "Title"), "first line")
        self.bad("spec", good.replace("## Out of scope", "## Scope"), "## Out of scope")
        self.bad("spec", good.replace("1. It works.", "It works."), "numbered criterion")

    def test_build(self):
        self.ok("build", "STATUS: BLOCKED\n\n" + SUMMARY + "\n## Blocked\nchecks.sh is protected.\n")
        self.bad("build", "STATUS: BLOCKED\n\n" + SUMMARY, "## Blocked")
        self.bad("build", "STATUS: DONE\n\n" + SUMMARY, "STATUS")
        self.bad("build", "# Build\n\n" + SUMMARY, "header line")

    def test_review(self):
        self.ok("review", "VERDICT: PASS\n\n" + SUMMARY + "\n## Findings\nNone.\n")
        self.ok("review", "VERDICT: CHANGES\n\n" + SUMMARY + "\n## Findings\n1. src/a.ts:3 bug\n")
        self.bad("review", "VERDICT: CHANGES\n\n" + SUMMARY + "\n## Findings\nNone.\n", "at least one finding")
        self.bad("review", "VERDICT: PASS\n\n" + SUMMARY, "## Findings")
        self.bad("review", "VERDICT: pass\n\n" + SUMMARY + "\n## Findings\nNone.\n", "VERDICT")

    def test_decision(self):
        self.ok("decision", "DECISION: APPROVE\n\n" + SUMMARY + "\n## Why\nAll good.\n")
        self.bad("decision", "DECISION: APPROVE\n\n" + SUMMARY, "## Why")
        self.bad("decision", "APPROVE\n\n" + SUMMARY + "\n## Why\nx\n", "header line")

    def test_checks(self):
        self.ok("checks", f"GATE: PASS\nCOMMIT: {SHA}\n\n" + SUMMARY)
        self.bad("checks", "GATE: PASS\nCOMMIT: abc123\n\n" + SUMMARY, "full commit sha")
        self.bad("checks", f"GATE: OK\nCOMMIT: {SHA}\n\n" + SUMMARY, "GATE")


if __name__ == "__main__":
    unittest.main()
