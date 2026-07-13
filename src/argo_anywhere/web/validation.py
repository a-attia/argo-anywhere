"""Server-side validation for launcher-supplied working directories (D-031).

The web UI's launcher popover requires an absolute path in the cwd field
(client-side check per D2a), and this module runs the same check on the server
so the enforcement is defense-in-depth: nothing that comes over the wire is
trusted just because the browser page said so.

Validation is intentionally simple and non-network:

* absolute path required (blank / relative rejected);
* ``~`` expanded via :meth:`pathlib.Path.expanduser`;
* symlinks resolved via :meth:`pathlib.Path.resolve` so error messages + logs
  name the canonical target;
* returns one of three verdicts (:class:`CwdVerdict`) so the endpoint can
  translate to the right HTTP status.

The forbid-list (project-scope hard/soft blocks per D-031 D6) lives in
:mod:`argo_anywhere.web.forbid` and is invoked from Task 7; this module
only does the shape/existence/type checks common to every launch.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from pathlib import Path


class CwdVerdict(enum.Enum):
    """Outcome of a cwd validation.

    * :attr:`OK` -- path is absolute, exists, and is a readable directory.
    * :attr:`BAD_INPUT` -- blank, relative, or otherwise unusable syntactically;
      the launch cannot proceed and the user must fix their input (400).
    * :attr:`MISSING` -- absolute + syntactically valid but does not exist on
      disk; the endpoint returns 409 so the UI can offer to create it (D2c).
    * :attr:`NOT_DIRECTORY` -- exists but is not a directory (a file, a socket,
      etc.); reject with 400 -- there's nothing meaningful to create here.
    * :attr:`NOT_READABLE` -- exists as a directory but the server user cannot
      read + traverse it (rare; typically a permission-mode footgun); 400.
    """

    OK = "ok"
    BAD_INPUT = "bad_input"
    MISSING = "missing"
    NOT_DIRECTORY = "not_directory"
    NOT_READABLE = "not_readable"


@dataclass(frozen=True)
class CwdValidation:
    """Result of :func:`validate_cwd`. ``resolved`` is ``None`` when the input
    couldn't even be parsed (``BAD_INPUT``)."""

    verdict: CwdVerdict
    resolved: Path | None
    detail: str

    @property
    def ok(self) -> bool:
        return self.verdict is CwdVerdict.OK


def validate_cwd(raw: str | None) -> CwdValidation:
    """Validate a user-supplied cwd string. Never raises.

    ``raw`` is what the launcher UI sent (``lCwd`` value or ``cwd`` query/body
    param). Blank / whitespace / ``None`` return ``BAD_INPUT`` -- the launcher
    is expected to pre-fill a default so the user always has something visible
    to edit (D3b).
    """
    if raw is None or not raw.strip():
        return CwdValidation(
            CwdVerdict.BAD_INPUT,
            None,
            "cwd is required (blank not accepted); pick a directory in the launcher.",
        )

    # Expand ~ / ~user, resolve symlinks + .. fragments. ``strict=False`` so
    # nonexistent paths return a normalized Path instead of raising -- the
    # MISSING verdict below is how we surface "doesn't exist yet".
    try:
        expanded = Path(raw).expanduser()
    except (RuntimeError, ValueError) as exc:  # e.g. ~unknownuser
        return CwdValidation(
            CwdVerdict.BAD_INPUT, None, f"cannot expand path: {exc}"
        )

    if not expanded.is_absolute():
        return CwdValidation(
            CwdVerdict.BAD_INPUT,
            None,
            (
                f"cwd must be absolute (got {raw!r}); use an absolute path "
                "or the Browse button (pywebview only) to pick one."
            ),
        )

    try:
        resolved = expanded.resolve(strict=False)
    except (OSError, RuntimeError) as exc:  # e.g. symlink loop
        return CwdValidation(
            CwdVerdict.BAD_INPUT, None, f"cannot resolve path: {exc}"
        )

    if not resolved.exists():
        return CwdValidation(
            CwdVerdict.MISSING,
            resolved,
            f"directory does not exist: {resolved}",
        )
    if not resolved.is_dir():
        return CwdValidation(
            CwdVerdict.NOT_DIRECTORY,
            resolved,
            f"path exists but is not a directory: {resolved}",
        )
    # Readable + traversable check (r-x on the dir bit). This is the mode the
    # engine needs to cd there + list its contents (e.g. for project markers).
    if not os.access(resolved, os.R_OK | os.X_OK):
        return CwdValidation(
            CwdVerdict.NOT_READABLE,
            resolved,
            f"directory not readable/traversable by this user: {resolved}",
        )
    return CwdValidation(CwdVerdict.OK, resolved, "ok")


#: HTTP status codes we return for each verdict. Kept in one place so
#: endpoints stay consistent + the UI can key its error handling off status.
STATUS_FOR_VERDICT: dict[CwdVerdict, int] = {
    CwdVerdict.OK: 200,
    CwdVerdict.BAD_INPUT: 400,
    CwdVerdict.MISSING: 409,          # UI offers "create?" per D2c
    CwdVerdict.NOT_DIRECTORY: 400,
    CwdVerdict.NOT_READABLE: 400,
}
