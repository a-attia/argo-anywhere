"""Per-user derived default port (D-035) and the channel-only next-steps tail.

**The structural problem.** Every install shipped the same literal default
port. A TCP port on a shared compute node is node-global and first-binder-wins,
so on a node with ten argo-anywhere tenants a collision was not an edge case --
it was the expected outcome. Everything built after the 2026-08-10 incident
(the bind-test oracle, the identity gate, the collision prompt) treats a
collision as something to *survive*. This makes it unlikely to happen.

The default is now derived from the ANL username, spread over
``PROXY_PORT_SPAN`` slots above ``PROXY_PORT_BASE``. Three properties matter and
each is pinned below:

* **Deterministic** -- the port is transport state that the cache, the client
  configs and the far end must agree on. A random default would fight that.
* **Bounded** -- inside the range, so the free-port walk stays in the same
  neighbourhood and cannot run off the end of the port space.
* **Advisory** -- a hint, not a reservation. Two usernames can hash to one slot
  and a co-tenant may hold it anyway, so bind-test detection, the collision
  prompt and the free-port walk all still apply unchanged.

**Why the ANL username specifically**, never the laptop's ``$USER``: the port
is contended on the *node*, among Argonne accounts. The maintainer's laptop
user is ``attia`` and his Argonne user is ``aattia``; deriving from the former
would give two people who happen to share a laptop username the same slot.

**Why not also the machine name**: the tunnel is ``localhost:P -> node:P``, one
number at both ends. Hashing the node would vary the port *per machine*, which
invalidates every client config on a node switch -- while the local-side
collision it would solve is already refused outright (``ensure_or_reuse_tunnel``
declines two tunnels on one local port to different nodes).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from argo_anywhere._engine import engine_path

BASE = 64742
SPAN = 500


def _engine_source() -> str:
    with engine_path() as script:
        return script.read_text()


def _function_body(src: str, name: str) -> str:
    lines = src.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"{name}() {{")), None
    )
    assert start is not None, f"{name} definition not found in engine"
    pending: str | None = None
    for idx in range(start, len(lines)):
        line = lines[idx]
        if pending is not None:
            if line.strip() == pending:
                pending = None
            continue
        opener = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
        if opener:
            pending = opener.group(1)
            continue
        if idx > start and line == "}":
            return "\n".join(lines[start : idx + 1])
    raise AssertionError(f"unterminated function body for {name}")


def _derive(tmp_path: Path, user: str, *, user_cache: str | None = None) -> int:
    """Run the engine's real _derive_default_port."""
    src = _engine_source()
    cache = user_cache if user_cache is not None else "/nonexistent"
    script = "\n".join(
        (
            "set -uo pipefail",
            f"PROXY_PORT_BASE={BASE}",
            f"PROXY_PORT_SPAN={SPAN}",
            f"USER_CACHE={cache}",
            _function_body(src, "_username_for_port_derivation"),
            _function_body(src, "_derive_default_port"),
            f'_derive_default_port "{user}"',
        )
    )
    path = tmp_path / "d.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return int(out.stdout.strip())


# ---------------------------------------------------------------------------
# The derivation
# ---------------------------------------------------------------------------


def test_derivation_is_deterministic(tmp_path: Path) -> None:
    """Same user, same port, every run and every machine.

    Load-bearing: the port is written into client configs and the cache, so a
    value that moved between runs would guarantee the drift this release spent
    its time fixing.
    """
    first = _derive(tmp_path, "aattia")
    for _ in range(4):
        assert _derive(tmp_path, "aattia") == first


def test_derivation_stays_in_range(tmp_path: Path) -> None:
    """Must not run off the end of the port space."""
    users = ["aattia", "jdoe", "alice", "bob", "x", "averyverylongusername123",
             "a.b_c-d", "ZZZ"]
    for u in users:
        port = _derive(tmp_path, u)
        assert BASE <= port < BASE + SPAN, f"{u} -> {port} outside the range"
        assert port <= 65535, f"{u} -> {port} above the maximum TCP port"


def test_different_users_generally_differ(tmp_path: Path) -> None:
    """The whole point: co-tenants should not start on the same port.

    Not a guarantee -- collisions in the hash are possible and handled
    downstream -- so this asserts spread, not uniqueness.
    """
    users = ["aattia", "jdoe", "alice", "bob", "carol", "dave", "erin", "frank",
             "grace", "heidi"]
    ports = [_derive(tmp_path, u) for u in users]
    assert len(set(ports)) >= 9, (
        f"derivation clusters badly: {len(set(ports))} distinct of {len(users)}: {ports}"
    )


def test_per_machine_usernames_get_independent_ports(tmp_path: Path) -> None:
    """A user with different Argonne accounts per machine.

    ``~/.ssh/config`` resolution is per-target, so a user can be ``aattia`` on
    CELS and ``attia_a`` on Aurora. Those are different accounts competing for
    different slots and must not share a derived port.
    """
    assert _derive(tmp_path, "aattia") != _derive(tmp_path, "attia_a")


def test_unknown_username_falls_back_to_base(tmp_path: Path) -> None:
    """No name to hash -> the base port, never empty and never a crash."""
    assert _derive(tmp_path, "") == BASE


def test_derivation_survives_a_missing_hash_tool(tmp_path: Path) -> None:
    """Degrade to the base rather than die if cksum/awk are unavailable."""
    src = _engine_source()
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    script = "\n".join(
        (
            "set -uo pipefail",
            f"PATH={empty_bin}",
            f"PROXY_PORT_BASE={BASE}",
            f"PROXY_PORT_SPAN={SPAN}",
            "USER_CACHE=/nonexistent",
            _function_body(src, "_username_for_port_derivation"),
            _function_body(src, "_derive_default_port"),
            '_derive_default_port "aattia"',
        )
    )
    path = tmp_path / "nohash.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f"must not die: {out.stderr}"
    assert out.stdout.strip() == str(BASE)


def test_derivation_never_uses_the_local_os_username() -> None:
    """The contended resource is on the NODE, among Argonne accounts.

    The laptop's ``$USER`` is a different namespace -- ``attia`` vs ``aattia``
    on the maintainer's own machine -- and hashing it would collide two people
    who share a laptop username while separating one person from themselves.
    """
    body = _function_body(_engine_source(), "_username_for_port_derivation")
    code = [ln for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    joined = "\n".join(code)
    # \$USER must not match \$USER_CACHE, which is a legitimate ANL-username
    # source -- hence the boundary rather than a substring test.
    for pattern, label in (
        (r"\bid\s+-un\b", "id -un"),
        (r"\bwhoami\b", "whoami"),
        (r"\$USER(?![A-Za-z0-9_])", "$USER"),
        (r"\$\{USER(?![A-Za-z0-9_])", "${USER}"),
    ):
        assert not re.search(pattern, joined), (
            f"derivation reads {label}; it must use the ANL username only"
        )


# ---------------------------------------------------------------------------
# Re-derivation once the username is known
# ---------------------------------------------------------------------------


def _rederive(tmp_path: Path, *, port: int, source: str, user: str) -> dict:
    src = _engine_source()
    script = "\n".join(
        (
            "set -uo pipefail",
            f"PROXY_PORT_BASE={BASE}",
            f"PROXY_PORT_SPAN={SPAN}",
            "USER_CACHE=/nonexistent",
            'log(){ :; }',
            f"PROXY_PORT={port}",
            f'PORT_SOURCE="{source}"',
            f'ANL_USERNAME="{user}"',
            '_PORT_CACHE_PENDING=""',
            _function_body(src, "_username_for_port_derivation"),
            _function_body(src, "_derive_default_port"),
            _function_body(src, "_maybe_rederive_default_port"),
            "_maybe_rederive_default_port",
            'echo "PORT=$PROXY_PORT"',
            'echo "PENDING=$_PORT_CACHE_PENDING"',
        )
    )
    path = tmp_path / "r.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )


COLD = "built-in base (no cache, no configs, username not yet known; seeding /x)"


def test_rederives_on_a_cold_start(tmp_path: Path) -> None:
    """The case that matters: a brand-new user must not land on the base port.

    ``resolve_port`` runs before ``resolve_username`` (which can prompt), so on
    a first run it has no name to hash and falls back to the shared base --
    handing a new user the one port every other install also starts on, exactly
    when they are most likely to collide.
    """
    res = _rederive(tmp_path, port=BASE, source=COLD, user="aattia")
    expected = _derive(tmp_path, "aattia")
    assert res["PORT"] == str(expected), "cold start did not re-derive"
    assert res["PORT"] != str(BASE)
    assert res["PENDING"] == str(expected), (
        "the re-derived port must be STAGED, so it is cached only after the "
        "channel comes up (CACHE-AFTER-SUCCESS INVARIANT)"
    )


@pytest.mark.parametrize(
    "source",
    [
        "--port flag",
        "ARGO_ANYWHERE_PORT env",
        "cached port (/x)",
        "migrated from opencode config (cached for future runs)",
        "derived from username 'aattia' (no cache, no existing client configs)",
    ],
)
def test_rederivation_never_overrides_a_real_decision(
    tmp_path: Path, source: str
) -> None:
    """It seeds a default; it does not second-guess one.

    An explicit ``--port``, a cached port, or a port migrated from a client
    config all outrank the derivation. Overriding any of them would move a port
    the user or their configs already committed to.
    """
    res = _rederive(tmp_path, port=9999, source=source, user="aattia")
    assert res["PORT"] == "9999", f"re-derivation clobbered a {source!r} port"
    assert res["PENDING"] == ""


def test_rederivation_is_a_noop_without_a_username(tmp_path: Path) -> None:
    res = _rederive(tmp_path, port=BASE, source=COLD, user="")
    assert res["PORT"] == str(BASE)


def test_rederivation_runs_before_the_port_is_announced() -> None:
    """Every 'Using port:' log must follow a re-derivation attempt.

    Otherwise a mode announces one port and then quietly uses another -- the
    class of inconsistency that made the v3.3.0 incident hard to diagnose.
    """
    lines = _engine_source().splitlines()
    announces = [
        i for i, ln in enumerate(lines)
        if ln.strip() == 'log "Using port: ${PROXY_PORT}  (source: ${PORT_SOURCE})"'
    ]
    assert announces, "no port announcements found -- did the wording change?"
    for i in announces:
        window = "\n".join(lines[max(0, i - 4) : i])
        assert "_maybe_rederive_default_port" in window, (
            f"port announced at line {i + 1} without re-deriving first:\n{window}"
        )


def test_base_is_not_handed_out_directly() -> None:
    """``resolve_port``'s cold-start branch must derive, not use the literal.

    This is the only branch that hands out a fresh port, so it is the only one
    that had to change -- and the only one that can regress.
    """
    body = _function_body(_engine_source(), "resolve_port")
    assert "_derive_default_port" in body, (
        "resolve_port no longer derives; every install would start on the same port"
    )


def test_span_is_wide_enough_to_matter() -> None:
    """A narrow span leaves the structural problem substantially intact.

    Birthday problem: over 100 slots, ten co-tenants collide 37% of the time
    and twenty collide 87% -- on a node that had 22 argo-proxy processes during
    the incident. 500 gives 8.7% and 32%.
    """
    src = _engine_source()
    m = re.search(r"^PROXY_PORT_SPAN=(\d+)", src, re.M)
    assert m, "PROXY_PORT_SPAN not found"
    span = int(m.group(1))
    assert span >= 500, f"span {span} is too narrow to reduce collisions materially"
    base_m = re.search(r"^PROXY_PORT_BASE=(\d+)", src, re.M)
    assert base_m
    assert int(base_m.group(1)) + span <= 65535, "range runs past the port space"


# ---------------------------------------------------------------------------
# The channel-only next-steps tail
# ---------------------------------------------------------------------------


def _next_steps(tmp_path: Path, *, port: int, opencode=None, aider=None) -> str:
    src = _engine_source()
    oc = tmp_path / "oc.json"
    if opencode:
        oc.write_text(json.dumps({"provider": {"argo": {"options": {
            "baseURL": f"http://localhost:{opencode}/v1"}}}}))
    ai = tmp_path / "aider.yml"
    if aider:
        ai.write_text(f"openai-api-base: http://localhost:{aider}/v1\n")
    fns = "\n".join(
        _function_body(src, f) for f in (
            "read_port_from_opencode_config",
            "_get_port_from_claudecode_config",
            "_get_port_from_aider_config",
            "enumerate_client_ports",
            "report_next_steps",
        )
    )
    script = "\n".join(
        (
            "set -uo pipefail",
            'log(){ echo "$*"; }',
            "ARGO_ANYWHERE_PACKAGED=1",
            "ANL_USERNAME=aattia",
            f"PROXY_PORT={port}",
            f"OPENCODE_GLOBAL_CONFIG={oc}",
            f"OPENCODE_CONFIG={oc}",
            "CLAUDECODE_GLOBAL_CONFIG=/nonexistent",
            "CLAUDECODE_PROJECT_CONFIG=/nonexistent",
            f"AIDER_GLOBAL_CONFIG={ai}",
            'CLI_TOOLS_AVAILABLE=("opencode|OpenCode" "claudecode|Claude Code" "aider|aider")',
            fns,
            f"report_next_steps {port}",
        )
    )
    path = tmp_path / "n.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_next_steps_separates_ready_stale_and_absent(tmp_path: Path) -> None:
    """One channel, three different situations, three different answers."""
    out = _next_steps(tmp_path, port=64743, opencode=64743, aider=64751)
    assert "Ready now" in out and "opencode" in out
    assert "Needs updating" in out
    assert "configure aider" in out, "a drifted tool needs the configure command"
    assert "Not set up yet" in out and "run claudecode" in out, (
        "a tool with no config should be offered `run`, which configures and launches"
    )


def test_next_steps_offers_run_for_unconfigured_tools(tmp_path: Path) -> None:
    """A first-time user with nothing configured must still get a command.

    The old tail said only 'no client configured' and described the endpoint,
    which tells the user what exists rather than what to do.
    """
    out = _next_steps(tmp_path, port=64743)
    assert "run opencode" in out
    assert "configure opencode" in out


def test_next_steps_names_the_binary_for_ready_tools(tmp_path: Path) -> None:
    """claudecode's binary is `claude`; printing the tool token would mislead."""
    src = _engine_source()
    body = _function_body(src, "report_next_steps")
    assert 'claudecode' in body and '_bin="claude"' in body, (
        "claudecode must be announced as its actual binary name"
    )


def test_next_steps_does_not_write_any_config() -> None:
    """`connect` is channel-only by contract (D-024).

    Writing three config files from a verb named 'connect' is the unattended
    state change that caused the v3.3.0 incident. Report; do not act.
    """
    body = _function_body(_engine_source(), "report_next_steps")
    for forbidden in ("write_opencode_config", "write_aider_config",
                      "write_claudecode_config", "handle_config_file",
                      "write_port_cache"):
        assert forbidden not in body, (
            f"report_next_steps calls {forbidden}; it must only report"
        )


def test_engine_copies_stay_byte_identical() -> None:
    """Root and vendored engine copies must not diverge (D-001/D-028)."""
    repo_root = Path(__file__).resolve().parent.parent
    root_copy = repo_root / "argo-anywhere.sh"
    if not root_copy.exists():  # pragma: no cover
        pytest.skip("root engine copy not present in this layout")
    with engine_path() as vendored:
        assert root_copy.read_bytes() == vendored.read_bytes()
