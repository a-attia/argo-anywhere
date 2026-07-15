"""Enumerate ssh_config Host aliases for the launcher's node picker (D-032).

**Contract** (per plan §8 Q11 decision): this module NEVER calls ``ssh``.
Pure filesystem read of ``~/.ssh/config`` with textual ``Include`` expansion.
Zero network I/O, zero SSH authentication attempts, zero interaction with the
D-012 SSH failure tracker. Safe to fire on every page load without any CSPO
IP-block risk. Future maintainers: do NOT introduce ``ssh -G`` or ``ssh -T``
invocations here; use the ``Match exec``-free file parser only.

**Scope**: enumerate only Host directives whose value looks like a
concrete alias (no wildcards ``*``/``?``, no negations ``!``). Wildcard
patterns like ``Host *.internal`` are legitimate ssh_config content but
don't make sense in a picker (the user isn't typing a pattern, they're
typing a target).

**Include expansion**: ssh_config's ``Include`` directive is honored via
textual expansion. Relative paths in Include values resolve relative to
``~/.ssh/`` (matching OpenSSH's semantics; see ssh_config(5)). Absolute
paths and ``~`` prefixes are honored. Missing include files are silently
skipped (matches OpenSSH's behavior; the picker just shows fewer aliases).

**Recursion guard**: Include cycles (rare in practice but easy to
create) are detected via a seen-set; the second visit is skipped.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path


def _iter_config_lines(path: Path, seen: set[str] | None = None) -> list[str]:
    """Read ``path`` line-by-line, textually expanding ``Include`` directives.

    Returns a flat list of logical config lines (whitespace-stripped;
    comments removed). ``seen`` tracks resolved paths to break Include
    cycles.
    """
    if seen is None:
        seen = set()
    try:
        resolved = str(path.resolve())
    except OSError:
        return []
    if resolved in seen:
        return []  # cycle guard
    seen.add(resolved)
    if not path.is_file():
        return []
    lines: list[str] = []
    try:
        with path.open() as f:
            raw_lines = f.readlines()
    except OSError:
        return []
    for raw in raw_lines:
        # Strip trailing newline + inline comments. ssh_config uses `#`
        # for line comments; there's no in-line comment syntax so a `#`
        # anywhere on a line terminates the logical content.
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        # Include directive: recurse. Case-insensitive per ssh_config(5).
        stripped = line.strip()
        parts = stripped.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "include":
            for include_path in _resolve_include(parts[1], path.parent):
                lines.extend(_iter_config_lines(include_path, seen))
            continue
        lines.append(line)
    return lines


def _resolve_include(value: str, config_dir: Path) -> list[Path]:
    """Resolve an Include directive value to a list of concrete Path objects.

    ssh_config's Include supports:
    * absolute paths (``/etc/ssh/ssh_config.d/*.conf``)
    * ``~``-prefixed paths (``~/.ssh/conf.d/*.conf``)
    * relative paths (resolved against the directory of the CURRENT
      config file per ssh_config(5); typically ``~/.ssh/``)
    * glob patterns (``*``, ``?``, ``[...]``) in any component
    """
    # Strip leading/trailing whitespace + quotes (ssh_config allows both).
    value = value.strip().strip('"').strip("'")
    if not value:
        return []
    # Absolute + ~-prefixed: expand and glob.
    if value.startswith("/") or value.startswith("~"):
        pattern = os.path.expanduser(value)
    else:
        # Relative: anchor at the current config's directory.
        pattern = str(config_dir / value)
    # glob returns [] for both "no match" and "invalid pattern", matching
    # OpenSSH's silent-skip semantics.
    return [Path(p) for p in sorted(glob.glob(pattern))]


def parse_ssh_config_hosts(path: Path | None = None) -> list[str]:
    """Return the list of Host aliases suitable for a picker.

    Returns ``[]`` if the config file doesn't exist or is unreadable.
    Never raises.
    """
    cfg = path or (Path.home() / ".ssh" / "config")
    lines = _iter_config_lines(cfg)
    seen_aliases: set[str] = set()
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        if parts[0].lower() != "host":
            continue
        # A single Host directive can list multiple names:
        #   Host polaris-login swing crux
        # Filter each independently.
        for name in parts[1:]:
            if _is_pickable_alias(name):
                seen_aliases.add(name)
    return sorted(seen_aliases)


def _is_pickable_alias(name: str) -> bool:
    """True if ``name`` is a concrete alias suitable for a datalist.

    Rejects:
    * wildcard patterns (``*``, ``?``, ``[...]``) -- not concrete targets
    * negated patterns (``!foo``) -- ssh_config-specific "not this alias"
      syntax; useless in a picker
    * empty strings (defensive)
    """
    if not name:
        return False
    if name.startswith("!"):
        return False
    for ch in ("*", "?", "["):
        if ch in name:
            return False
    return True
