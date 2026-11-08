import tempfile
import unittest
from pathlib import Path

from puxirum import config
from puxirum.config import Config, ConfigError, parse


class ParseTest(unittest.TestCase):
    def test_empty_file_gives_defaults(self):
        self.assertEqual(parse({}), Config())

    def test_reads_every_table(self):
        c = parse(
            {
                "queue": {"label": "q", "needs_info_label": "q:i", "needs_human_label": "q:h", "concurrency": 3, "max_rounds": 5},
                "git": {"base": "trunk", "merge_method": "merge", "branch_prefix": "bot/", "worktrees_dir": "wt"},
                "gate": {"checks": "ci/checks.sh", "timeout_s": 60, "protected": ["ci/*"]},
                "ports": {"base": 6000, "step": 5},
                "models": {"builder": "opus"},
                "routing": {
                    "risk": {"low": {"code": "haiku"}, "medium": {"code": "sonnet"}, "high": {"code": "opus", "security": "opus"}},
                    "surfaces": {"ui": {"ux": "sonnet"}},
                },
                "prices": {"m": {"input": 1, "output": 2, "cache_write_5m": 1.25, "cache_write_1h": 2, "cache_read": 0.1}},
            }
        )
        self.assertEqual((c.queue_label, c.concurrency, c.max_rounds), ("q", 3, 5))
        self.assertEqual((c.base_branch, c.merge_method, c.branch_prefix, c.worktrees_dir), ("trunk", "merge", "bot/", "wt"))
        self.assertEqual((c.checks, c.gate_timeout_s, c.protected), ("ci/checks.sh", 60, ("ci/*",)))
        self.assertEqual((c.ports_base, c.ports_step), (6000, 5))
        self.assertEqual(c.models["builder"], "opus")
        self.assertEqual(c.models["intake"], "sonnet", "models merge over the defaults")
        self.assertEqual(c.risk_reviewers["high"], {"code": "opus", "security": "opus"})
        self.assertEqual(c.surface_reviewers, {"ui": {"ux": "sonnet"}}, "a given table replaces the default")
        self.assertEqual(c.prices["m"].cache_write_5m, 1.25)

    def assertRefused(self, data, fragment):
        with self.assertRaises(ConfigError) as cm:
            parse(data)
        self.assertIn(fragment, str(cm.exception))

    def test_refuses_unknown_keys_with_their_path(self):
        self.assertRefused({"queue": {"concurrancy": 2}}, "queue.concurrancy")
        self.assertRefused({"nope": {}}, "nope")
        self.assertRefused({"routing": {"risks": {}}}, "routing.risks")
        self.assertRefused({"models": {"reviewer": "x"}}, "models.reviewer")
        self.assertRefused({"routing": {"surfaces": {"ui": {"design": "x"}}}}, "routing.surfaces.ui.design")
        p = {"input": 1, "output": 1, "cache_write_5m": 1, "cache_write_1h": 1, "cache_read": 1, "extra": 1}
        self.assertRefused({"prices": {"m": p}}, "prices.m.extra")

    def test_refuses_wrong_types_and_ranges(self):
        self.assertRefused({"queue": {"concurrency": True}}, "queue.concurrency")
        self.assertRefused({"queue": {"concurrency": 0}}, "queue.concurrency")
        self.assertRefused({"queue": {"label": ""}}, "queue.label")
        self.assertRefused({"queue": "x"}, "queue")
        self.assertRefused({"git": {"merge_method": "octopus"}}, "git.merge_method")
        self.assertRefused({"git": {"worktrees_dir": "/tmp/wt"}}, "git.worktrees_dir")
        self.assertRefused({"git": {"worktrees_dir": "../wt"}}, "git.worktrees_dir")
        self.assertRefused({"git": {"branch_prefix": "bot"}}, "git.branch_prefix")
        self.assertRefused({"gate": {"protected": "x"}}, "gate.protected")
        self.assertRefused({"ports": {"base": 80}}, "ports.base")
        self.assertRefused({"prices": {"m": {"input": 1}}}, "prices.m.output")
        self.assertRefused({"prices": {"m": {"input": -1}}}, "prices.m.input")

    def test_risk_routing_must_cover_every_risk(self):
        self.assertRefused({"routing": {"risk": {"low": {"code": "haiku"}}}}, "medium, high")

    def test_labels_must_differ(self):
        self.assertRefused({"queue": {"label": "x", "needs_info_label": "x"}}, "must all differ")


class ProtectedTest(unittest.TestCase):
    def test_matches_patterns(self):
        c = Config()
        self.assertTrue(c.is_protected(".puxirum/checks.sh"))
        self.assertTrue(c.is_protected(".puxirum/roles/builder.md"))
        self.assertFalse(c.is_protected("src/main.ts"))
        self.assertFalse(c.is_protected(".puxirum/CHECKS.SH"), "matching is case-sensitive")


class LoadTest(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ConfigError) as cm:
            config.load(Path(d))
        self.assertIn("puxirum init", str(cm.exception))

    def test_bad_toml(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".puxirum").mkdir()
            (Path(d) / ".puxirum" / "config.toml").write_text("[queue\n")
            with self.assertRaises(ConfigError):
                config.load(Path(d))

    def test_loads_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".puxirum").mkdir()
            (Path(d) / ".puxirum" / "config.toml").write_text('[queue]\nconcurrency = 2\n')
            self.assertEqual(config.load(Path(d)).concurrency, 2)


if __name__ == "__main__":
    unittest.main()
