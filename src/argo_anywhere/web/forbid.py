"""Scope-conditional forbid-list for launcher cwd (D-031 D6).

This is the Python side of the forbid-list. The **bash side** in the engine
(:file:`argo-anywhere.sh`, function ``_scope_project_forbid_dirs``, Task 8) is
the authoritative source of truth; this file must be kept in lock-step so CLI
users and web users get identical protection.

**Contract.**

* Applies to ``--scope project`` **only**. ``--scope global`` (or empty scope)
  is unrestricted -- beginners who launch a tool from ``$HOME`` just to chat
  with the agent take the happy path. Rationale in the design record §2.2 D6a.
* :func:`check` returns one of three verdicts:
  - :attr:`Verdict.ALLOW` -- fine as-is;
  - :attr:`Verdict.HARD_BLOCK` -- refuse; there is no override (this dir
    is either ``$HOME`` exact or a system dir);
  - :attr:`Verdict.SOFT_WARN` -- allowed with an explicit user confirmation;
    the dir has no ``.git`` and no obvious project marker.

**Order matters** (D-031 A7): hard-block check runs first, then soft-warn. A
path in a hard-blocked root would otherwise trigger a soft-warn stat storm.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from pathlib import Path

#: Hard-blocked directories for ``project`` scope. Matched by **exact path**
#: (checked both pre-resolve and post-resolve to catch macOS's ``/etc`` ->
#: ``/private/etc`` symlinks; ``/tmp/foo`` is NOT blocked because it isn't
#: ``/tmp`` itself). Landing project configs directly at these paths would
#: either litter dotfiles in ``$HOME`` or (worse) touch system directories.
#:
#: Kept in lock-step with the bash ``_scope_project_forbid_dirs`` function in
#: the engine. When either list changes, update both in the same commit.
HARD_BLOCK_ROOTS: frozenset[str] = frozenset({
    "/",
    "/bin",
    "/sbin",
    "/usr",
    "/etc",
    "/var",
    "/opt",
    "/tmp",
    "/var/tmp",
    # macOS additions -- present on Linux too as ordinary dirs but there's no
    # reason to project-configure them either.
    "/System",
    "/Library",
    "/private",
    # macOS symlink targets: /etc -> /private/etc, /tmp -> /private/tmp,
    # /var -> /private/var. Include the targets so post-resolve exact-match
    # catches them on Darwin.
    "/private/etc",
    "/private/var",
    "/private/tmp",
    "/private/var/tmp",
})

#: Files whose presence indicates a real project. If ANY of these exist in cwd
#: (or ``.git`` as a subdir), project scope is allowed without a soft-warn.
#: The list matches "the usual suspects" across ecosystems Python + JS + Rust
#: + Go + Java + native.
PROJECT_MARKER_FILES: frozenset[str] = frozenset({
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "Makefile",
    "makefile",
    "GNUmakefile",
    "go.mod",
    "CMakeLists.txt",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
})

#: Existing tool-config filenames. If the user has one of these in cwd, they've
#: clearly chosen this dir as a project before; skip the soft-warn.
TOOL_CONFIG_FILES: frozenset[str] = frozenset({
    "opencode.json",
    ".aider.conf.yml",
})

#: Subdirectory markers checked separately from files.
PROJECT_MARKER_DIRS: frozenset[str] = frozenset({
    ".git",
    ".claude",  # claudecode writes .claude/settings.local.json in project scope
})


class Verdict(enum.Enum):
    """Forbid-list verdicts. See module docstring for semantics."""

    ALLOW = "allow"
    HARD_BLOCK = "hard_block"
    SOFT_WARN = "soft_warn"


@dataclass(frozen=True)
class ForbidResult:
    """Outcome of :func:`check`."""

    verdict: Verdict
    reason: str

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def blocking(self) -> bool:
        return self.verdict is Verdict.HARD_BLOCK


def _home_dir() -> Path:
    return Path(os.path.expanduser("~")).resolve()


def _has_project_marker(cwd: Path) -> bool:
    for name in PROJECT_MARKER_FILES:
        if (cwd / name).is_file():
            return True
    for name in PROJECT_MARKER_DIRS:
        if (cwd / name).is_dir():
            return True
    for name in TOOL_CONFIG_FILES:
        if (cwd / name).exists():
            return True
    return False


def check(cwd: str | os.PathLike[str], scope: str | None) -> ForbidResult:
    """Evaluate the forbid-list for ``cwd`` under the given ``scope``.

    ``scope`` values: ``"project"`` triggers the full check; anything else
    (``"global"``, ``""``, ``None``, ``"auto"``) short-circuits to
    :attr:`Verdict.ALLOW` because the tool doesn't write into ``cwd`` under
    non-project scopes.

    ``cwd`` is assumed to be an absolute, existing directory (the caller has
    already run :func:`argo_anywhere.web.validation.validate_cwd`); this
    function is purely about the scope-conditional policy layer.
    """
    if scope != "project":
        return ForbidResult(Verdict.ALLOW, "global scope is unrestricted")

    expanded = Path(cwd).expanduser()
    resolved = expanded.resolve()
    resolved_s = str(resolved)
    expanded_s = str(expanded)

    # A1 (order): hard-block first. Compare BOTH the pre-resolve form (so
    # a user typing "/etc" is caught even on macOS where /etc -> /private/etc)
    # AND the post-resolve form (so a symlink pointing at /etc is also caught).
    if resolved_s in HARD_BLOCK_ROOTS or expanded_s in HARD_BLOCK_ROOTS:
        return ForbidResult(
            Verdict.HARD_BLOCK,
            f"{resolved_s} is a system dir; refusing to write a project config here.",
        )
    if resolved == _home_dir():
        return ForbidResult(
            Verdict.HARD_BLOCK,
            (
                f"{resolved_s} is your $HOME; a project config there would "
                "litter dotfiles in your home directory. Use --scope global "
                "instead, or pick a project subdirectory."
            ),
        )

    # A2: soft-warn if no project marker + no existing tool config.
    if not _has_project_marker(resolved):
        return ForbidResult(
            Verdict.SOFT_WARN,
            (
                f"{resolved_s} has no .git and no obvious project marker "
                "(pyproject.toml, package.json, Cargo.toml, ...). Project scope "
                "will write the config directly here. If you just want to chat "
                "with the agent without touching this directory, pick "
                "--scope global instead."
            ),
        )
    return ForbidResult(Verdict.ALLOW, "ok")
