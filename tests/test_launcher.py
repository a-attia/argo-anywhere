"""Install-launcher (scrollback-style): double-clickable launchers for the web UI.

Generation is platform-parameterized (``system=``) so these run identically on
macOS and Linux CI. All local: no GUI opens, no ANL/SSH/network.
"""

from __future__ import annotations

import sys
from pathlib import Path

from argo_anywhere import cli, footprint, launcher


def test_macos_creates_command_and_app(tmp_path: Path) -> None:
    created = launcher.install(system="darwin", home=tmp_path)
    names = {p.name for p in created}
    assert names == {"argo-anywhere.command", "argo-anywhere.app"}
    # Desktop dir doesn't exist in tmp, so the .command lands in home.
    cmd = next(p for p in created if p.suffix == ".command")
    body = cmd.read_text()
    assert sys.executable in body                    # interpreter baked in
    assert "-m argo_anywhere app" in body
    assert cmd.stat().st_mode & 0o100                # executable bit
    # The .app bundle is real: runner + Info.plist.
    app = next(p for p in created if p.suffix == ".app")
    assert (app / "Contents" / "MacOS" / "argo-anywhere").is_file()
    plist = (app / "Contents" / "Info.plist").read_text()
    assert "CFBundleExecutable" in plist and "argo-anywhere" in plist


def test_linux_creates_desktop_and_sh(tmp_path: Path) -> None:
    created = launcher.install(system="linux", home=tmp_path)
    names = {p.name for p in created}
    assert names == {"argo-anywhere.desktop", "argo-anywhere.sh"}
    entry = next(p for p in created if p.suffix == ".desktop")
    body = entry.read_text()
    assert body.startswith("[Desktop Entry]")
    assert sys.executable in body and "-m argo_anywhere app" in body


def test_desktop_selector_macos_only_command(tmp_path: Path) -> None:
    created = launcher.install(system="darwin", home=tmp_path, desktop=True)
    assert [p.suffix for p in created] == [".command"]


def test_app_bundle_selector_macos_only_app(tmp_path: Path) -> None:
    created = launcher.install(system="darwin", home=tmp_path, app_bundle=True)
    assert [p.suffix for p in created] == [".app"]


def test_installed_artifacts_roundtrip(tmp_path: Path) -> None:
    assert launcher.installed_artifacts(home=tmp_path, system="darwin") == []
    launcher.install(system="darwin", home=tmp_path)
    found = {p.name for p in launcher.installed_artifacts(home=tmp_path, system="darwin")}
    assert "argo-anywhere.command" in found and "argo-anywhere.app" in found


def test_remove_path_handles_file_and_dir(tmp_path: Path) -> None:
    created = launcher.install(system="darwin", home=tmp_path)
    for p in created:
        assert p.exists()
        launcher.remove_path(p)
        assert not p.exists()


def test_footprint_includes_launcher(tmp_path: Path) -> None:
    # Create on the RUNNING platform so footprint()'s default-system scan finds it.
    launcher.install(home=tmp_path)
    entries = footprint.footprint(home=tmp_path)
    assert any(e.description.startswith("web-app launcher") and e.tier == "artifact"
               for e in entries)


def test_cli_install_launcher_verb(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = cli.main(["install-launcher"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "created:" in out
    assert launcher.installed_artifacts(home=tmp_path)  # something was written


def test_uninstall_sweeps_launcher(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    launcher.install(home=tmp_path)
    assert launcher.installed_artifacts(home=tmp_path)
    # Stub the engine teardown to succeed so the residue sweep runs.
    monkeypatch.setattr(cli, "_run_engine_passthrough", lambda a: 0)
    rc = cli.main(["uninstall", "-y"])
    assert rc == 0
    assert launcher.installed_artifacts(home=tmp_path) == []  # swept
    assert "removed launcher:" in capsys.readouterr().err
