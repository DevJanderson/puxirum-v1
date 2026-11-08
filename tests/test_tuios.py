import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from puxirum.tuios import Tuios, TuiosError, cli_caller
from tests.fake_tuios import FakeDaemon

ENV = {"TUIOS_ENV": "1", "TUIOS_SESSION": "work", "TUIOS_PANE_ID": "core-pane"}


def found(tool):
    return f"/usr/bin/{tool}"


class DetectTest(unittest.TestCase):
    def test_outside_tuios_there_is_no_adapter(self):
        d = FakeDaemon()
        self.assertIsNone(Tuios.detect({}, found, d))
        self.assertIsNone(Tuios.detect({**ENV, "TUIOS_ENV": "0"}, found, d))
        self.assertIsNone(Tuios.detect({"TUIOS_ENV": "1", "TUIOS_SESSION": "work"}, found, d), "no pane id")
        self.assertIsNone(Tuios.detect(ENV, lambda tool: None, d), "no tuios binary")
        self.assertEqual(d.calls, [], "nothing was called")

    def test_inside_a_pane(self):
        d = FakeDaemon()
        t = Tuios.detect(ENV, found, d)
        self.assertEqual((t.session, t.pane), ("work", "core-pane"))
        self.assertEqual(d.calls[0][0], "hello")
        self.assertEqual(d.calls[0][1]["protocol"], 1)

    def test_a_daemon_that_does_not_speak_our_protocol_is_an_error(self):
        for daemon in (FakeDaemon(protocol=2, min_protocol=2), FakeDaemon(protocol=0, min_protocol=0)):
            with self.assertRaises(TuiosError) as cm:
                Tuios.detect(ENV, found, daemon)
            self.assertEqual(cm.exception.code, "protocol")
        self.assertIsNotNone(Tuios.detect(ENV, found, FakeDaemon(protocol=3, min_protocol=1)))


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.d = FakeDaemon()
        self.core = self.d.add_window("Puxirum", workspace=4)
        self.t = Tuios("work", self.core, self.d)

    def test_every_window_call_names_the_session_and_the_window(self):
        self.t.note(self.core, "x")
        self.t.send_text(self.core, "y")
        self.t.split(self.core, "right", "z")
        for verb, params in self.d.calls:
            self.assertEqual(params["session"], "work", verb)
            self.assertIn("window", params, verb)

    def test_windows(self):
        self.assertEqual(self.t.workspace_of(self.core), 4)
        self.assertIsNone(self.t.window("gone"))
        with self.assertRaises(TuiosError):
            self.t.workspace_of("gone")
        feed = self.t.split(self.core, "down", "Agentes")
        self.assertEqual(self.t.windows_on(4), [self.core, feed])
        self.t.close_window(feed)
        self.t.close_window(feed)  # closing what is already gone is fine
        self.assertEqual(self.t.windows_on(4), [self.core])

    def test_other_errors_are_not_hidden(self):
        self.d.fail["get-window"] = "permission_denied"
        with self.assertRaises(TuiosError):
            self.t.window(self.core)

    def test_surfaces(self):
        doc = '<tml version="1" title="t"><state>{"a": {"b": 1}}</state><text>{state.a.b}</text></tml>'
        sid, wid = self.t.open_surface(doc, 4, "Painel")
        self.assertEqual(self.d.windows[wid]["workspace"], 4)
        self.t.patch(sid, [{"op": "replace", "path": "/a/b", "value": 2}])
        self.assertEqual(self.d.surfaces[sid]["state"], {"a": {"b": 2}})
        self.assertTrue(self.t.surface_alive(sid))
        self.t.close_window(wid)
        self.assertFalse(self.t.surface_alive(sid))

    def test_limits_are_respected(self):
        self.t.note(self.core, "é" * 150)
        self.assertLessEqual(len(self.d.notes[self.core].encode()), 200)
        self.t.tell("x" * 300, ["y" * 100])
        question, options = self.d.asks[0]
        self.assertLessEqual(len(question.encode()), 160)
        self.assertLessEqual(len(options[0].encode()), 60)

    def test_tell_does_not_wait(self):
        self.assertEqual(self.t.tell("#7 escalated", ["ok"]), "r1")
        self.assertFalse(self.d.calls[-1][1]["wait"])
        self.assertEqual(self.d.calls[-1][1]["window"], self.core, "asked as our own pane")


class CliCallerTest(unittest.TestCase):
    """The real `tuios call` contract, against a stand-in binary."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.bin = Path(self._dir.name) / "tuios"
        self.bin.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "verb, params = sys.argv[2], json.loads(sys.argv[3])\n"
            "mode = os.environ.get('FAKE_TUIOS', 'ok')\n"
            "if mode == 'error':\n"
            '    print(json.dumps({"error": {"code": "window_not_found", "message": "no window"}})); sys.exit(1)\n'
            "if mode == 'garbage':\n"
            "    print('not json'); sys.exit(0)\n"
            "if mode == 'crash':\n"
            "    print('boom', file=sys.stderr); sys.exit(3)\n"
            'print(json.dumps({"verb": verb, "params": params}))\n'
        )
        self.bin.chmod(0o755)

    def tearDown(self):
        os.environ.pop("FAKE_TUIOS", None)
        self._dir.cleanup()

    def call(self, mode):
        os.environ["FAKE_TUIOS"] = mode
        return cli_caller(str(self.bin))("get-window", {"window": "w1"})

    def test_reply(self):
        self.assertEqual(self.call("ok"), {"verb": "get-window", "params": {"window": "w1"}})

    def test_errors(self):
        for mode, code in (("error", "window_not_found"), ("garbage", "bad_reply"), ("crash", "exit 3")):
            with self.assertRaises(TuiosError) as cm:
                self.call(mode)
            self.assertEqual(cm.exception.code, code, mode)
        with self.assertRaises(TuiosError) as cm:
            cli_caller(str(self.bin) + "-missing")("hello", {})
        self.assertEqual(cm.exception.code, "unreachable")

    def test_the_json_goes_through_unchanged(self):
        out = self.call("ok")
        self.assertEqual(json.dumps(out["params"]), json.dumps({"window": "w1"}))


if __name__ == "__main__":
    unittest.main()
