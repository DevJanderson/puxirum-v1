"""The tuios adapter: the few tuios verbs the workbench uses, behind one small class.

Puxirum talks to tuios only through `tuios call <verb> '<json>'`, which has a
stable contract: one JSON reply, and errors with a code instead of text to
scrape. The adapter:

- is only built inside a tuios pane (`TUIOS_ENV=1`, a session and a pane id) with
  the `tuios` binary on PATH, and only when the daemon speaks protocol 1.
  Anywhere else `detect` returns None and Puxirum runs exactly the same, with no
  workbench;
- always names the session and the window, never relying on focus, because the
  focused pane is the person's, not ours;
- keeps window ids (uuids), never indexes or names, which change as panes close.

tuios is a mirror. Nothing here is a source of truth: if a call fails, the
workbench may lose a pane or a number on the dashboard, never a job.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from puxirum import __version__

PROTOCOL = 1
CALL_TIMEOUT_S = 15

Caller = Callable[[str, dict[str, Any]], dict[str, Any]]


class TuiosError(Exception):
    def __init__(self, verb: str, code: str, message: str = ""):
        super().__init__(f"tuios {verb}: {code}" + (f": {message}" if message else ""))
        self.verb, self.code, self.message = verb, code, message


def cli_caller(binary: str = "tuios", timeout_s: float = CALL_TIMEOUT_S) -> Caller:
    """Run verbs as `tuios call VERB JSON`. The CLI adds this pane's token itself."""

    def call(verb: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            res = subprocess.run(
                [binary, "call", verb, json.dumps(params)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise TuiosError(verb, "unreachable", str(e)) from None
        try:
            data = json.loads(res.stdout) if res.stdout.strip() else {}
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise TuiosError(verb, "bad_reply", (res.stdout or res.stderr).strip()[:200])
        error = data.get("error")
        if isinstance(error, dict):
            raise TuiosError(verb, str(error.get("code") or "error"), str(error.get("message") or ""))
        if res.returncode != 0:
            raise TuiosError(verb, f"exit {res.returncode}", res.stderr.strip()[:200])
        return data

    return call


class Tuios:
    def __init__(self, session: str, pane: str, call: Caller):
        self.session, self.pane, self._call = session, pane, call

    @classmethod
    def detect(
        cls,
        env: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        call: Caller | None = None,
    ) -> Tuios | None:
        """The adapter for the tuios pane we run in, or None outside tuios.

        A daemon that doesn't speak our protocol is an error, not a silent
        fallback: the person asked for a workbench and should hear why it's missing.
        """
        env = os.environ if env is None else env
        session, pane = env.get("TUIOS_SESSION"), env.get("TUIOS_PANE_ID")
        if env.get("TUIOS_ENV") != "1" or not session or not pane or which("tuios") is None:
            return None
        t = cls(session, pane, call or cli_caller())
        hello = t.call("hello", client="puxirum", version=__version__, protocol=PROTOCOL)
        speaks, oldest = hello.get("protocol"), hello.get("min_protocol", hello.get("protocol"))
        if not isinstance(speaks, int) or not isinstance(oldest, int) or not oldest <= PROTOCOL <= speaks:
            raise TuiosError("hello", "protocol", f"the daemon speaks {oldest}..{speaks}; Puxirum needs {PROTOCOL}")
        return t

    def call(self, verb: str, **params: Any) -> dict[str, Any]:
        return self._call(verb, params)

    # ---- windows --------------------------------------------------------------------------------

    def window(self, window: str) -> dict[str, Any] | None:
        """The window's description, or None when it's gone."""
        try:
            return self.call("get-window", session=self.session, window=window)
        except TuiosError as e:
            if e.code == "window_not_found":
                return None
            raise

    def workspace_of(self, window: str) -> int:
        info = self.window(window)
        if info is None or not isinstance(info.get("workspace"), int):
            raise TuiosError("get-window", "window_not_found", window)
        return info["workspace"]

    def windows_on(self, workspace: int) -> list[str]:
        data = self.call("list-windows", session=self.session)
        windows = data.get("windows", [])
        return [w["window_id"] for w in windows if w.get("workspace") == workspace and w.get("window_id")]

    def name_workspace(self, workspace: int, name: str) -> None:
        self.call("set-workspace-name", session=self.session, workspace=workspace, name=name)

    def split(self, window: str, side: str, name: str) -> str:
        """Open a shell pane on `side` of `window`; returns its id."""
        return str(self.call("split-window", session=self.session, window=window, side=side, name=name)["window_id"])

    def send_text(self, window: str, text: str) -> None:
        self.call("send-text", session=self.session, window=window, text=text)

    def close_window(self, window: str) -> None:
        try:
            self.call("close-window", session=self.session, window=window)
        except TuiosError as e:
            if e.code != "window_not_found":
                raise

    def note(self, window: str, text: str) -> None:
        """A short line on the window, shown in every client and kept across restarts."""
        self.call("set-note", session=self.session, window=window, note=text.encode()[:200].decode(errors="ignore"))

    # ---- TML surfaces ---------------------------------------------------------------------------

    def open_surface(self, doc: str, workspace: int, name: str) -> tuple[str, str]:
        """Show a TML document as a tiled pane; returns (surface id, window id)."""
        data = self.call("tml-open", session=self.session, doc=doc, target="pane", workspace=workspace, name=name)
        return str(data["surface"]), str(data["window_id"])

    def surface_alive(self, surface: str) -> bool:
        try:
            self.call("tml-get", surface=surface)
        except TuiosError:
            return False
        return True

    def patch(self, surface: str, ops: list[dict[str, Any]]) -> None:
        self.call("tml-patch", surface=surface, ops=ops)

    def replace(self, surface: str, doc: str) -> None:
        self.call("tml-replace", surface=surface, doc=doc)

    # ---- the person -----------------------------------------------------------------------------

    def tell(self, question: str, options: list[str]) -> str | None:
        """Put an item in the person's Inbox (and so their notifications) without waiting.

        Returns its request id. tuios caps the line at 160 bytes and an answer at 60.
        """
        data = self.call(
            "ask-human",
            session=self.session,
            window=self.pane,
            question=question.encode()[:160].decode(errors="ignore"),
            options=[o.encode()[:60].decode(errors="ignore") for o in options],
            wait=False,
        )
        rid = data.get("request_id")
        return str(rid) if rid else None
