"""Driver tests: verb classification (pure) + Lane-1 and Lane-2 exercised
against the engine's ``help`` verb (local, fast, no ANL/SSH/network).

``help`` is the safe choice: the engine's main() exempts it from the legacy-state
gate and it never opens a tunnel or prompts, so it returns 0 with usage text on
both lanes.
"""

from __future__ import annotations

import select
import time

import pytest

from argo_anywhere import driver
from argo_anywhere.driver import Lane


# -- classification (pure) --------------------------------------------------

@pytest.mark.parametrize(
    "argv, expected",
    [
        (["status"], "status"),
        (["--port", "64742", "status"], "status"),   # flags before the verb
        (["connect", "--user", "x"], "connect"),       # flags after the verb
        ([], "client"),                                 # engine default
        (["--user", "x"], "client"),                   # flags only -> default
        (["configure", "opencode", "aider"], "configure"),
    ],
)
def test_verb_of(argv: list[str], expected: str) -> None:
    assert driver.verb_of(argv) == expected


@pytest.mark.parametrize(
    "argv, lane",
    [
        (["status"], Lane.SUBPROCESS),
        (["list-models"], Lane.SUBPROCESS),
        (["help"], Lane.SUBPROCESS),
        (["stop"], Lane.SUBPROCESS),
        (["connect"], Lane.PTY),
        (["configure", "opencode"], Lane.PTY),
        (["run", "aider"], Lane.PTY),
        (["--port", "64742"], Lane.PTY),   # default client -> interactive
        (["frobnicate"], Lane.PTY),         # unknown token -> safe default
    ],
)
def test_classify(argv: list[str], lane: Lane) -> None:
    assert driver.classify(argv) == lane


def test_every_subprocess_verb_is_a_known_verb() -> None:
    assert driver.SUBPROCESS_VERBS <= driver.KNOWN_VERBS


# -- Lane 1: captured subprocess -------------------------------------------

def test_run_engine_help_returns_usage() -> None:
    result = driver.run_engine(["help"], timeout=30)
    assert result.ok
    assert result.returncode == 0
    # usage names the core subcommands (NB: the engine's help text omits
    # `configure` today -- a known engine doc gap, not a driver concern).
    assert "connect" in result.stdout
    assert "status" in result.stdout


def test_run_engine_closes_stdin() -> None:
    # `help` doesn't read stdin, but this asserts the call completes promptly
    # (no hang) which is the point of DEVNULL stdin for Lane 1.
    start = time.time()
    result = driver.run_engine(["help"], timeout=30)
    assert result.ok
    assert time.time() - start < 30


# -- Lane 2: pseudo-terminal ------------------------------------------------

def _drain(session: driver.PtySession, deadline_s: float = 15.0) -> bytes:
    out = b""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        r, _, _ = select.select([session.fileno()], [], [], 0.5)
        if r:
            chunk = session.read()
            if not chunk:
                break
            out += chunk
        elif not session.isalive():
            break
    return out


def test_pty_session_runs_help_on_a_terminal() -> None:
    with driver.PtySession(["help"], dimensions=(40, 120)) as session:
        assert session.pid > 0
        out = _drain(session)
        session.wait(timeout=5)
        assert session.exitstatus == 0
    # help output rendered to the PTY
    assert b"connect" in out


def test_pty_session_set_winsize_does_not_raise() -> None:
    with driver.PtySession(["help"]) as session:
        session.set_winsize(50, 200)  # ioctl must succeed on the master fd
        _drain(session)
        session.wait(timeout=5)
