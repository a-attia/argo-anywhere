"""D-030b: a single ledger of argo-anywhere's own on-disk footprint.

Mirrors the sibling ``scrollback`` project's ``footprint()``: one enumeration of
every path THIS tool created on the machine, tagged by tier. It is consumed by
``argo-anywhere info`` for visibility -- so a user can answer "what has
argo-anywhere put on my machine?" in one place.

This module never DELETES anything. Removal stays delegated to the engine's
tiered ``uninstall`` (which owns the live-channel ownership guard); the footprint
is the visibility half of D-030b (removal of the overlapping tiers is the
engine's job).

It NEVER lists the user's live agent data (OpenCode / Claude Code / aider
configs): argo-anywhere only reads-and-restores those. The config *backups* it
created (``<config>.bak.*``) are listed -- they are unambiguously ours and are
the restore source ``uninstall --restore-configs`` would use.

Tiers (a subset of scrollback's; argo owns no ``durable`` user data):

* ``disposable`` -- rebuilt on demand / pure state: the state dir (cached
  identity + the install manifest + the ssh-fail lock) and the SSH multiplex
  sockets.
* ``artifact``   -- things an install created: the canonical script install
  (``~/.argo_anywhere/``, **engine mode only** -- never created under the
  package, D-030a) and the client-config backups.
"""

from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from pathlib import Path

# SSH multiplex socket name prefixes this tool has used (current + v1.x). Both
# are unambiguously ours; the engine's own clean/uninstall sweep both.
_SOCKET_GLOBS = ("argo-anywhere-*", "argo-opencode-*")


@dataclass(frozen=True)
class FootprintEntry:
    """One path argo-anywhere created on disk, tagged by tier."""

    path: Path
    tier: str          # "disposable" | "artifact"
    description: str

    def size_bytes(self) -> int:
        return _path_size(self.path)

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "tier": self.tier,
            "description": self.description,
            "size_bytes": self.size_bytes(),
        }


def _path_size(path: Path) -> int:
    """Total bytes at ``path`` (a file/socket's own size, or a dir's contents)."""
    try:
        if path.is_symlink() or path.is_file() or path.is_socket():
            return path.lstat().st_size
    except OSError:
        return 0
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def _config_backups(manifest: Path) -> list[Path]:
    """Backups (``<config>.bak.*``) of pre-existing configs the manifest tracks.

    These are the restore source ``uninstall --restore-configs`` would use.
    Mirrors the engine's ``_manifest_configs_to_restore`` glob (it discovers the
    backup at restore time rather than storing its path). Only existing files.
    """
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[Path] = []
    for cfg, meta in (data.get("configs") or {}).items():
        if isinstance(meta, dict) and not meta.get("created_by_us"):
            out.extend(Path(p) for p in sorted(glob.glob(str(cfg) + ".bak.*")))
    return out


def footprint(home: Path | None = None) -> list[FootprintEntry]:
    """Every path argo-anywhere may have created under ``home``, tagged by tier.

    Only paths that currently exist are returned. ``home`` defaults to the real
    home dir; it is a parameter so callers (and tests) can scope the scan.
    """
    h = home if home is not None else Path.home()
    state_dir = h / ".config" / "argo_anywhere"
    canonical = h / ".argo_anywhere"
    sockets_dir = h / ".ssh" / "sockets"
    manifest = state_dir / "manifest.json"

    entries: list[FootprintEntry] = []

    # artifact: the canonical script install (engine mode only; D-030a means
    # this is never created under the package, so under pipx it is absent).
    if canonical.exists():
        entries.append(FootprintEntry(
            canonical, "artifact",
            "canonical script install (engine mode; not created under the package)",
        ))

    # disposable: the state dir (cached identity + manifest + ssh-fail lock).
    if state_dir.exists():
        entries.append(FootprintEntry(
            state_dir, "disposable",
            "state: cached identity, install manifest, ssh-fail lock",
        ))

    # disposable: SSH multiplex sockets.
    if sockets_dir.is_dir():
        for pattern in _SOCKET_GLOBS:
            for sock in sorted(sockets_dir.glob(pattern)):
                entries.append(FootprintEntry(
                    sock, "disposable", "SSH multiplex socket",
                ))

    # artifact: client-config backups (the restore source).
    for bak in _config_backups(manifest):
        if bak.exists():
            entries.append(FootprintEntry(
                bak, "artifact",
                "client-config backup (restore source; consumed by uninstall --restore-configs)",
            ))

    return entries


def format_size(n: int) -> str:
    """Human-readable byte count (e.g. ``12.3 KB``)."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
