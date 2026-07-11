"""D-030c: the package-level `argo-anywhere uninstall` verb.

It intercepts `uninstall` before the engine passthrough, delegates the tiered
teardown to the engine (which the passthrough marks ARGO_ANYWHERE_PACKAGED=1),
and prints the pip/pipx command to remove the package itself -- never
self-deleting. These tests stub the engine call, so no engine/ANL/SSH runs.
"""

from __future__ import annotations

import pytest

from argo_anywhere import cli


def test_removal_command_pipx(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "executable", "/Users/me/.local/pipx/venvs/argo-anywhere/bin/python")
    assert cli._package_removal_command() == "pipx uninstall argo-anywhere"


def test_removal_command_pip(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "executable", "/usr/local/bin/python3")
    assert cli._package_removal_command() == "pip uninstall argo-anywhere"


def test_main_routes_uninstall_to_the_verb(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_passthrough(args):
        captured["args"] = list(args)
        return 0

    monkeypatch.setattr(cli, "_run_engine_passthrough", fake_passthrough)
    rc = cli.main(["uninstall", "--dry-run", "--restore-configs"])
    assert rc == 0
    # The verb delegates to the engine's `uninstall` with the same flags.
    assert captured["args"] == ["uninstall", "--dry-run", "--restore-configs"]


def test_uninstall_prints_removal_hint_on_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_run_engine_passthrough", lambda args: 0)
    monkeypatch.setattr(cli.sys, "executable", "/opt/pipx/venvs/argo-anywhere/bin/python")
    rc = cli.main(["uninstall", "--dry-run"])
    assert rc == 0
    assert "pipx uninstall argo-anywhere" in capsys.readouterr().err


def test_uninstall_no_hint_when_aborted(monkeypatch, capsys) -> None:
    # A non-zero engine rc (e.g. the user answered "N") must NOT nudge the user
    # to remove the package.
    monkeypatch.setattr(cli, "_run_engine_passthrough", lambda args: 1)
    rc = cli.main(["uninstall"])
    assert rc == 1
    assert "uninstall argo-anywhere" not in capsys.readouterr().err


def test_uninstall_in_help_addendum(capfd: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["help"])
    assert rc == 0
    assert "argo-anywhere uninstall" in capfd.readouterr().err
