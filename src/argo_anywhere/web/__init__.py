"""Local web UI for argo-anywhere (optional; ``pip install 'argo-anywhere[web]'``).

A loopback-only FastAPI server that streams the bash engine's interactive flows
to a browser terminal (xterm.js) over a WebSocket-bridged PTY. This is the
packaged form of the P1 spike (PLAN.md D-026); the terminal drives Lane 2 of the
two-lane driver (:mod:`argo_anywhere.driver`).

Importing this subpackage requires the ``[web]`` extra (fastapi + uvicorn). The
factory is :func:`argo_anywhere.web.app.create_app`; :func:`argo_anywhere.web.app.serve`
runs it under uvicorn.
"""

from __future__ import annotations
