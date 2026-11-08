import io
import unittest

from puxirum import bootstrap, cli
from puxirum.config import Config, load
from puxirum.forge import FakeForge, ForgeError
from tests.gitrepo import Repos, git


class InitTest(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.repo = self.r.main
        self.r.commit(self.repo, {".gitignore": "node_modules/", "app.txt": "v1\n"}, "init")
        self.r.push_main()
        self.forge = FakeForge(operator="op")
        self.lines = []

    def tearDown(self):
        self.r.cleanup()

    def test_creates_files_labels_and_ignores(self):
        bootstrap.init(self.repo, self.forge, self.lines.append)
        self.assertEqual(load(self.repo), Config(), "the template parses to the defaults")
        checks = self.repo / ".puxirum/checks.sh"
        self.assertTrue(checks.stat().st_mode & 0o100)
        self.assertEqual((self.repo / ".gitignore").read_text(), "node_modules/\n.puxirum/state/\n.worktrees/\n")
        self.assertEqual(sorted(self.forge.repo_labels), ["puxirum", "puxirum:needs-human", "puxirum:needs-info"])
        self.assertTrue((self.repo / ".puxirum/roles").is_dir())

    def test_never_overwrites_and_is_repeatable(self):
        (self.repo / ".puxirum").mkdir()
        (self.repo / ".puxirum/checks.sh").write_text("npm test\n")
        bootstrap.init(self.repo, self.forge, self.lines.append)
        bootstrap.init(self.repo, self.forge, self.lines.append)
        self.assertEqual((self.repo / ".puxirum/checks.sh").read_text(), "npm test\n")
        self.assertIn("kept .puxirum/checks.sh (already exists)", self.lines)
        self.assertEqual((self.repo / ".gitignore").read_text().count(".worktrees/"), 1)
        self.assertEqual([c for c in self.forge.calls if c[0] == "create_label"].__len__(), 3)

    def test_the_template_checks_fail(self):
        bootstrap.init(self.repo, None, self.lines.append)
        res = __import__("subprocess").run(["bash", ".puxirum/checks.sh"], cwd=self.repo, capture_output=True)
        self.assertEqual(res.returncode, 1)


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.repo = self.r.main
        self.r.commit(self.repo, {"app.txt": "v1\n"}, "init")
        self.r.push_main()
        self.forge = FakeForge(operator="op")

    def tearDown(self):
        self.r.cleanup()

    def levels(self, which=lambda tool: f"/usr/bin/{tool}"):
        return {c.what: (c.level, c.detail) for c in bootstrap.doctor(self.repo, self.forge, which)}

    def test_fresh_repo_fails_with_hints(self):
        got = self.levels()
        self.assertEqual(got[".puxirum/config.toml"][0], "fail")
        self.assertIn("puxirum init", got[".puxirum/config.toml"][1])

    def test_after_init_only_the_checks_template_fails(self):
        bootstrap.init(self.repo, self.forge, lambda line: None)
        got = self.levels()
        failing = {k: v for k, v in got.items() if v[0] == "fail"}
        self.assertEqual(list(failing), [".puxirum/checks.sh"])
        self.assertIn("template", failing[".puxirum/checks.sh"][1])
        (self.repo / ".puxirum/checks.sh").write_text("npm test\n")
        self.assertFalse([k for k, v in self.levels().items() if v[0] == "fail"])
        self.assertEqual(self.levels()[".puxirum/checks.sh is committed"][0], "warn")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "puxirum")
        self.assertEqual(self.levels()[".puxirum/checks.sh is committed"][0], "ok")

    def test_missing_tools_and_offline_forge(self):
        bootstrap.init(self.repo, self.forge, lambda line: None)
        got = self.levels(which=lambda tool: None)
        self.assertEqual(got["gh CLI"][0], "fail")
        self.assertEqual(got["claude not found"][0], "warn")
        self.assertEqual(got["tuios not found"][0], "warn")
        self.assertEqual(got["builder sandbox"][0], "fail")
        self.assertEqual(self.levels()["builder sandbox"], ("ok", "bwrap and socat found"))

        def offline():
            raise ForgeError("gh: not logged in")
        self.forge.operator = offline
        self.assertEqual(self.levels()["gh can reach GitHub"], ("fail", "gh: not logged in"))

    def test_missing_label(self):
        bootstrap.init(self.repo, self.forge, lambda line: None)
        del self.forge.repo_labels["puxirum:needs-info"]
        self.assertEqual(self.levels()["label puxirum:needs-info"][0], "fail")

    def test_cli(self):
        out = io.StringIO()
        code = cli.main(["init"], make_forge=lambda repo: self.forge, cwd=self.repo, out=out)
        self.assertEqual(code, 0)
        self.assertIn("created .puxirum/config.toml", out.getvalue())
        out = io.StringIO()
        code = cli.main(["doctor"], make_forge=lambda repo: self.forge, cwd=self.repo, out=out)
        self.assertEqual(code, 1)
        self.assertIn("FAIL  .puxirum/checks.sh: still the template", out.getvalue())


if __name__ == "__main__":
    unittest.main()
