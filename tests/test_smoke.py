"""P0 smoke tests: the package imports, exposes a version, and the vendored
engine round-trips byte-for-byte through ``--print-script``.

These need no ANL infra, no SSH, no network -- they exercise only the packaging
+ engine-vendoring contract (PLAN.md D-026 "vendored VERBATIM").
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import argo_anywhere
from argo_anywhere import _engine, cli

# Repo-root source of the engine (present in a dev checkout; absent in a wheel).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_ENGINE = _REPO_ROOT / "argo-anywhere.sh"


def test_package_imports_and_has_version() -> None:
    assert isinstance(argo_anywhere.__version__, str)
    # PEP 440-ish: starts with the target major.minor.patch.
    assert re.match(r"^\d+\.\d+\.\d+", argo_anywhere.__version__)
    assert argo_anywhere.__version__.startswith("3.0.0")


def test_engine_bytes_look_like_the_engine() -> None:
    data = _engine.engine_bytes()
    assert isinstance(data, bytes)
    assert len(data) > 50_000  # the engine is ~485 KB, never this small
    assert data.startswith(b"#!")  # shebang
    assert b"SCRIPT_VERSION=" in data  # the engine's internal version tag


def test_engine_path_yields_a_real_file() -> None:
    with _engine.engine_path() as path:
        assert path.is_file()
        assert path.name == _engine.ENGINE_FILENAME
        assert path.read_bytes() == _engine.engine_bytes()


def test_print_script_round_trips(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    rc = cli.main(["--print-script"])
    assert rc == 0
    out = capsysbinary.readouterr().out
    # stdout must reproduce the vendored engine exactly (redirect-to-file works).
    assert out == _engine.engine_bytes()


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "argo-anywhere" in out
    assert argo_anywhere.__version__ in out


def test_help_passes_through_and_appends_addendum(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # `help` runs the engine (subprocess -> fd-level output, hence capfd) then
    # appends the package addendum to stderr.
    rc = cli.main(["help"])
    assert rc == 0
    captured = capfd.readouterr()
    assert "connect" in captured.out          # engine help
    assert "argo-anywhere web" in captured.err  # package addendum


def test_web_subcommand_parses_help() -> None:
    # `web --help` exits 0 via argparse without launching the server.
    with pytest.raises(SystemExit) as exc:
        cli.main(["web", "--help"])
    assert exc.value.code == 0


def test_app_subcommand_parses_help() -> None:
    # `app --help` exits 0 via argparse without opening a window / server.
    with pytest.raises(SystemExit) as exc:
        cli.main(["app", "--help"])
    assert exc.value.code == 0


def test_app_in_help_addendum(capfd: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["help"])
    assert rc == 0
    assert "argo-anywhere app" in capfd.readouterr().err


@pytest.mark.skipif(
    not _SOURCE_ENGINE.exists(),
    reason="repo-root engine source absent (installed wheel, not a dev checkout)",
)
def test_vendored_engine_is_verbatim() -> None:
    """The vendored copy must be byte-identical to the repo-root source (D-026)."""
    assert _engine.engine_bytes() == _SOURCE_ENGINE.read_bytes()
