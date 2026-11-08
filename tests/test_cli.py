import io
import unittest
from contextlib import redirect_stderr

from puxirum import cli
from puxirum.config import parse
from puxirum.engine import Engine
from puxirum.forge import FakeForge
from puxirum.runner import FakeRunner
from puxirum.store import Store
from puxirum.world import World
from tests import agents
from tests.gitrepo import Repos


class CliTest(unittest.TestCase):
    def setUp(self):
        self.r = Repos()
        self.r.commit(
            self.r.main,
            {".gitignore": ".worktrees/\n.puxirum/state/\n", ".puxirum/checks.sh": "true\n", "app.txt": "v1\n"},
            "init",
        )
        self.r.push_main()
        self.forge = FakeForge(operator="op")
        self.runner = FakeRunner(agents.happy(builder=agents.builder(status="BLOCKED")))
        world = World(self.r.main, parse({}), Store(self.r.main), self.forge)
        self.engine = Engine(world, self.runner)

    def tearDown(self):
        self.r.cleanup()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stderr(err):
            code = cli.main(list(argv), make_engine=lambda cwd: self.engine, out=out)
        return code, out.getvalue(), err.getvalue()

    def test_status_run_feedback_reject(self):
        code, out, _ = self.cli("status")
        self.assertEqual((code, out), (0, "Nothing in the queue.\n"))
        n = self.forge.add_issue("Editar título", author="ana").number
        code, out, _ = self.cli("status")
        self.assertIn("new", out)
        self.assertIn("Editar título", out)
        code, out, _ = self.cli("run")
        self.assertEqual(code, 0)
        self.assertIn("needs-human", out)
        self.assertIn("give feedback or reject", out)
        self.assertIn("$0.03", out)
        code, _, err = self.cli("reject", str(n), "-m", " ")
        self.assertEqual(code, 1)
        self.assertIn("empty", err)
        code, out, _ = self.cli("feedback", str(n), "-m", "Pick option B.")
        self.assertEqual(code, 0)
        self.assertIn("now build", out)
        self.cli("run")
        code, out, _ = self.cli("reject", "001-editar-titulo", "-m", "Not now.")
        self.assertEqual((code, out), (0, "001-editar-titulo: rejected\n"))

    def test_errors_are_reported_not_raised(self):
        code, _, err = self.cli("feedback", "42", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("no job for issue #42", err)


if __name__ == "__main__":
    unittest.main()
