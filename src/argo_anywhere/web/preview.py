"""Resolved-launch preview for the D-032 launcher (2026-07-15).

This module powers the ``/api/preview-launch`` endpoint. It reflects back
what argo-anywhere WOULD run given the launcher popover's current inputs,
including any divergences between what the user typed and what
``~/.ssh/config`` says. Purely reflective -- no SSH connection is attempted.

**Contract** (per plan §7 C5 + §8 Q11): ``ssh -G <alias>`` is
non-authenticating by design. Zero network I/O to any SSH server, zero
Duo prompts, zero interaction with the D-012 SSH failure tracker.
IP-block-safe by construction. The 2s subprocess timeout guards against
a runaway ``Match exec`` block in the user's own ``~/.ssh/config``
(``ssh -G`` honors Match exec and shells out to evaluate it -- that's
the user attacking themselves via their own config, not our surface,
but the timeout keeps the server thread alive regardless).

**Mirroring contract** (per plan §7 W9 + AGENTS.md D-032 coupling
subsection): the engine's ``ssh_jump_args`` decides at runtime whether
to add ``-J <user>@<ANL_JUMP>`` based on ``--no-jump`` +
``_alias_has_own_proxy`` + the jump-loop guard. This module's
``reflect_jump_args`` is the Python mirror; the two must produce
byte-equivalent output on any given input. A stub-ssh test in
``tests/test_preview_launch.py`` enforces the mirror.
"""

from __future__ import annotations

import getpass
import re
import subprocess
from dataclasses import dataclass


# Default ANL_JUMP (matches the engine's Section 5 declaration). If a
# future engine refactor changes this constant, the mirror below must
# follow -- and vice versa (D-032 coupling contract per AGENTS.md).
DEFAULT_ANL_JUMP = "logins.cels.anl.gov"

#: Reject the same shape ``_SAFE_HOSTLIKE`` in app.py rejects; keep the
#: two in sync (both are hostname/username-safe patterns per RFC 1035).
_SAFE_HOSTLIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")


@dataclass(frozen=True)
class SshGResult:
    """A parsed ``ssh -G`` response for one target.

    Important: ``ssh -G`` ALWAYS returns rc=0 for any syntactically-valid
    hostname, even if that hostname has NO entry in ``~/.ssh/config``.
    It fills in defaults (hostname == input; user == $USER; proxyjump ==
    empty; port == 22; etc.). Distinguishing "real alias" from "bare
    hostname" requires comparing the returned values to the defaults --
    see :meth:`is_meaningful_alias`.
    """

    hostname: str = ""
    user: str = ""
    proxyjump: str = ""       # "none" for explicit no-jump; empty if absent
    proxycommand: str = ""    # "none" for the sentinel; empty if absent

    @property
    def has_own_proxy(self) -> bool:
        """Mirror of engine's ``_alias_has_own_proxy`` semantic."""
        if self.proxyjump and self.proxyjump != "none":
            return True
        if self.proxycommand and self.proxycommand != "none":
            return True
        return False

    def is_meaningful_alias(self, input_target: str) -> tuple[bool, str]:
        """Mirror of engine's ``_is_ssh_config_alias``.

        Returns ``(is_alias, reason)`` where ``reason`` is a human-
        readable description of which signal fired (empty when
        ``is_alias`` is False). Order of signal checks matches the
        engine.

        Signal union (must stay in lockstep with the engine's
        ``_is_ssh_config_alias`` per D-032 coupling contract):

          (1) HostName rewrite -- ``hostname`` field differs from
              ``input_target``. Classic alias.
          (2) ProxyJump / ProxyCommand attached (via
              :meth:`has_own_proxy`). Alias exists to attach routing.
          (3) User attached -- ``user`` field differs from the local
              OS user (``$USER``). Alias exists to attach identity.

        A6 amendment (2026-07-15 live-verify): before this method
        existed, ``/api/preview-launch`` used ``run_ssh_G`` returning
        non-None as the "is a resolved alias" signal. That was wrong
        because ssh -G returns non-None for ANY valid hostname (it
        just fills defaults). Xyzzy test alias came back as
        state=resolved with our $USER as the "resolved user" -- a
        classic false positive.
        """
        # Signal 1: HostName rewrite.
        if self.hostname and self.hostname != input_target:
            return True, f"resolves to {self.hostname}"
        # Signal 2: ProxyJump/ProxyCommand.
        if self.has_own_proxy:
            return True, "no hostname rewrite; routing via ~/.ssh/config's ProxyJump/ProxyCommand"
        # Signal 3: User attached (differs from local OS user).
        try:
            local_user = getpass.getuser()
        except Exception:
            local_user = ""
        if self.user and self.user != local_user:
            return True, (
                f"no hostname rewrite; identity attached via ~/.ssh/config "
                f"(User {self.user})"
            )
        return False, ""


def _parse_ssh_G(stdout: str) -> SshGResult:
    """Parse the lowercase-keyed output of ``ssh -G <alias>``."""
    fields: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            key, value = parts
            # ssh -G output is guaranteed lowercase-keyed on OpenSSH 5.6+
            # (confirmed 2026-07-15 on OpenSSH 10.2p1). We defensively
            # lowercase anyway in case some future ssh changes format.
            fields.setdefault(key.lower(), value)
    return SshGResult(
        hostname=fields.get("hostname", ""),
        user=fields.get("user", ""),
        proxyjump=fields.get("proxyjump", ""),
        proxycommand=fields.get("proxycommand", ""),
    )


def run_ssh_G(alias: str, timeout: float = 2.0) -> SshGResult | None:
    """Run ``ssh -G <alias>`` (non-authenticating) and return the parsed
    result, or ``None`` on failure / timeout / bad input.

    Never raises. Sub-2s timeout protects against ``Match exec`` blocks
    in the user's own config that shell out. Uses a list argv (never
    ``shell=True``) so argv boundaries stay argv boundaries -- no shell
    injection even if the caller bypasses ``_SAFE_HOSTLIKE`` validation.
    """
    if not alias or not _SAFE_HOSTLIKE.match(alias):
        return None
    try:
        proc = subprocess.run(
            ["ssh", "-G", alias],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return _parse_ssh_G(proc.stdout)


def reflect_jump_args(
    user: str,
    target: str,
    *,
    anl_jump: str,
    no_jump: bool,
    ssh_g_result: SshGResult | None,
) -> list[str]:
    """Mirror the engine's ``ssh_jump_args`` decision.

    Returns the argv fragment the engine WOULD emit for the target:
    * ``[]`` if ``--no-jump`` is on (or the equivalent env-empty case).
    * ``[]`` if the target IS the jump host itself (loop guard).
    * ``[]`` if the target has its own ProxyJump/ProxyCommand in
      ``~/.ssh/config`` (D-032 Sub-fix C).
    * ``["-J", "<user>@<anl_jump>"]`` otherwise.

    This function is the Python counterpart to the engine's
    ``ssh_jump_args``; the two must produce byte-equivalent output on
    any given input. Enforced by
    ``tests/test_preview_launch.py::test_reflect_jump_args_matches_engine``.
    """
    if no_jump:
        return []
    if target and target == anl_jump:
        return []
    if ssh_g_result is not None and ssh_g_result.has_own_proxy:
        return []
    return ["-J", f"{user}@{anl_jump}"]
