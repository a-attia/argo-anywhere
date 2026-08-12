"""argo-anywhere -- Python package that owns the runtime and wraps the unchanged
bash engine, adding a local web UI (Model A; PLAN.md D-026..D-029).

The bash engine (``engine/argo-anywhere.sh``) remains the single source of truth
for all orchestration (SSH mux, Duo, argo-proxy bootstrap, per-tool config). This
package adds the runtime + web layer around it; it does not reimplement the engine.
"""

from __future__ import annotations

# Package version = the single source of release identity (D-029). This is
# distinct from the vendored engine's internal ``SCRIPT_VERSION``.
__version__ = "3.3.0"

__all__ = ["__version__"]
