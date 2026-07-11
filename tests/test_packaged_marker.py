"""D-030a: the package marks every engine invocation with
``ARGO_ANYWHERE_PACKAGED=1`` so the engine's own bootstrap / self-install /
self-update stay dormant (pipx/pip owns the runtime).

These tests capture the env passed to the spawn without running the engine, so
they need no ANL/SSH/network -- they exercise only the marker wiring.
"""

from __future__ import annotations

import types

from argo_anywhere import cli, driver
from argo_anywhere._engine import PACKAGED_MARKER, packaged_env


def test_packaged_env_sets_the_marker() -> None:
    env = packaged_env()
    assert env[PACKAGED_MARKER] == "1"


def test_packaged_env_merges_environ_and_extra(monkeypatch) -> None:
    monkeypatch.setenv("SOME_INHERITED", "keep")
    env = packaged_env({"EXTRA": "x"})
    assert env["SOME_INHERITED"] == "keep"   # inherits the real environment
    assert env["EXTRA"] == "x"               # applies caller overrides
    assert env[PACKAGED_MARKER] == "1"       # ... and still sets the marker


def test_packaged_env_extra_cannot_unset_marker() -> None:
    # Even if a caller tries to pass the marker through, it stays truthy.
    env = packaged_env({PACKAGED_MARKER: "1"})
    assert env[PACKAGED_MARKER] == "1"


def test_run_engine_lane1_sets_marker(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.run_engine(["status"])
    assert result.returncode == 0
    assert captured["env"][PACKAGED_MARKER] == "1"      # type: ignore[index]
    assert captured["cmd"][0] == "bash"                 # type: ignore[index]


def test_cli_passthrough_sets_marker(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    rc = cli._run_engine_passthrough(["status"])
    assert rc == 0
    assert captured["env"][PACKAGED_MARKER] == "1"      # type: ignore[index]
