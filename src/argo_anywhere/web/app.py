"""FastAPI app for the local web terminal (loopback-only; D-026).

The server binds ``127.0.0.1`` and enforces a DNS-rebinding guard (the Host
header must name loopback), mirroring the P1 spike. It is otherwise
unauthenticated: it shares the user's shell trust boundary -- anyone who can
already reach ``127.0.0.1:<port>`` has the user's shell. This posture is
ratified for v3.0.0 (PLAN.md §11 Q11; see docs/SECURITY.md "Local web UI");
a loopback token / Origin check is queued as post-3.0 hardening against the
local-process / browser-CSRF residual.

Each ``/ws`` connection spawns one :class:`~argo_anywhere.driver.PtySession`
running the configured engine invocation (default ``connect``) and streams it to
the browser terminal via :func:`argo_anywhere.web.pty_bridge.run_pty_bridge`.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from contextlib import ExitStack, asynccontextmanager
from importlib.resources import as_file, files
from typing import Sequence

import argo_anywhere
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from ..driver import KNOWN_VERBS, PtySession, run_engine
from .pty_bridge import run_pty_bridge
from .registry import (
    CHANNEL_PANEL_VERBS,
    UTILITY_PANEL_VERBS,
    PanelSlot,
    SessionRegistry,
)
from . import state as _state
from .forbid import Verdict as ForbidVerdict
from .forbid import check as check_forbid
from .validation import STATUS_FOR_VERDICT, CwdVerdict, validate_cwd

#: Host header values (hostname part, port stripped) accepted by the guard.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: Lowercase-token guard for user-supplied flag values (cli-tool, scope). The
#: browser can only ever hand these to the vendored engine, never to a shell,
#: but we still constrain them to a safe alphabet to keep argv predictable.
_SAFE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

#: Hostname / username / jump-host guard for D-032 launcher fields
#: (compute node, ANL username, jump-host). Broader than _SAFE_TOKEN because
#: real hostnames contain ``.`` (compute-01.cels.anl.gov), real usernames
#: contain ``_`` (some ANL accounts), and both preserve case (mixed-case
#: aliases are unusual but legal). Deliberately excludes ``@`` (would confuse
#: ``${user}@${host}`` target parse in the engine), ``/`` and ``:`` (path/
#: URI separators — nothing to do with hostnames), whitespace, and shell
#: metachars. Length capped at 253 (max DNS label length per RFC 1035).
#: Rejected §7 W1 audit "reuse _SAFE_TOKEN" verdict on inspection: _SAFE_TOKEN
#: is stricter than the plan claimed (lowercase-only, no ``.`` or ``_``) and
#: would reject legitimate hostnames like the default node fqdn.
_SAFE_HOSTLIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")

#: Returning verbs the dashboard may run captured (Lane 1) via /api/run. The
#: ``anl`` flag says whether the verb reaches ANL through the tunnel, so the UI
#: can gate those behind an explicit confirm and never auto-run them.
INFO_VERBS: dict[str, dict] = {
    "list-tools": {"anl": False},   # static local list of supported CLI tools
    "status": {"anl": True},        # polls the tunnel + /v1/models when up
    "list-models": {"anl": True},   # fetches models from argo-proxy
}

#: Verbs the web UI HARD-BLOCKS from spawning into an embedded panel (D-031).
#: ``run`` and ``client`` launch a user-facing tool whose lifecycle should not
#: be tied to a browser tab; closing the tab would kill the tool session. Both
#: verbs must go through /api/launch-external (or the CLI). ``client`` is also
#: removed from the web UI's verb dropdown entirely (the split-verb story
#: connect+configure+run is what the web UI teaches); CLI keeps ``client``.
EMBEDDED_BLOCKED_VERBS: frozenset[str] = frozenset({"run", "client"})


def _panel_for_verb(verb: str) -> PanelSlot | None:
    """Return the named panel a verb routes to, or ``None`` if not embedded.

    D-031 routing rules:
      * ``connect`` -> Channel (persistent, owns SSH master).
      * ``configure`` / ``setup`` / ``tunnel`` -> Utility (ephemeral).
      * ``run`` / ``client`` -> None (hard-blocked from embedded; must go
        external).
      * Info verbs (``status`` / ``list-models`` / ``list-tools``) go through
        /api/run (Lane-1 captured), not the ws endpoint at all.
    """
    if verb in CHANNEL_PANEL_VERBS:
        return "channel"
    if verb in UTILITY_PANEL_VERBS:
        return "utility"
    return None


def build_launch_argv(
    verb: str,
    *,
    cli_tool: str | None = None,
    scope: str | None = None,
    port: int | None = None,
    node: str | None = None,
    user: str | None = None,
    jump_host: str | None = None,
    no_jump: bool = False,
) -> list[str]:
    """Assemble a validated engine argv for a browser-initiated terminal launch.

    Only a known verb plus a constrained set of flags is allowed; free-form
    passthrough is deliberately not supported. Raises ``ValueError`` on anything
    outside the allowlist so the caller can reject the launch.

    D-032 additions (2026-07-15) -- ``node``, ``user``, ``jump_host``,
    ``no_jump`` map 1:1 to the engine's ``--node`` / ``--user`` /
    ``--jump-host`` / ``--no-jump`` flags. Empty string means "let the
    engine resolve it" (per plan §10.2): we simply omit the flag rather
    than passing an empty value that the engine would reject at parse time
    (--jump-host "" is a die per §7 A9). For the explicit "skip the jump
    host entirely" intent, callers pass ``no_jump=True`` (mirrors the
    checkbox in the launcher popover added in C4).
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
    if node:
        if not _SAFE_HOSTLIKE.match(node):
            raise ValueError(f"bad node: {node!r}")
        argv += ["--node", node]
    if user:
        if not _SAFE_HOSTLIKE.match(user):
            raise ValueError(f"bad user: {user!r}")
        argv += ["--user", user]
    if jump_host:
        if not _SAFE_HOSTLIKE.match(jump_host):
            raise ValueError(f"bad jump_host: {jump_host!r}")
        argv += ["--jump-host", jump_host]
    if no_jump:
        argv += ["--no-jump"]
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

    @app.get("/icon.svg")
    async def icon_svg() -> Response:
        # The app icon (constellation) from package-data, for the in-app About.
        data = files("argo_anywhere").joinpath("assets/icon.svg").read_bytes()
        return Response(data, media_type="image/svg+xml")

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        # D-031 multi-instance guard: include a package marker + pid + app cwd
        # so a second argo-anywhere trying to bind the same port can identify
        # the incumbent as a sibling (vs. some unrelated service on that port)
        # and produce a helpful error. Also useful for `pgrep`-style ops.
        from ..status import app_cwd_display

        return JSONResponse({
            "status": "ok",
            "app": "argo-anywhere",  # marker other argo instances key off
            "package_version": argo_anywhere.__version__,
            "pid": os.getpid(),
            "app_cwd_short": app_cwd_display(),
        })

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

    @app.get("/api/models")
    def api_models() -> JSONResponse:
        """Structured model catalog from ``list-models --format json``.

        This reaches ANL through the tunnel (same as
        ``POST /api/run/list-models``) and is only called on an explicit
        user action in the dashboard's Models panel. Returns a shape the
        UI can render directly -- no client-side text parsing:

        .. code-block:: json

            {
              "models": [
                {"internal_name": "gpt4o", "id": "gpt-4o",
                 "provider": "openai", "modalities": "text+image->text",
                 "in_opencode_config": true},
                ...
              ],
              "opencode_config_present": true,
              "counts": {"total": 30, "in_config": 5, "orphan": 0},
              "note": "The 'in_opencode_config' flag is per-tool: it "
                      "reflects the OpenCode config's models array, "
                      "not whether the model works with other CLI tools "
                      "(Claude Code, aider, ...)."
            }

        The rewording from ``configured`` -> ``in_opencode_config`` +
        the explicit ``note`` fixes a user-facing ambiguity (bug
        2026-07-13): the raw column just said "no", making Claude 4.8
        look mis-configured for Claude Code when it's really just
        absent from the OpenCode picker's model list -- which is
        irrelevant to Claude Code / aider / others.
        """
        import json as _json

        try:
            result = run_engine(
                ["list-models", "--format", "json"], timeout=45,
            )
        except subprocess.TimeoutExpired:
            return JSONResponse(
                {"error": "list-models timed out (channel down?)"},
                status_code=504,
            )
        if result.returncode != 0:
            return JSONResponse(
                {
                    "error": (result.stderr or result.stdout or "").strip()
                             or f"list-models exited {result.returncode}",
                    "returncode": result.returncode,
                },
                status_code=502,
            )
        try:
            raw = _json.loads(result.stdout or "[]")
        except ValueError as exc:
            return JSONResponse(
                {"error": f"malformed JSON from list-models: {exc}"},
                status_code=502,
            )
        # Whether the OpenCode config was consulted at all: the engine
        # includes the ``configured`` key on every row iff a config was
        # present; when absent it's silently dropped from the JSON rows.
        opencode_present = bool(raw) and "configured" in raw[0]
        models: list[dict] = []
        counts = {"total": 0, "in_config": 0, "orphan": 0}
        for row in raw:
            entry = {
                "internal_name": row.get("internal_name"),
                "id": row.get("id"),
                "provider": row.get("provider"),
                "modalities": row.get("modalities"),
            }
            if opencode_present:
                cfg = row.get("configured")
                entry["in_opencode_config"] = (cfg == "yes")
                entry["is_orphan"] = (cfg == "orphan")
                if cfg == "yes":
                    counts["in_config"] += 1
                elif cfg == "orphan":
                    counts["orphan"] += 1
            models.append(entry)
            counts["total"] += 1
        return JSONResponse({
            "models": models,
            "opencode_config_present": opencode_present,
            "counts": counts,
            "note": (
                "'in_opencode_config' reflects the OpenCode config's "
                "models array only. It does NOT indicate whether a "
                "model works with Claude Code, aider, or other tools -- "
                "those consult argo-proxy directly."
            ),
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

    @app.post("/api/preview-launch")
    def api_preview_launch(payload: dict) -> JSONResponse:
        """D-032 (2026-07-15): reflect back what argo WOULD run given the
        launcher popover's current inputs.

        Purely reflective -- no SSH connection is attempted.
        ``ssh -G`` is non-authenticating; 2s timeout guards against
        user-config Match-exec hangs. See src/argo_anywhere/web/preview.py
        for the full security contract.

        Request body: ``{node, user, jump_host, no_jump}`` (all optional).
        Response shape:
          * ``{"state": "cached", <field>: {"value": ..., "source": ...}, ...}``
            when all inputs are empty AND caches exist (pre-Launch reassurance).
          * ``{"state": "empty"}`` when all inputs are empty AND no caches.
          * ``{"state": "partial", ...}`` when some inputs given but no node.
          * ``{"state": "unresolved"}`` when node given but ssh -G failed.
          * ``{"state": "resolved", "hostname": ..., "user": ...,
             "proxyjump": ..., "our_extra_jump_args": [...],
             "divergences": [...]}``: full resolution.
        """
        from .preview import (
            DEFAULT_ANL_JUMP,
            reflect_jump_args,
            run_ssh_G,
        )

        node = (payload.get("node") or "").strip()
        user = (payload.get("user") or "").strip()
        jump_host = (payload.get("jump_host") or "").strip()
        no_jump = bool(payload.get("no_jump"))

        # Server-side validation (per §7 C6 audit): reject anything with
        # shell-hostile chars before ssh -G sees it. Defense-in-depth --
        # subprocess.run with a list is injection-safe by construction,
        # but hygiene says validate first.
        for name, val in (("node", node), ("user", user),
                          ("jump_host", jump_host)):
            if val and not _SAFE_HOSTLIKE.match(val):
                return JSONResponse(
                    {"error": f"bad {name}: contains disallowed characters"},
                    status_code=400,
                )

        # W13: empty inputs -> show cached defaults (or "empty" if no cache).
        if not node and not user and not jump_host and not no_jump:
            from ..status import STATE_DIR

            cached_node = ""
            cached_user = ""
            try:
                cached_node = (STATE_DIR / "node").read_text().strip()
            except OSError:
                pass
            try:
                cached_user = (STATE_DIR / "user").read_text().strip()
            except OSError:
                pass
            if cached_node or cached_user:
                return JSONResponse({
                    "state": "cached",
                    "hostname": {"value": cached_node, "source": "cache" if cached_node else "unset"},
                    "user": {"value": cached_user, "source": "cache" if cached_user else "unset"},
                    "proxyjump": {"value": DEFAULT_ANL_JUMP, "source": "default"},
                })
            return JSONResponse({"state": "empty"})

        # W13: partial input (username or jump-host but no node) -> can't
        # ssh -G without a target; return what we have.
        if not node:
            return JSONResponse({
                "state": "partial",
                "user": {"value": user, "source": "input"} if user else None,
                "jump_host": {"value": jump_host, "source": "input"} if jump_host else None,
                "no_jump": no_jump,
            })

        # Resolve via ssh -G. Returns None on timeout / non-zero exit / bad
        # input; collapse those to "unresolved" (never leak stderr to the
        # response, per §7 W3).
        result = run_ssh_G(node)
        if result is None:
            return JSONResponse({"state": "unresolved"})

        # A6 amendment (2026-07-15 live-verify): ssh -G returns rc=0 for
        # ANY syntactically-valid hostname, filling in defaults for
        # unknown targets (hostname=input, user=$USER, proxyjump=empty).
        # Before this check, a bogus alias like "xyzzy-42" got a false
        # state=resolved response with $USER as the "resolved user." Use
        # SshGResult.is_meaningful_alias to distinguish "real ssh_config
        # entry" from "bare hostname with default values."
        is_alias, detection_reason = result.is_meaningful_alias(node)
        if not is_alias:
            # No meaningful ssh_config entry for this target -- treat as
            # a bare hostname. argo will still try (per the pre-D-032
            # flow); UI can show "argo will connect using its defaults."
            return JSONResponse({
                "state": "bare_hostname",
                "hostname": node,   # what argo will target
                "note": "no meaningful ~/.ssh/config entry for this target; "
                        "argo will use its defaults (jump host + your "
                        "explicit --user if given, else prompt)",
            })

        # Divergence detection: user's explicit input differs from what
        # ssh_config says. Load-bearing for the auto-expand-on-divergence
        # UX (Q10 decision).
        divergences = []
        if user and result.user and user != result.user:
            divergences.append({
                "field": "user",
                "yours": user,
                "ssh_config": result.user,
            })
        if jump_host and result.proxyjump and jump_host != result.proxyjump:
            divergences.append({
                "field": "jump_host",
                "yours": jump_host,
                "ssh_config": result.proxyjump,
            })

        # Resolve the effective ANL_JUMP for the reflection (--jump-host
        # explicit input beats the default; --no-jump takes precedence
        # over both).
        anl_jump = jump_host or DEFAULT_ANL_JUMP
        # Resolve the effective user for the reflection: caller's explicit
        # --user wins; else ssh-config's User; else empty (engine would
        # prompt at runtime).
        effective_user = user or result.user or ""

        our_jump_args = reflect_jump_args(
            effective_user,
            node,
            anl_jump=anl_jump,
            no_jump=no_jump,
            ssh_g_result=result,
        )

        return JSONResponse({
            "state": "resolved",
            "hostname": result.hostname,
            "user": result.user,
            "proxyjump": result.proxyjump,
            "our_extra_jump_args": our_jump_args,
            "divergences": divergences,
            "detection_reason": detection_reason,
        })

    @app.get("/api/ssh-hosts")
    def api_ssh_hosts(refresh: int = 0) -> JSONResponse:
        """D-032 (2026-07-15): enumerate ssh_config Host aliases for the
        launcher's node-field datalist.

        Cached at process lifetime; ``?refresh=1`` re-reads the file. The
        parse is a pure filesystem read + textual Include expansion --
        NEVER calls ssh. Zero IP-block risk. See
        ``argo_anywhere.web.ssh_hosts.parse_ssh_config_hosts`` for the
        full contract.
        """
        from .ssh_hosts import parse_ssh_config_hosts

        cache = getattr(app.state, "ssh_hosts_cache", None)
        if cache is None or refresh:
            cache = parse_ssh_config_hosts()
            app.state.ssh_hosts_cache = cache
        return JSONResponse({"hosts": cache})

    @app.post("/api/launch-external")
    def api_launch_external(
        verb: str,
        cli_tool: str | None = None,
        scope: str | None = None,
        port: int | None = None,
        terminal: str | None = None,
        cwd: str | None = None,
        node: str | None = None,       # D-032 (2026-07-15)
        user: str | None = None,       # D-032
        jump_host: str | None = None,  # D-032
        no_jump: bool = False,         # D-032 (checkbox in launcher)
    ) -> JSONResponse:
        # Open the chosen verb in a NEW native terminal window the user owns
        # (independent of the web server; not tracked in the registry). The
        # window runs the console script on a real TTY -- full-fidelity Duo /
        # monitor / prompts.
        from ..external_terminal import (
            console_command_verified,
            open_external_terminal,
        )

        # D-031 Task 3: validate the launcher-supplied cwd (defense in depth).
        # For external launches an existing dir is required now -- there's no
        # window in which the UI can offer to create it (that flow is ws-only
        # via the 409-then-confirm dance).
        resolved_cwd: str | None = None
        if cwd is not None and cwd.strip():
            cv = validate_cwd(cwd)
            if not cv.ok:
                return JSONResponse(
                    {"error": cv.detail, "verdict": cv.verdict.value},
                    status_code=STATUS_FOR_VERDICT[cv.verdict],
                )
            resolved_cwd = str(cv.resolved)
            # D-031 Task 7: hard-block enforcement server-side (defense in depth).
            fr = check_forbid(resolved_cwd, scope)
            if fr.verdict is ForbidVerdict.HARD_BLOCK:
                return JSONResponse(
                    {"error": fr.reason, "verdict": "hard_block"},
                    status_code=403,
                )

        try:
            engine_argv = build_launch_argv(
                verb, cli_tool=cli_tool, scope=scope, port=port,
                node=node, user=user, jump_host=jump_host, no_jump=no_jump,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Fixed 2026-07-13: with the server running under a Python that has
        # neither argo-anywhere installed nor an ``argo-anywhere`` script next
        # to it (e.g. a dev-mode run from PYTHONPATH=src under miniconda while
        # the user's pipx install lives elsewhere), console_command() would
        # previously fall back to ``<sys.executable> -m argo_anywhere`` which
        # then failed in the spawned terminal with ``No module named
        # argo_anywhere``. Now: console_command_verified() runs a
        # ``<prefix> --version`` probe with a scrubbed env so an invocation
        # that would only succeed with our PYTHONPATH gets caught HERE
        # rather than in a terminal window the user can't inspect.
        prefix, probe_error = console_command_verified()
        if probe_error is not None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": (
                        "cannot spawn an argo-anywhere CLI in the new terminal: "
                        f"{probe_error}. Install with ``pipx install "
                        "argo-anywhere`` OR run the web server from an "
                        "interpreter where the package is importable "
                        "WITHOUT PYTHONPATH (a proper install)."
                    ),
                },
                status_code=500,
            )

        result = open_external_terminal(
            prefix + engine_argv,
            terminal=terminal,
            cwd=resolved_cwd,
        )
        # D-031 Task 5: touch MRU on a successful external launch. Best-effort.
        if result.get("ok") and resolved_cwd is not None:
            try:
                _state.touch_mru(resolved_cwd)
            except OSError:
                pass
        return JSONResponse(result, status_code=200 if result.get("ok") else 502)

    @app.get("/api/check-forbid")
    def api_check_forbid(path: str, scope: str | None = None) -> JSONResponse:
        """Pre-flight the scope-conditional forbid-list without spawning.

        D-031 Task 7: the UI calls this on every launch when scope == "project"
        so it can show the soft-warn confirm modal (or refuse hard-blocks
        cleanly) before opening the ws. Returns:
          - 200 + ``verdict: allow`` on ok;
          - 200 + ``verdict: soft_warn`` (UI shows confirm modal);
          - 403 + ``verdict: hard_block`` (UI shows an unrecoverable error).
        For scope != "project" always returns 200 + ``allow`` (short-circuit).
        """
        result = check_forbid(path, scope)
        status_code = 403 if result.verdict is ForbidVerdict.HARD_BLOCK else 200
        return JSONResponse(
            {"verdict": result.verdict.value, "reason": result.reason},
            status_code=status_code,
        )

    @app.get("/api/validate-cwd")
    def api_validate_cwd(path: str) -> JSONResponse:
        """Pre-flight the launcher-cwd validator without spawning anything.

        D-031 Task 3: the ws endpoint closes with an opaque 1008 on a bad cwd
        (WebSockets can't reasonably return a JSON error). The UI's embedded
        launch path calls this first so it can show the same 400 / 409 UX as
        the external-terminal path (which gets structured JSON directly).
        Read-only; never touches disk.
        """
        cv = validate_cwd(path)
        return JSONResponse(
            {
                "ok": cv.ok,
                "verdict": cv.verdict.value,
                "detail": cv.detail,
                "resolved": str(cv.resolved) if cv.resolved else None,
            },
            status_code=STATUS_FOR_VERDICT[cv.verdict],
        )

    @app.post("/api/mkdir")
    def api_mkdir(path: str) -> JSONResponse:
        """Create a missing directory the launcher wants to spawn into (D-031 D2c).

        Called by the UI's confirm modal after the launch endpoint returned
        409 (verdict ``missing``). The path goes through the same validator
        (must be absolute, must NOT exist as anything else) before creation.
        On success returns 201 + the resolved path; on any failure returns
        the matching 4xx from :data:`STATUS_FOR_VERDICT`.
        """
        cv = validate_cwd(path)
        # A path we can create must be MISSING (absolute, syntactically valid,
        # nothing on disk yet). Every other verdict is a rejection.
        if cv.verdict is CwdVerdict.OK:
            return JSONResponse(
                {"error": "already exists", "path": str(cv.resolved)},
                status_code=409,
            )
        if cv.verdict is not CwdVerdict.MISSING:
            return JSONResponse(
                {"error": cv.detail, "verdict": cv.verdict.value},
                status_code=STATUS_FOR_VERDICT[cv.verdict],
            )
        assert cv.resolved is not None  # MISSING guarantees a resolved path
        try:
            cv.resolved.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            return JSONResponse(
                {"error": f"mkdir failed: {exc}", "path": str(cv.resolved)},
                status_code=500,
            )
        return JSONResponse({"created": str(cv.resolved)}, status_code=201)

    @app.get("/api/state")
    def api_get_state() -> JSONResponse:
        """Return the persisted web-UI state (MRU cwd list, divider, theme).

        Called on page load so the launcher can pre-fill the cwd datalist +
        restore the divider position + apply the saved theme (D-031 Task 5 + 5.5).
        Never fails: read errors return the default state.
        """
        return JSONResponse(_state.load_state())

    @app.post("/api/state")
    async def api_set_state(request: Request) -> JSONResponse:
        """Merge a small patch into the persisted state (D-031 Task 5 + 5.5).

        Body: JSON object with any of ``divider_pct`` / ``theme`` / ``mru``.
        Unknown keys are silently dropped (see :func:`state.update_state`).
        Returns the new full state on success; 400 for non-JSON.
        """
        try:
            patch = await request.json()
        except Exception:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if not isinstance(patch, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        try:
            new_state = _state.update_state(patch)
        except OSError as exc:
            return JSONResponse({"error": f"write failed: {exc}"}, status_code=500)
        return JSONResponse(new_state)

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
        resolved_cwd = None  # populated when the caller supplied a valid cwd
        if q.get("verb"):
            verb = q["verb"]
            # D-031 hard-block: run/client can't spawn in an embedded panel;
            # browser tab close would kill the tool session.
            if verb in EMBEDDED_BLOCKED_VERBS:
                await ws.close(code=1008)  # policy violation
                return
            # D-031 Task 3: validate the launcher-supplied cwd server-side
            # (defense in depth; the UI already refused blanks + relatives).
            # Blank cwd is still accepted at the ws level for backward compat
            # with pre-Task-3 callers (test_ws_bridge... uses no cwd); the UI's
            # own workflow always sends one.
            raw_cwd = q.get("cwd")
            if raw_cwd is not None and raw_cwd.strip():
                cv = validate_cwd(raw_cwd)
                if not cv.ok:
                    # 1008 policy-violation; the browser's onerror will surface it.
                    # The UI does its own pre-flight validation, so this path only
                    # fires for scripted clients or an out-of-date UI.
                    await ws.close(code=1008)
                    return
                resolved_cwd = cv.resolved
                # D-031 Task 7: enforce hard-blocks server-side (the UI's
                # /api/check-forbid catches these too; this is the safety net).
                # Soft-warn is UI-only -- the server accepts and lets the user's
                # explicit "continue" from the modal proceed.
                fr = check_forbid(str(cv.resolved), q.get("scope"))
                if fr.verdict is ForbidVerdict.HARD_BLOCK:
                    await ws.close(code=1008)
                    return
            try:
                argv = build_launch_argv(
                    verb,
                    cli_tool=q.get("cli_tool"),
                    scope=q.get("scope"),
                    port=int(q["port"]) if q.get("port") else None,
                    node=q.get("node"),            # D-032 (2026-07-15)
                    user=q.get("user"),            # D-032
                    jump_host=q.get("jump_host"),  # D-032
                    no_jump=q.get("no_jump") in ("1", "true", "on"),  # D-032
                )
            except (ValueError, TypeError):
                await ws.close(code=1008)  # rejected launch spec
                return
        else:
            argv = list(engine_argv)
            verb = None  # engine_argv default; no panel routing

        # D-031 panel routing: pick a named slot from the verb; fall back to
        # slot-less (legacy) register when the caller didn't name a verb.
        panel: PanelSlot | None = None
        if verb is not None:
            panel = _panel_for_verb(verb)
            # For Channel-owning verbs (currently just ``connect``), refuse
            # if a live Channel session already exists. The UI's launcher
            # offers a "stop + replace" secondary path that stops the old
            # session via /api/sessions/<id>/stop and then reconnects; this
            # server-side check is the safety net if the UI is bypassed.
            if panel == "channel" and registry.panel_alive("channel"):
                await ws.close(code=1008)  # channel already up
                return

        await ws.accept()
        # D-031 Task 4: thread the validated cwd into PtySession -> subprocess
        # so the engine (and any AI CLI tool it spawns) starts in the user's
        # chosen directory. ``resolved_cwd`` is None when the caller didn't
        # supply a cwd (legacy / test / default engine_argv path); Popen(cwd=None)
        # inherits the parent's cwd, matching pre-D-031 behavior.
        session = PtySession(
            argv,
            dimensions=(24, 80),
            cwd=str(resolved_cwd) if resolved_cwd else None,
        )
        # D-031 Task 5: record successful cwd usage in the MRU list. Best-
        # effort (a broken write should never abort the launch); errors are
        # swallowed here + surfaced elsewhere via /api/state failures.
        if resolved_cwd is not None:
            try:
                _state.touch_mru(str(resolved_cwd))
            except OSError:
                pass
        if panel is not None:
            managed, evicted = registry.register_panel(session, panel)
            # Utility replacement: the previous Utility session (if any) was
            # evicted from the slot mapping but not the id map. Stop + reap
            # it so we don't leak PIDs.
            if evicted is not None and evicted.session.isalive():
                try:
                    evicted.session.close()
                except Exception:
                    pass
                registry.unregister(evicted.id)
        else:
            managed = registry.register(session)

        detached = False
        try:
            # Channel owners aren't force-killed on ws-close: keep them running so
            # the SSH master (and the tunnel) survives -> no repeat Duo.
            await run_pty_bridge(ws, session, terminate_on_close=not managed.owns_channel)
            if managed.owns_channel and session.isalive():
                detached = True
                _drain_detached(managed)
        finally:
            if not detached:
                registry.unregister(managed.id)
                session.close()

    def _drain_detached(managed) -> None:
        """Keep a detached channel-owning session alive after its ws closed.

        Its ``connect`` keeps printing to the PTY; with no reader the buffer fills
        and the process blocks. So we drain (discard) the PTY on the event loop,
        and reap + unregister the session when it finally exits (or is stopped via
        ``/api/sessions/<id>/stop``, which closes the pty and triggers EOF here).
        """
        session = managed.session
        fd = session.fileno()
        loop = asyncio.get_running_loop()
        managed.detached = True

        def _drain() -> None:
            try:
                data = session.read()
            except OSError:
                data = b""
            if data:
                return
            try:  # EOF -> the child exited (or was stopped): clean up.
                loop.remove_reader(fd)
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass
            registry.unregister(managed.id)

        loop.add_reader(fd, _drain)

    return app


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8799,
    engine_argv: Sequence[str] = ("connect",),
    reload: bool = False,
) -> None:
    """Run the web UI under uvicorn (blocking).

    ``reload`` (dev only): pass the app as an import string + watch
    ``src/argo_anywhere/`` so code edits restart uvicorn without a manual
    Ctrl-C. The engine invocation for reload mode is fixed to the default
    ("connect") because the factory-based reload path can't easily thread
    the CLI's ``--engine`` argument through; users who need a non-default
    engine invocation should run without ``--reload``. Requires
    ``watchfiles``.
    """
    import uvicorn

    print(f"[argo-anywhere web] engine: {' '.join(engine_argv)!r}")
    print(f"[argo-anywhere web] open http://{host}:{port}")
    if reload:
        # In reload mode uvicorn must be able to re-import the app fresh, so
        # pass an app import string + a factory. The reload watchdog picks
        # up file changes under the package directory.
        import argo_anywhere as _pkg
        from pathlib import Path
        pkg_dir = Path(_pkg.__file__).resolve().parent
        print(f"[argo-anywhere web] --reload watching {pkg_dir} (dev mode)")
        uvicorn.run(
            "argo_anywhere.web.app:create_app",
            factory=True,
            host=host, port=port, log_level="info",
            reload=True, reload_dirs=[str(pkg_dir)],
        )
        return
    app = create_app(engine_argv=engine_argv)
    uvicorn.run(app, host=host, port=port, log_level="info")
