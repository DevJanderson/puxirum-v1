import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from puxirum import orphans


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); it no longer runs.
    return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"


class OrphansTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        self._dir.cleanup()

    def start(self, *argv):
        """A group leader with a child, as `claude -p` or `npm run dev` would have."""
        script = "import subprocess, time; subprocess.Popen(['sleep', '60']); time.sleep(60)"
        p = subprocess.Popen([sys.executable, "-c", script, *argv], start_new_session=True)
        self.procs.append(p)
        time.sleep(0.3)
        child = int(subprocess.run(["pgrep", "-P", str(p.pid)], capture_output=True, text=True).stdout.split()[0])
        return p, child

    def test_a_left_over_group_is_stopped_with_everything_it_started(self):
        p, child = self.start()
        pid_file = self.dir / "builder-r1-a1.pid"
        orphans.record(pid_file, p.pid, sys.executable)
        stopped = orphans.reap([pid_file], grace_s=2)
        p.wait(timeout=5)
        time.sleep(0.2)
        self.assertEqual(stopped, [f"builder-r1-a1 (pid {p.pid})"])
        self.assertFalse(alive(child), "the agent's own children go too")
        self.assertFalse(pid_file.exists())

    def test_a_reused_pid_running_something_else_is_left_alone(self):
        p, _ = self.start()
        pid_file = self.dir / "x.pid"
        orphans.record(pid_file, p.pid, "claude")
        self.assertEqual(orphans.reap([pid_file], grace_s=1), [])
        self.assertIsNone(p.poll(), "not ours: still running")
        self.assertFalse(pid_file.exists(), "the stale file is cleared")

    def test_gone_and_garbled_files_are_just_cleared(self):
        gone = self.dir / "gone.pid"
        orphans.record(gone, 2**22 + 12345, "claude")
        bad = self.dir / "bad.pid"
        bad.write_text("not json")
        self.assertEqual(orphans.reap([gone, bad]), [])
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_tracked_removes_the_file_when_done(self):
        path = self.dir / "a.pid"
        with orphans.tracked(path, 1, "x"):
            self.assertTrue(path.exists())
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
