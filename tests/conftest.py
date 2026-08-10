"""Shared pytest fixtures.

The headline fixture here is :func:`_isolate_home`, which is **autouse**: it
redirects every filesystem path the package derives from ``$HOME`` at a
per-test tmp directory, so running the suite can never touch the developer's
real ``~/.argo_anywhere`` / ``~/.config/argo_anywhere`` / ``~/.ssh``.

Why autouse rather than opt-in
------------------------------
``tests/test_web.py`` already shipped a ``state_file`` fixture that did this
correctly -- but it was opt-in, and three tests that reach the MRU-writing code
path (``test_ws_accepts_valid_cwd``,
``test_launch_external_passes_d032_flags_through``,
``test_launch_external_omits_empty_d032_fields``) simply forgot to request it.
The result (found 2026-08-09): every ``pytest`` run appended dead
``/private/var/folders/.../pytest-of-*/`` paths into the maintainer's real
``~/.argo_anywhere/web_state.json`` MRU list, and a Playwright-driven theme
toggle during the same audit persisted ``theme: "dark"`` into it too.

Opt-in isolation fails open: the cost of forgetting is invisible (the test
still passes) and the damage lands outside the repo. Autouse fails closed --
a new test that touches ``$HOME`` is isolated by default and an author has to
opt *out* deliberately.

Why patching the module attributes is required
----------------------------------------------
``argo_anywhere.status`` computes ``STATE_DIR`` / ``APP_HOME`` /
``WEB_STATE_FILE`` at **import time**, and ``argo_anywhere.web.state`` does
``from ..status import WEB_STATE_FILE``, binding its own module-level name to
the same object. Monkeypatching ``HOME`` alone therefore changes nothing for
already-imported modules; both the origin constant *and* every re-export have
to be re-pointed. That is what this fixture does.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every ``$HOME``-derived path at a per-test tmp directory.

    Returns the fake home so a test can assert against it if it wants to.
    """
    from argo_anywhere import status as _status
    from argo_anywhere.web import state as _state

    # Placed in a private sibling of ``tmp_path`` rather than inside it. Two
    # constraints force this:
    #   * NOT ``tmp_path / "home"`` -- several tests build their own fake home
    #     at exactly that path (test_status, test_web_validation,
    #     test_web_forbid) and would collide with a dir we pre-created.
    #   * NOT anywhere inside ``tmp_path`` at all -- two atomic-write tests
    #     assert their target's parent dir contains nothing else, to prove no
    #     ``.tmp`` sibling leaked. A sandbox dir sitting in ``tmp_path`` would
    #     be counted as that leak and fail a test about unrelated behaviour.
    home = tmp_path.parent / (tmp_path.name + "-argohome")
    app_home = home / ".argo_anywhere"
    state_dir = home / ".config" / "argo_anywhere"
    app_home.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    # Env first, so anything resolving ~ lazily (subprocesses, expanduser calls
    # made at call time rather than import time) also lands in the sandbox.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # harmless on POSIX

    # Then the already-bound module-level constants. `raising=False` keeps this
    # robust if a constant is renamed/removed in a future refactor -- the env
    # redirect above still holds the line.
    monkeypatch.setattr(_status, "APP_HOME", app_home, raising=False)
    monkeypatch.setattr(_status, "STATE_DIR", state_dir, raising=False)
    monkeypatch.setattr(
        _status, "WEB_STATE_FILE", app_home / "web_state.json", raising=False
    )
    # web.state re-exported WEB_STATE_FILE into its own namespace at import.
    monkeypatch.setattr(
        _state, "WEB_STATE_FILE", app_home / "web_state.json", raising=False
    )

    return home
