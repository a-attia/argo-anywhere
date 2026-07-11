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

import re
import subprocess
import sys
from contextlib import ExitStack, asynccontextmanager
from importlib.resources import as_file, files
from typing import Sequence

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from ..driver import KNOWN_VERBS, PtySession, run_engine
from .pty_bridge import run_pty_bridge
from .registry import SessionRegistry

#: Host header values (hostname part, port stripped) accepted by the guard.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: Lowercase-token guard for user-supplied flag values (cli-tool, scope). The
#: browser can only ever hand these to the vendored engine, never to a shell,
#: but we still constrain them to a safe alphabet to keep argv predictable.
_SAFE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

#: Returning verbs the dashboard may run captured (Lane 1) via /api/run. The
#: ``anl`` flag says whether the verb reaches ANL through the tunnel, so the UI
#: can gate those behind an explicit confirm and never auto-run them.
INFO_VERBS: dict[str, dict] = {
    "list-tools": {"anl": False},   # static local list of supported CLI tools
    "status": {"anl": True},        # polls the tunnel + /v1/models when up
    "list-models": {"anl": True},   # fetches models from argo-proxy
}


def build_launch_argv(
    verb: str,
    *,
    cli_tool: str | None = None,
    scope: str | None = None,
    port: int | None = None,
) -> list[str]:
    """Assemble a validated engine argv for a browser-initiated terminal launch.

    Only a known verb plus a constrained set of flags is allowed; free-form
    passthrough is deliberately not supported. Raises ``ValueError`` on anything
    outside the allowlist so the caller can reject the launch.
    """
    if verb not in KNOWN_VERBS:
        raise ValueError(f"unknown verb: {verb!r}")
    argv: list[str] = []
    if cli_tool:
        if not _SAFE_TOKEN.match(cli_tool):
            raise ValueError(f"bad cli_tool: {cli_tool!r}")
        argv += ["--cli-tool", cli_tool]
    if scope:
        if not _SAFE_TOKEN.match(scope):
            raise ValueError(f"bad scope: {scope!r}")
        argv += ["--scope", scope]
    if port is not None:
        if not 1 <= int(port) <= 65535:
            raise ValueError(f"port out of range: {port!r}")
        argv += ["--port", str(int(port))]
    argv.append(verb)
    return argv


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

    # One registry per app: tracks the live PtySessions spawned by /ws so the
    # dashboard can list them and guard against killing a channel-owning one.
    registry = SessionRegistry()

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
    # Exposed for introspection/tests; the /ws handler and endpoints close over
    # the same instance.
    app.state.registry = registry

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

    # NOTE: /api/status and /api/health run blocking work (lsof, a loopback HTTP
    # GET). They are defined as plain `def` so FastAPI runs them in a threadpool
    # rather than blocking the event loop; the WS bridge stays on the loop.
    @app.get("/api/status")
    def api_status() -> JSONResponse:
        # Local-only: versions + loopback listeners + live managed sessions.
        # Does NOT poll channel /health (that would traverse an ANL tunnel); the
        # dashboard requests health explicitly on user action via /api/health.
        from ..status import cached_state, local_listeners, package_info

        state = cached_state()
        ports = sorted({p for p in (state["port"], 8799) if p})
        return JSONResponse({
            "package": package_info(),
            "cached": state,
            "listeners": [ln.as_dict() for ln in local_listeners(ports)],
            "sessions": registry.snapshots(),
        })

    @app.get("/api/sessions")
    async def api_sessions() -> JSONResponse:
        # Live managed PTY sessions. Purely local (waitpid liveness; no network).
        return JSONResponse({"sessions": registry.snapshots()})

    @app.get("/api/health")
    def api_health(port: int) -> JSONResponse:
        # On-demand channel health. This GET traverses the SSH tunnel to reach
        # argo-proxy on the compute node when a tunnel is up, so it is triggered
        # only by an explicit user action in the dashboard (never auto-polled).
        # Against a down port it is a local connection-refused -> up=False.
        from ..status import channel_health

        if not 1 <= port <= 65535:
            return JSONResponse({"error": "port out of range (1-65535)"}, status_code=400)
        return JSONResponse(channel_health(port).as_dict())

    @app.post("/api/sessions/{sid}/stop")
    def api_stop_session(sid: str, force: bool = False) -> JSONResponse:
        # Kill-guard: stopping a session that owns a LIVE SSH channel tears the
        # tunnel down (notes/impl_python_webui.md "Operational lessons"). When
        # that is the case and the caller did not pass force=true, refuse with a
        # 409 + explanation so the UI can confirm intent before proceeding.
        from ..status import cached_state, local_listeners

        managed = registry.get(sid)
        if managed is None:
            return JSONResponse({"error": f"no such session: {sid}"}, status_code=404)

        if managed.owns_channel and managed.session.isalive() and not force:
            port = cached_state().get("port")
            channel_live = bool(port and local_listeners([port]))
            if channel_live:
                return JSONResponse(
                    {
                        "warning": "owns_live_channel",
                        "port": port,
                        "detail": (
                            f"Session {sid} ({managed.verb}) is holding the SSH "
                            f"channel on :{port}. Stopping it tears down the "
                            "tunnel. Re-send with force=true to proceed."
                        ),
                    },
                    status_code=409,
                )

        managed.session.close()
        return JSONResponse({"stopped": sid})

    @app.post("/api/run/{verb}")
    def api_run(verb: str, cli_tool: str | None = None) -> JSONResponse:
        # Run a whitelisted returning verb captured (Lane 1, stdin closed) and
        # return its output. status/list-models reach ANL through the tunnel, so
        # the UI only calls those on an explicit user action (INFO_VERBS.anl).
        spec = INFO_VERBS.get(verb)
        if spec is None:
            return JSONResponse(
                {"error": f"verb not allowed: {verb}", "allowed": sorted(INFO_VERBS)},
                status_code=400,
            )
        argv = [verb]
        if cli_tool:
            if not _SAFE_TOKEN.match(cli_tool):
                return JSONResponse({"error": f"bad cli_tool: {cli_tool}"}, status_code=400)
            argv += ["--cli-tool", cli_tool]
        try:
            result = run_engine(argv, timeout=30)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": f"{verb} timed out"}, status_code=504)
        return JSONResponse({
            "argv": result.argv,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "reaches_anl": spec["anl"],
        })

    @app.get("/api/terminals")
    def api_terminals() -> JSONResponse:
        # Native terminals detected on this machine + the default id, so the
        # launcher can offer a picker instead of assuming one.
        from ..external_terminal import available_terminals, default_terminal

        return JSONResponse({
            "terminals": available_terminals(),
            "default": default_terminal(),
        })

    @app.post("/api/launch-external")
    def api_launch_external(
        verb: str,
        cli_tool: str | None = None,
        scope: str | None = None,
        port: int | None = None,
        terminal: str | None = None,
    ) -> JSONResponse:
        # Open the chosen verb in a NEW native terminal window the user owns
        # (independent of the web server; not tracked in the registry). The
        # window runs the console script on a real TTY -- full-fidelity Duo /
        # monitor / prompts.
        from ..external_terminal import console_command, open_external_terminal

        try:
            engine_argv = build_launch_argv(verb, cli_tool=cli_tool, scope=scope, port=port)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        result = open_external_terminal(console_command() + engine_argv, terminal=terminal)
        return JSONResponse(result, status_code=200 if result.get("ok") else 502)

    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # The HTTP middleware doesn't cover the WS upgrade -- guard it here too.
        if not _host_is_loopback(ws.headers.get("host", "")):
            await ws.close(code=1008)
            return
        # Optional launch spec via query params lets the dashboard run a chosen
        # verb (the launcher); with no params we run the server's configured
        # default (unchanged P0/P1 behavior).
        q = ws.query_params
        if q.get("verb"):
            try:
                argv = build_launch_argv(
                    q["verb"],
                    cli_tool=q.get("cli_tool"),
                    scope=q.get("scope"),
                    port=int(q["port"]) if q.get("port") else None,
                )
            except (ValueError, TypeError):
                await ws.close(code=1008)  # rejected launch spec
                return
        else:
            argv = list(engine_argv)
        await ws.accept()
        session = PtySession(argv, dimensions=(24, 80))
        managed = registry.register(session)
        try:
            await run_pty_bridge(ws, session)
        finally:
            registry.unregister(managed.id)
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
