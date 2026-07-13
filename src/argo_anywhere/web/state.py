"""Persisted web-UI state (D-031 §4.1 + A6).

Backing store for the launcher's MRU cwd list, the panel divider position, and
(added by Task 5.5) the light/dark theme choice. Lives at
``~/.argo_anywhere/web_state.json`` (see :data:`argo_anywhere.status.WEB_STATE_FILE`).

Design constraints:

* **Versioned schema** (``version: 1``) so we can migrate later without breaking
  older installs. Unknown versions log a warning and reset to defaults.
* **Atomic writes** via ``tempfile.NamedTemporaryFile`` in the same directory +
  ``os.replace``. Prevents a concurrent reader from seeing a half-written file
  (two web instances racing on the same file, or a crash mid-write).
* **Never raises** on read: missing file / bad JSON / bad shape all return the
  default state so a corrupted file never breaks the UI. Write failures raise
  ``OSError`` (the endpoint layer catches + returns 500 with a clear error).
* **MRU dedupe + cap** enforced on write via :func:`touch_mru` so callers never
  need to know the discipline.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..status import WEB_STATE_FILE, ensure_app_home

#: Current schema version. Bumped when the shape of the JSON changes in a way
#: readers must be aware of. Readers of higher versions gracefully downgrade.
SCHEMA_VERSION = 1

#: Maximum number of MRU cwd entries kept. LIFO; oldest are dropped when a new
#: entry pushes the list past this cap.
MRU_CAP = 10

#: Divider position bounds (percent of container width taken by the Channel
#: panel). Matches the JS-side clamp in ``index.html``.
DIVIDER_MIN = 25
DIVIDER_MAX = 75

#: Legal theme values (extended by Task 5.5). Unknown values fall back to
#: ``"auto"`` on read.
THEME_VALUES = ("auto", "dark", "light")


def default_state() -> dict[str, Any]:
    """The fresh-install / corrupted-file fallback."""
    return {
        "version": SCHEMA_VERSION,
        "mru": [],
        "divider_pct": 50,
        "theme": "auto",
    }


def _clamp_divider(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 50
    return max(DIVIDER_MIN, min(DIVIDER_MAX, n))


def _clean_mru(raw: Any) -> list[str]:
    """Normalize MRU input: absolute strings only, deduped preserving order,
    capped at :data:`MRU_CAP`. Non-existent paths are pruned lazily so a
    project the user deleted doesn't clutter the datalist."""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s or not os.path.isabs(s):
            continue
        # Lazy prune: skip entries whose paths have since vanished. We don't
        # remove them from disk here (that's a write; keep read-side pure);
        # the next write via touch_mru will drop them from what gets saved.
        if not os.path.isdir(s):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= MRU_CAP:
            break
    return out


def _clean_theme(raw: Any) -> str:
    if isinstance(raw, str) and raw in THEME_VALUES:
        return raw
    return "auto"


def load_state(path: Path | None = None) -> dict[str, Any]:
    """Return the persisted state, or :func:`default_state` on any error.

    Never raises. ``path`` overrides the default location (used by tests)."""
    p = path if path is not None else WEB_STATE_FILE
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError):
        return default_state()
    if not isinstance(raw, dict):
        return default_state()
    version = raw.get("version")
    if version != SCHEMA_VERSION:
        # Unknown/future version -> fall back rather than mangle. Preserved in
        # the file until the next write (which upgrades the schema).
        return default_state()
    return {
        "version": SCHEMA_VERSION,
        "mru": _clean_mru(raw.get("mru")),
        "divider_pct": _clamp_divider(raw.get("divider_pct", 50)),
        "theme": _clean_theme(raw.get("theme", "auto")),
    }


def save_state(state: dict[str, Any], path: Path | None = None) -> Path:
    """Atomically write the state to disk. Returns the resolved file path."""
    p = path if path is not None else WEB_STATE_FILE
    # Make sure the directory exists (D-031 A5: canonical install may not have
    # been bootstrapped yet). ensure_app_home() targets ~/.argo_anywhere; for a
    # non-default path we mkdir its parent.
    if path is None:
        ensure_app_home()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling tempfile then rename -- atomic on POSIX + fine on
    # Windows via os.replace's overwrite semantics.
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=p.name + ".", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, p)
    except Exception:
        # Best-effort cleanup of the tempfile if replace didn't succeed.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return p


def touch_mru(cwd: str, path: Path | None = None) -> list[str]:
    """Record a successful cwd usage: prepend to MRU + dedupe + cap + persist.

    Returns the new MRU list (post-clamp). Silently no-ops on a bad cwd
    (non-absolute) so callers don't have to pre-validate again."""
    if not cwd or not os.path.isabs(cwd):
        return load_state(path)["mru"]
    state = load_state(path)
    mru = [x for x in state["mru"] if x != cwd]
    mru.insert(0, cwd)
    del mru[MRU_CAP:]
    state["mru"] = mru
    save_state(state, path)
    return mru


def update_state(patch: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Merge ``patch`` into the current state + persist. Returns the new state.

    Only known keys are honored (``divider_pct``, ``theme``, ``mru``); unknown
    keys are silently dropped so a stale UI can't inject arbitrary JSON."""
    state = load_state(path)
    if "divider_pct" in patch:
        state["divider_pct"] = _clamp_divider(patch["divider_pct"])
    if "theme" in patch:
        state["theme"] = _clean_theme(patch["theme"])
    if "mru" in patch:
        state["mru"] = _clean_mru(patch["mru"])
    save_state(state, path)
    return state
