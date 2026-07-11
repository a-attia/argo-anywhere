"""Locate + read the vendored bash engine.

The engine is shipped as package-data (``engine/argo-anywhere.sh``) and vendored
VERBATIM from the repo-root ``argo_anywhere.sh`` (PLAN.md D-026). Two access
shapes are provided:

- :func:`engine_bytes` -- raw bytes, for ``--print-script`` (D-026 escape hatch).
- :func:`engine_path` -- a context manager yielding a real filesystem path, for
  handing the script to ``bash`` (the driver's Lane 1 / Lane 2, later phases).
  ``importlib.resources.as_file`` guarantees a real path even if the package is
  installed inside a zip, which ``bash`` requires.
"""

from __future__ import annotations

import contextlib
import os
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterator, Mapping

# The vendored filename is hyphenated (D-028); the repo-root source is still the
# underscore name until the clean-break cutover.
ENGINE_FILENAME = "argo-anywhere.sh"
_ENGINE_RESOURCE = f"engine/{ENGINE_FILENAME}"

# D-030a: environment marker set on EVERY engine invocation the package spawns
# (CLI passthrough + web/PTY driver lanes). It tells the vendored engine it is
# driven by the Python package, so the engine's own first-run bootstrap /
# self-install / `update argo-anywhere` self-update stay dormant -- the package
# (pipx/pip) owns the runtime (D-029). A raw `--print-script` fork runs `bash`
# directly and never sets this, so a forked engine keeps full D-023/D-025
# self-install behavior. One env var distinguishes the two modes.
PACKAGED_MARKER = "ARGO_ANYWHERE_PACKAGED"


def packaged_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return ``os.environ`` plus the D-030a package marker (+ optional overrides).

    Use for any subprocess/PTY spawn of the vendored engine from the package.
    """
    env: dict[str, str] = {**os.environ, PACKAGED_MARKER: "1"}
    if extra:
        env.update(extra)
    return env


def engine_bytes() -> bytes:
    """Return the vendored engine as raw bytes (byte-identical to the source)."""
    return files(__package__).joinpath(_ENGINE_RESOURCE).read_bytes()


@contextlib.contextmanager
def engine_path() -> Iterator[Path]:
    """Yield a real filesystem path to the vendored engine, usable by ``bash``.

    Use as a context manager::

        with engine_path() as script:
            subprocess.run(["bash", str(script), "status"])
    """
    resource = files(__package__).joinpath(_ENGINE_RESOURCE)
    with as_file(resource) as path:
        yield path
