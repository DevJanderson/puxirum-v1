"""The app's dev server, started by the core for the agents that need to see the app.

The agent never decides whether to start a server: the core runs the project's
setup, starts the server on the job's port in its own process group, waits
until the port answers, hands the agent the URL and stops the whole group when
the agent is done. Phase 3 shows these servers as tuios windows.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

KILL_GRACE_S = 5
POLL_S = 0.1


class ServerError(Exception):
    pass


def listening(port: int) -> bool:
    """Something accepts connections on localhost:port, over IPv4 or IPv6."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        with contextlib.suppress(OSError), socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                return True
    return False


@contextlib.contextmanager
def running(command: Sequence[str], cwd: Path, port: int, log_path: Path, *, setup: Sequence[str] = (),
            ready_timeout_s: float = 60, setup_timeout_s: float = 900,
            env: dict[str, str] | None = None) -> Iterator[str]:
    """Run setup, start the server and yield its URL; stop it on exit."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    full_env = {**os.environ, **(env or {}), "PORT": str(port)}
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        if setup:
            log.write(f"$ {' '.join(setup)}\n")
            log.flush()
            try:
                res = subprocess.run(list(setup), cwd=cwd, env=full_env, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, timeout=setup_timeout_s)
            except subprocess.TimeoutExpired:
                raise ServerError(f"setup timed out after {setup_timeout_s:.0f}s; see {log_path.name}") from None
            if res.returncode != 0:
                raise ServerError(f"setup `{' '.join(setup)}` exited with {res.returncode}; see {log_path.name}")
        if listening(port):
            raise ServerError(f"port {port} is already in use")
        argv = [arg.replace("{port}", str(port)) for arg in command]
        log.write(f"$ {' '.join(argv)}\n")
        log.flush()
        proc = subprocess.Popen(argv, cwd=cwd, env=full_env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + ready_timeout_s
            while not listening(port):
                code = proc.poll()
                if code is not None:
                    raise ServerError(f"`{' '.join(argv)}` exited with {code} before listening; see {log_path.name}")
                if time.monotonic() > deadline:
                    raise ServerError(f"nothing listened on port {port} after {ready_timeout_s:.0f}s; "
                                      f"see {log_path.name}")
                time.sleep(POLL_S)
            yield f"http://localhost:{port}"
        finally:
            _stop(proc)


def _stop(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, KILL_GRACE_S), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)  # children that outlived the leader
