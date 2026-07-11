"""``argo-anywhere`` console-script entry point.

Dispatch model:

- **Package-level flags/verbs** handled here: ``--version``, ``--print-script``
  (the D-026 inspect-and-fork escape hatch), and ``web`` (launch the local
  web-terminal UI; needs the ``[web]`` extra).
- **Everything else** is a bash-engine invocation and is passed through to the
  vendored engine on the user's **real terminal** (stdin/stdout/stderr
  inherited). That gives full fidelity: Duo prompts, the live monitor, and the
  three interactive prompts all work exactly as running the ``.sh`` directly.
  (The two-lane driver in :mod:`argo_anywhere.driver` -- captured Lane 1 / PTY
  Lane 2 -- exists for the *web* and programmatic callers, where there is no
  inherited controlling terminal.)

``help`` / ``-h`` passes through to the engine, then appends a short note about
the package-only extras the engine doesn't know about.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shlex
import subprocess
import sys
from typing import Sequence

from . import __version__
from ._engine import ENGINE_FILENAME, engine_bytes, engine_path, packaged_env

_PACKAGE_ADDENDUM = f"""
argo-anywhere (Python package) additions beyond the engine's help:
  argo-anywhere app [--port N] [--browser]
                                 Open the web UI in a native desktop window
                                 (needs the [app] extra: pip install
                                 'argo-anywhere[app]'); falls back to your
                                 browser if pywebview isn't installed.
  argo-anywhere web [--host H] [--port N] [--engine "VERB ARGS"]
                                 Serve the local web UI (needs the [web] extra:
                                 pip install 'argo-anywhere[web]').
  argo-anywhere info [--json]    Local status: package + engine versions,
                                 loopback listeners, and argo-anywhere's own
                                 on-disk footprint (no ANL contact).
  argo-anywhere uninstall [...]  Remove argo-anywhere's on-disk footprint
                                 (config restore via the manifest; tiered per
                                 --restore-configs/--remove-binaries/--remote;
                                 --dry-run), then print the pip/pipx command to
                                 remove the package itself.
  argo-anywhere --print-script   Emit the raw bash engine to stdout
                                 (e.g. > {ENGINE_FILENAME}); inspect-and-fork.
  argo-anywhere --version        Print the package version.
"""


def _run_engine_passthrough(args: Sequence[str]) -> int:
    """Run the engine with the current process's stdio (full-fidelity).

    The ``ARGO_ANYWHERE_PACKAGED=1`` marker (D-030a) tells the engine it is
    driven by the package, so its own bootstrap / self-install / self-update
    stay dormant -- pipx/pip owns the runtime.
    """
    with engine_path() as script:
        proc = subprocess.run(["bash", str(script), *args], env=packaged_env())
    return proc.returncode


def _cmd_info(args: Sequence[str]) -> int:
    """Print local status: package + engine versions and loopback listeners.

    Purely local -- no ANL contact (does NOT poll channel /health, which would
    traverse an established tunnel). `--json` emits machine-readable output.
    """
    import json

    from .footprint import footprint, format_size
    from .status import cached_state, local_listeners, package_info

    info = package_info()
    state = cached_state()
    # Scope the listener view to argo-anywhere's own footprint: the cached
    # tunnel port + the default web-UI port. (local_listeners() with no filter
    # would dump every loopback listener on the machine.)
    ports = sorted({p for p in (state["port"], 8799) if p})
    listeners = [ln.as_dict() for ln in local_listeners(ports)]
    fp = footprint()  # D-030b: argo-anywhere's own on-disk footprint

    if "--json" in args:
        print(json.dumps(
            {
                "package": info,
                "cached": state,
                "listeners": listeners,
                "footprint": [e.as_dict() for e in fp],
            },
            indent=2,
        ))
        return 0

    print(
        f"argo-anywhere {info['package_version']}  "
        f"(engine {info['engine_version']}, sha {info['engine_sha256_short']})"
    )
    print(f"python {info['python_version']} on {info['platform']}")
    print(
        "cached channel: "
        f"user={state['user'] or '-'} node={state['node'] or '-'} "
        f"port={state['port'] or '-'}"
    )
    by_port = {ln["port"]: ln for ln in listeners}
    if state["port"]:
        ln = by_port.get(state["port"])
        print(
            f"  tunnel :{state['port']}  "
            + (f"UP (pid {ln['pid']}, {ln['command']})" if ln else "down (no local listener)")
        )
    web = by_port.get(8799)
    if web:
        print(f"  web UI :8799  UP (pid {web['pid']}, {web['command']})")

    # D-030b: on-disk footprint (argo-anywhere's own files; agent data is never
    # here -- we only read-and-restore those).
    print("on-disk footprint (argo-anywhere's own files; your agent data is never here):")
    if not fp:
        print("  (nothing created yet)")
    else:
        for e in fp:
            print(f"  [{e.tier:10}] {format_size(e.size_bytes()):>9}  {e.path}")
            print(f"               {e.description}")
        print("  remove with 'argo-anywhere uninstall' (restores client configs + sweeps")
        print("  these); then 'pipx uninstall argo-anywhere' to remove the package.")
    return 0


def _package_removal_command() -> str:
    """The command that removes the package itself, guessed from how it was
    installed (scrollback-style). We never run it: a process can't reliably
    uninstall the package it is executing from, and the right tool depends on
    the install method."""
    exe = (sys.executable or "").replace("\\", "/")
    if "/pipx/" in exe or "/.local/pipx/" in exe:
        return "pipx uninstall argo-anywhere"
    return "pip uninstall argo-anywhere"


def _cmd_uninstall(args: Sequence[str]) -> int:
    """Package-level uninstall (D-030c): delegate the tiered teardown to the
    engine, then print how to remove the package itself.

    The engine's ``uninstall`` (D-025) owns the real work -- manifest-driven
    config restore, binary removal, remote venv, and the live-channel ownership
    guard. Because :func:`_run_engine_passthrough` sets
    ``ARGO_ANYWHERE_PACKAGED=1`` (D-030a), the engine skips its canonical-dir
    removal (there is none under the package) and sweeps the rest of the
    footprint. We never self-delete the package; we print the pip/pipx command
    instead (only when the teardown actually ran / previewed, i.e. rc == 0 --
    an aborted uninstall shouldn't nudge the user to remove the package).
    """
    rc = _run_engine_passthrough(["uninstall", *args])
    if rc == 0:
        print(
            f"\nto remove the package itself, run:\n    {_package_removal_command()}",
            file=sys.stderr,
        )
    return rc


def _cmd_web(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="argo-anywhere web",
        description="Launch the local web-terminal UI (loopback-only).",
    )
    parser.add_argument(
        "--host", default=os.environ.get("ARGO_ANYWHERE_WEB_HOST", "127.0.0.1")
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ARGO_ANYWHERE_WEB_PORT", "8799")),
    )
    parser.add_argument(
        "--engine",
        default=os.environ.get("ARGO_ANYWHERE_WEB_ENGINE", "connect"),
        help="engine invocation the browser terminal runs (shell-split; default: connect).",
    )
    ns = parser.parse_args(list(args))

    try:
        from .web.app import serve
    except ModuleNotFoundError:
        print(
            "argo-anywhere web: the web UI needs the [web] extra.\n"
            "  Install it with:  pip install 'argo-anywhere[web]'",
            file=sys.stderr,
        )
        return 1

    serve(host=ns.host, port=ns.port, engine_argv=tuple(shlex.split(ns.engine)))
    return 0


def _cmd_app(args: Sequence[str]) -> int:
    """Open the web UI in a native desktop window (pywebview), server and all.

    Starts the web server on loopback in a background thread, then opens a native
    window pointed at it. Falls back to the default browser if pywebview (the
    ``[app]`` extra) isn't installed or ``--browser`` is passed.
    """
    parser = argparse.ArgumentParser(
        prog="argo-anywhere app",
        description="Open the local web UI in a native desktop window (loopback-only).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARGO_ANYWHERE_WEB_PORT", "8799")))
    parser.add_argument("--engine", default=os.environ.get("ARGO_ANYWHERE_WEB_ENGINE", "connect"))
    parser.add_argument("--browser", action="store_true", help="use the default browser instead of a native window")
    ns = parser.parse_args(list(args))

    try:
        from .web.app import create_app
    except ModuleNotFoundError:
        print(
            "argo-anywhere app: the UI needs the web server.\n"
            "  Install it with:  pip install 'argo-anywhere[app]'",
            file=sys.stderr,
        )
        return 1

    import threading
    import time
    import urllib.request

    import uvicorn

    app = create_app(engine_argv=tuple(shlex.split(ns.engine)))
    config = uvicorn.Config(app, host=ns.host, port=ns.port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://{ns.host}:{ns.port}"
    for _ in range(100):  # wait up to ~10s for the server to answer
        try:
            urllib.request.urlopen(f"{url}/healthz", timeout=0.5)  # noqa: S310 (loopback)
            break
        except OSError:
            time.sleep(0.1)

    if not ns.browser:
        try:
            import webview

            webview.create_window("argo-anywhere", url, width=1200, height=820, min_size=(900, 600))
            print(f"argo-anywhere: native window on {url}")
            webview.start()  # blocks on the main thread until the window closes
            server.should_exit = True
            return 0
        except ModuleNotFoundError:
            print(
                "(native window needs the [app] extra: pip install 'argo-anywhere[app]'; "
                "opening your browser instead)",
                file=sys.stderr,
            )

    import webbrowser

    webbrowser.open(url)
    print(f"argo-anywhere: serving {url}  (Ctrl-C to stop)")
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Package-level fast paths.
    if argv and argv[0] in ("--version", "-V"):
        print(f"argo-anywhere {__version__}")
        return 0
    if "--print-script" in argv:
        try:
            sys.stdout.buffer.write(engine_bytes())
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            # A downstream reader (head/less) closed the pipe early. Redirect
            # stdout to devnull so the interpreter's shutdown flush doesn't
            # re-raise, then exit cleanly like a normal Unix tool.
            with contextlib.suppress(OSError):
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    if argv and argv[0] == "app":
        return _cmd_app(argv[1:])
    if argv and argv[0] == "web":
        return _cmd_web(argv[1:])
    if argv and argv[0] == "info":
        return _cmd_info(argv[1:])
    if argv and argv[0] == "uninstall":
        return _cmd_uninstall(argv[1:])

    # help/-h: show the engine's help, then the package addendum.
    if argv and argv[0] in ("help", "-h", "--help"):
        rc = _run_engine_passthrough(argv)
        print(_PACKAGE_ADDENDUM, file=sys.stderr)
        return rc

    # Everything else is an engine invocation (bare argv -> engine default client).
    return _run_engine_passthrough(argv)


if __name__ == "__main__":
    raise SystemExit(main())
