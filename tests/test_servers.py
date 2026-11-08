import os
import socket
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from puxirum import servers
from puxirum.servers import ServerError

HTTP = [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServersTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        (self.dir / "index.html").write_text("hello app")
        self.log = self.dir / "logs" / "app.log"
        self.port = free_port()

    def tearDown(self):
        self._dir.cleanup()

    def test_serves_then_stops(self):
        with servers.running(HTTP, self.dir, self.port, self.log) as url:
            self.assertEqual(url, f"http://localhost:{self.port}")
            body = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/index.html", timeout=5).read()
            self.assertEqual(body, b"hello app")
        self.assertFalse(servers.listening(self.port))
        self.assertIn("http.server", self.log.read_text())

    def test_setup_runs_first_and_its_failure_is_reported(self):
        with servers.running(HTTP, self.dir, self.port, self.log, setup=["touch", "installed"]):
            self.assertTrue((self.dir / "installed").exists())
        with self.assertRaisesRegex(ServerError, "setup `false` exited with 1"):
            with servers.running(HTTP, self.dir, self.port, self.log, setup=["false"]):
                pass

    def test_server_that_dies(self):
        with self.assertRaisesRegex(ServerError, "exited with 3 before listening"):
            with servers.running([sys.executable, "-c", "raise SystemExit(3)"], self.dir, self.port, self.log):
                pass

    def test_server_that_never_listens(self):
        start = time.monotonic()
        with self.assertRaisesRegex(ServerError, "nothing listened"):
            with servers.running(["sleep", "30"], self.dir, self.port, self.log, ready_timeout_s=0.5):
                pass
        self.assertLess(time.monotonic() - start, 10)

    def test_port_in_use(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", self.port))
            s.listen()
            with self.assertRaisesRegex(ServerError, "already in use"):
                with servers.running(HTTP, self.dir, self.port, self.log):
                    pass

    def test_children_are_stopped_too(self):
        pidfile = self.dir / "child.pid"
        script = (
            f"import subprocess,sys; c=subprocess.Popen(['sleep','60']); open('{pidfile}','w').write(str(c.pid)); "
            f"import runpy; sys.argv=['http.server','{self.port}','--bind','127.0.0.1']; "
            "runpy.run_module('http.server', run_name='__main__')"
        )
        with servers.running([sys.executable, "-c", script], self.dir, self.port, self.log):
            pass
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_port_env_and_placeholder(self):
        script = (
            "import os,sys; assert os.environ['PORT']==sys.argv[1]; "
            "import runpy; sys.argv=['http.server',sys.argv[1],'--bind','127.0.0.1']; "
            "runpy.run_module('http.server', run_name='__main__')"
        )
        with servers.running([sys.executable, "-c", script, "{port}"], self.dir, self.port, self.log):
            self.assertTrue(servers.listening(self.port))


if __name__ == "__main__":
    unittest.main()
