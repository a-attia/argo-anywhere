"""FastAPI app for the local web terminal (loopback-only; D-026).

The server binds ``127.0.0.1`` and enforces a DNS-rebinding guard (the Host
header must name loopback), mirroring the P1 spike. It is otherwise
unauthenticated: it shares the user's shell trust boundary -- anyone who can
already reach ``127.0.0.1:<port>`` has the user's shell (PLAN.md §11 Q11, to be
ratified in docs/SECURITY.md).

Each ``/ws`` connection spawns one :class:`~argo_anywhere.driver.PtySession`
running the configured engine invocation (default ``connect``) and streams it to
the browser terminal via :func:`argo_anywhere.web.pty_bridge.run_pty_bridge`.
"""

from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager
from importlib.resources import as_file, files
from typing import Sequence

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from ..driver import PtySession
from .pty_bridge import run_pty_bridge

#: Host header values (hostname part, port stripped) accepted by the guard.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _host_is_loopback(host_header: str) -> bool:
    """True if the Host header names loopback (DNS-rebinding guard).

    An empty Host is allowed (some ws clients omit it, and the socket is bound to
    loopback anyway); any non-loopback name is refused.
    """
    if not host_header:
        return True
    host = host_header
    # Strip the port, handling the bracketed IPv6 form [::1]:8799.
    if host.startswith("["):
        host = host.split("]", 1)[0] + "]"
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host in _LOOPBACK_HOSTS


def _static_dir():
    """A real filesystem path to the vendored static assets."""
    return as_file(files(__package__).joinpath("static"))


def create_app(*, engine_argv: Sequence[str] = ("connect",)) -> FastAPI:
    """Build the FastAPI app.

    ``engine_argv`` is the engine invocation each ``/ws`` connection runs (the
    Lane-2 flow streamed to the terminal); it defaults to ``connect``.
    """
    engine_argv = tuple(engine_argv)

    # Resolve the vendored static dir to a real path and keep it valid for the
    # app's lifetime (a no-op for a normal filesystem install; matters only for
    # a zip-imported package).
    _stack = ExitStack()
    static_path = _stack.enter_context(_static_dir())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            _stack.close()

    app = FastAPI(title="argo-anywhere", lifespan=lifespan)

    @app.middleware("http")
    async def _host_guard(request, call_next):
        if not _host_is_loopback(request.headers.get("host", "")):
            return PlainTextResponse("forbidden host", status_code=403)
        return await call_next(request)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_path / "index.html")

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # The HTTP middleware doesn't cover the WS upgrade -- guard it here too.
        if not _host_is_loopback(ws.headers.get("host", "")):
            await ws.close(code=1008)
            return
        await ws.accept()
        session = PtySession(list(engine_argv), dimensions=(24, 80))
        try:
            await run_pty_bridge(ws, session)
        finally:
            session.close()

    return app


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8799,
    engine_argv: Sequence[str] = ("connect",),
) -> None:
    """Run the web UI under uvicorn (blocking)."""
    import uvicorn

    app = create_app(engine_argv=engine_argv)
    print(f"[argo-anywhere web] engine: {' '.join(engine_argv)!r}")
    print(f"[argo-anywhere web] open http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
