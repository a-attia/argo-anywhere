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
import os
import shlex
import subprocess
import sys
from typing import Sequence

from . import __version__
from ._engine import ENGINE_FILENAME, engine_bytes, engine_path

_PACKAGE_ADDENDUM = f"""
argo-anywhere (Python package) additions beyond the engine's help:
  argo-anywhere web [--host H] [--port N] [--engine "VERB ARGS"]
                                 Launch the local web-terminal UI (needs the
                                 [web] extra: pip install 'argo-anywhere[web]').
  argo-anywhere info [--json]    Local status: package + engine versions and
                                 loopback listeners (no ANL contact).
  argo-anywhere --print-script   Emit the raw bash engine to stdout
                                 (e.g. > {ENGINE_FILENAME}); inspect-and-fork.
  argo-anywhere --version        Print the package version.
"""


def _run_engine_passthrough(args: Sequence[str]) -> int:
    """Run the engine with the current process's stdio (full-fidelity)."""
    with engine_path() as script:
        proc = subprocess.run(["bash", str(script), *args])
    return proc.returncode


def _cmd_info(args: Sequence[str]) -> int:
    """Print local status: package + engine versions and loopback listeners.

    Purely local -- no ANL contact (does NOT poll channel /health, which would
    traverse an established tunnel). `--json` emits machine-readable output.
    """
    import json

    from .status import cached_state, local_listeners, package_info

    info = package_info()
    state = cached_state()
    # Scope the listener view to argo-anywhere's own footprint: the cached
    # tunnel port + the default web-UI port. (local_listeners() with no filter
    # would dump every loopback listener on the machine.)
    ports = sorted({p for p in (state["port"], 8799) if p})
    listeners = [ln.as_dict() for ln in local_listeners(ports)]

    if "--json" in args:
        print(json.dumps(
            {"package": info, "cached": state, "listeners": listeners}, indent=2
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
    return 0


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


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Package-level fast paths.
    if argv and argv[0] in ("--version", "-V"):
        print(f"argo-anywhere {__version__}")
        return 0
    if "--print-script" in argv:
        sys.stdout.buffer.write(engine_bytes())
        sys.stdout.buffer.flush()
        return 0
    if argv and argv[0] == "web":
        return _cmd_web(argv[1:])
    if argv and argv[0] == "info":
        return _cmd_info(argv[1:])

    # help/-h: show the engine's help, then the package addendum.
    if argv and argv[0] in ("help", "-h", "--help"):
        rc = _run_engine_passthrough(argv)
        print(_PACKAGE_ADDENDUM, file=sys.stderr)
        return rc

    # Everything else is an engine invocation (bare argv -> engine default client).
    return _run_engine_passthrough(argv)


if __name__ == "__main__":
    raise SystemExit(main())
