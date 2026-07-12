"""``python -m argo_anywhere.web`` -- run the local web terminal.

Env overrides (all optional):
- ``ARGO_ANYWHERE_WEB_HOST`` (default ``127.0.0.1``)
- ``ARGO_ANYWHERE_WEB_PORT`` (default ``8799``)
- ``ARGO_ANYWHERE_WEB_ENGINE`` (default ``connect``) -- shell-split engine argv
  the terminal runs, e.g. ``"connect --user me"`` or ``help`` for a dry run.
"""

from __future__ import annotations

import os
import shlex

from .app import serve


def main() -> int:
    host = os.environ.get("ARGO_ANYWHERE_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("ARGO_ANYWHERE_WEB_PORT", "8799"))
    engine_argv = tuple(shlex.split(os.environ.get("ARGO_ANYWHERE_WEB_ENGINE", "connect")))
    serve(host=host, port=port, engine_argv=engine_argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
