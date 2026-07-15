"""Tests for src/argo_anywhere/web/ssh_hosts.py (D-032, 2026-07-15).

The parser is a pure file reader with textual Include expansion. Tests
cover:

* basic Host enumeration (single alias per line, multi-alias per line)
* wildcard/negation filtering (``*``, ``?``, ``!foo``, ``[abc]``)
* case-insensitive directive matching
* Include directive expansion (relative + absolute + ~-prefixed +
  glob patterns)
* Include cycle guard
* silent handling of missing / unreadable files
* the "never calls ssh" contract (grep test)

The endpoint tests (``/api/ssh-hosts`` cache + refresh) live in
``tests/test_web.py`` alongside the other endpoint tests.
"""

from __future__ import annotations

from pathlib import Path

from argo_anywhere.web.ssh_hosts import parse_ssh_config_hosts


# ---------------------------------------------------------------------------
# Basic Host enumeration.
# ---------------------------------------------------------------------------


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Nonexistent ssh_config path -> [] (not an exception)."""
    assert parse_ssh_config_hosts(tmp_path / "no-such-file") == []


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("")
    assert parse_ssh_config_hosts(cfg) == []


def test_single_host_directive(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text("Host polaris-login\n    HostName compute-01.cels.anl.gov\n")
    assert parse_ssh_config_hosts(cfg) == ["polaris-login"]


def test_multiple_host_blocks(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host polaris-login\n"
        "    HostName compute-01.cels.anl.gov\n"
        "\n"
        "Host swing\n"
        "    HostName swing.alcf.anl.gov\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["polaris-login", "swing"]


def test_multi_alias_per_host_line(tmp_path: Path) -> None:
    """A single ``Host`` directive can list multiple names -- each is a
    pickable alias."""
    cfg = tmp_path / "config"
    cfg.write_text("Host polaris-login swing crux\n    User me\n")
    assert parse_ssh_config_hosts(cfg) == ["crux", "polaris-login", "swing"]


def test_output_is_sorted_and_deduplicated(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host swing polaris-login\n"
        "    User me\n"
        "Host polaris-login\n"  # dupe on purpose
        "    Port 2222\n"
    )
    hosts = parse_ssh_config_hosts(cfg)
    assert hosts == ["polaris-login", "swing"]  # sorted; dupes collapsed


# ---------------------------------------------------------------------------
# Wildcard / negation filtering (per plan §10.3).
# ---------------------------------------------------------------------------


def test_wildcard_star_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host *\n"
        "    ServerAliveInterval 60\n"
        "Host *.internal\n"
        "    User me\n"
        "Host polaris-login\n"
        "    HostName x\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["polaris-login"]


def test_wildcard_question_mark_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host compute-0?.cels.anl.gov\n"
        "    User me\n"
        "Host swing\n"
        "    User me\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["swing"]


def test_wildcard_bracket_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host compute-[0-9]\n"
        "    User me\n"
        "Host swing\n"
        "    User me\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["swing"]


def test_negated_pattern_rejected(tmp_path: Path) -> None:
    """``!foo`` is ssh_config's "not this alias" negation. Useless in a
    picker (you don't type a negation as a target)."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host !gateway *\n"
        "    User me\n"
        "Host polaris-login\n"
        "    User me\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["polaris-login"]


# ---------------------------------------------------------------------------
# Case + comment handling.
# ---------------------------------------------------------------------------


def test_host_directive_is_case_insensitive(tmp_path: Path) -> None:
    """ssh_config(5) says directive names are case-insensitive. The parser
    accepts ``Host``, ``host``, ``HOST``."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "host polaris-login\n"
        "HOST swing\n"
        "Host crux\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["crux", "polaris-login", "swing"]


def test_comments_stripped(tmp_path: Path) -> None:
    """``#`` starts a comment; content before it is retained."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "# top comment\n"
        "Host polaris-login    # inline comment\n"
        "    HostName x\n"
        "# Host commented-out-alias\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["polaris-login"]


def test_whitespace_variance(tmp_path: Path) -> None:
    """Tabs and multiple spaces around/between tokens are handled."""
    cfg = tmp_path / "config"
    cfg.write_text(
        "\tHost\tpolaris-login\tswing\n"
        "  Host    crux\n"
    )
    assert parse_ssh_config_hosts(cfg) == ["crux", "polaris-login", "swing"]


# ---------------------------------------------------------------------------
# Include directive expansion.
# ---------------------------------------------------------------------------


def test_include_absolute_path(tmp_path: Path) -> None:
    main_cfg = tmp_path / "config"
    included = tmp_path / "included"
    included.write_text("Host polaris-login\n    HostName x\n")
    main_cfg.write_text(f"Include {included}\nHost swing\n    User me\n")
    assert parse_ssh_config_hosts(main_cfg) == ["polaris-login", "swing"]


def test_include_relative_path(tmp_path: Path) -> None:
    """Relative Include values resolve against the DIRECTORY of the current
    config file (matching ssh_config(5) semantics)."""
    conf_dir = tmp_path / ".ssh"
    conf_dir.mkdir()
    main_cfg = conf_dir / "config"
    included = conf_dir / "extra"
    included.write_text("Host polaris-login\n    User me\n")
    main_cfg.write_text("Include extra\nHost swing\n    User me\n")
    assert parse_ssh_config_hosts(main_cfg) == ["polaris-login", "swing"]


def test_include_glob_pattern(tmp_path: Path) -> None:
    """Include supports glob patterns; all matching files are included."""
    conf_d = tmp_path / "conf.d"
    conf_d.mkdir()
    (conf_d / "01-anl.conf").write_text("Host polaris-login\n    User me\n")
    (conf_d / "02-alcf.conf").write_text("Host swing\n    User me\n")
    main_cfg = tmp_path / "config"
    main_cfg.write_text(f"Include {conf_d}/*.conf\n")
    assert parse_ssh_config_hosts(main_cfg) == ["polaris-login", "swing"]


def test_include_missing_file_silent(tmp_path: Path) -> None:
    """Missing include files are silently skipped (OpenSSH behavior)."""
    main_cfg = tmp_path / "config"
    main_cfg.write_text("Include /nonexistent/path\nHost polaris-login\n    User me\n")
    assert parse_ssh_config_hosts(main_cfg) == ["polaris-login"]


def test_include_cycle_guard(tmp_path: Path) -> None:
    """Two files that include each other should not infinite-loop."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text(f"Include {b}\nHost from-a\n    User me\n")
    b.write_text(f"Include {a}\nHost from-b\n    User me\n")
    result = parse_ssh_config_hosts(a)
    # Both hosts appear (each file's own Host line is visited on the FIRST
    # visit; the cycle-guard prevents the SECOND visit from recursing).
    assert result == ["from-a", "from-b"]


# ---------------------------------------------------------------------------
# Contract: NEVER calls ssh (grep-based invariant per plan §7 W11).
# ---------------------------------------------------------------------------


def test_module_source_never_calls_ssh() -> None:
    """The ssh_hosts module MUST NOT call ``ssh`` in any form. Contract per
    plan §7 W11: pure file parser, IP-block-safe by construction.
    """
    import argo_anywhere.web.ssh_hosts as m

    src = Path(m.__file__).read_text()
    # Look for any call-shape that would invoke `ssh` as an executable.
    # False-positives to avoid: "ssh_config" (module name), the docstring's
    # discussion of ssh, "ssh -G" in a comment/docstring.
    # Strategy: grep for subprocess-style patterns and shell-invocation
    # patterns; the whole module deliberately does none of them.
    for pattern in (
        "subprocess.",   # any subprocess call
        "os.system",     # shell invocation
        "os.popen",      # shell invocation
        "os.exec",       # exec* family
        "commands.",     # legacy commands module
    ):
        assert pattern not in src, (
            f"ssh_hosts module contains {pattern!r}; the D-032 contract "
            "says it must NEVER shell out. Move any command-invoking code "
            "to preview.py or a caller that owns the IP-block contract."
        )


# ---------------------------------------------------------------------------
# Real ~/.ssh/config smoke test (skipped if the user has no ssh_config).
# ---------------------------------------------------------------------------


def test_real_ssh_config_smoke() -> None:
    """Live smoke test against the machine's actual ~/.ssh/config. Skipped
    if the file doesn't exist. Returns a list -- doesn't crash on weird
    real-world contents."""
    import pytest
    real = Path.home() / ".ssh" / "config"
    if not real.is_file():
        pytest.skip("no ~/.ssh/config on this machine")
    result = parse_ssh_config_hosts(real)
    # Only assert basic shape; the actual list depends on the user's config.
    assert isinstance(result, list)
    for h in result:
        assert isinstance(h, str)
        assert h  # non-empty
        assert "*" not in h and "?" not in h and "[" not in h
        assert not h.startswith("!")
