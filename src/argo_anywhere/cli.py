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
  argo-anywhere install-launcher [--desktop] [--app-bundle]
                                 Install a double-clickable launcher for the
                                 web UI (macOS .command / .app; Linux .desktop
                                 + .sh) so you can start it without a terminal.
                                 Removed by 'argo-anywhere uninstall'.
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
    footprint. Then we sweep the **package-only residue** the engine doesn't
    know about -- the double-clickable launchers ``install-launcher`` created
    (D-030b's ``artifact`` tier). We never self-delete the package; we print the
    pip/pipx command instead (only when the teardown actually ran / previewed,
    i.e. rc == 0 -- an aborted uninstall shouldn't nudge the user to remove the
    package).
    """
    rc = _run_engine_passthrough(["uninstall", *args])
    if rc != 0:
        return rc  # aborted / failed teardown: don't touch residue or nudge

    # Package-only residue: the launchers (the engine's manifest never saw them).
    _sweep_launcher_residue(dry_run="--dry-run" in args)
    print(
        f"\nto remove the package itself, run:\n    {_package_removal_command()}",
        file=sys.stderr,
    )
    return 0


def _sweep_launcher_residue(*, dry_run: bool) -> None:
    """Remove the launcher artifacts ``install-launcher`` created (dry-run aware)."""
    from .launcher import installed_artifacts, remove_path

    for path in installed_artifacts():
        if dry_run:
            print(f"[dry-run] would remove launcher: {path}", file=sys.stderr)
            continue
        try:
            remove_path(path)
            print(f"removed launcher: {path}", file=sys.stderr)
        except OSError as exc:
            print(f"could not remove {path}: {exc}", file=sys.stderr)


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


def _brand_macos_app() -> None:
    """Brand the macOS app menu + About panel for ``argo-anywhere app`` unbundled.

    Cocoa reads the menu-bar name and the standard "About" panel text from the
    running process's bundle info dict — "Python" / empty for an unbundled Python
    process. We patch the main bundle's info dict (via pyobjc, a pywebview dep on
    macOS) BEFORE the menu is built, so pywebview's default app menu gets the
    right name + a populated About. (The icon is set separately, after launch, by
    :func:`_apply_macos_dock_icon`.) No-op off macOS and if pyobjc isn't
    importable; best-effort, never blocks the window. When launched from the
    install-launcher ``.app`` bundle these come from Info.plist instead. Modeled
    on scrollback's ``_brand_macos_app``.
    """
    if sys.platform != "darwin":
        return
    repo = "https://github.com/a-attia/argo-anywhere"
    try:
        from Foundation import NSBundle  # provided by pyobjc on macOS

        bundle = NSBundle.mainBundle()
        if bundle is not None:
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info is not None:
                info["CFBundleName"] = "argo-anywhere"
                info["CFBundleDisplayName"] = "argo-anywhere"
                # Fields the standard "About argo-anywhere" panel reads:
                info["CFBundleShortVersionString"] = __version__
                info["CFBundleVersion"] = __version__
                info["NSHumanReadableCopyright"] = (
                    "Run AI coding CLIs against the ANL Argo gateway from anywhere.\n"
                    + repo.replace("https://", "")
                )
    except Exception:
        pass


# Keep a reference so the Obj-C About handler isn't garbage-collected while the
# menu item points at it.
_about_handler = None


def _install_macos_app_chrome() -> None:
    """After the Cocoa app is up: set the Dock icon and give the standard
    "About argo-anywhere" panel our icon + a clickable repo link.

    Runs via ``webview.start(func=…)`` (after launch, so it isn't overridden by
    pywebview's init). For an UNBUNDLED process the About panel keeps the
    executable's icon (Python) unless we pass an explicit ``ApplicationIcon`` in
    the panel options — so we rewire the standard About menu item to a handler
    that opens the panel with our icon. No-op off macOS / without pyobjc;
    best-effort (try/except) so it never crashes the window. Modeled on
    scrollback's ``_install_macos_about_link``.
    """
    global _about_handler
    if sys.platform != "darwin":
        return
    try:
        from importlib.resources import as_file, files

        from AppKit import (  # type: ignore
            NSApplication,
            NSAttributedString,
            NSFont,
            NSFontAttributeName,
            NSImage,
        )
        from Foundation import NSObject, NSURL  # type: ignore

        from . import __version__

        img = None
        try:
            with as_file(files("argo_anywhere").joinpath("assets/icon.icns")) as icon:
                img = NSImage.alloc().initWithContentsOfFile_(str(icon))
        except Exception:
            img = None

        app = NSApplication.sharedApplication()
        if img is not None:
            app.setApplicationIconImage_(img)  # Dock icon

        repo = "https://github.com/a-attia/argo-anywhere"
        credits = NSAttributedString.alloc().initWithString_attributes_(
            "Run AI coding CLIs against the ANL Argo gateway from anywhere.\n\n"
            "Repository:  ",
            {NSFontAttributeName: NSFont.systemFontOfSize_(11)},
        )
        link = NSAttributedString.alloc().initWithString_attributes_(
            "github.com/a-attia/argo-anywhere",
            {"NSLink": NSURL.URLWithString_(repo),
             NSFontAttributeName: NSFont.systemFontOfSize_(11)},
        )
        full = credits.mutableCopy()
        full.appendAttributedString_(link)

        class _AboutHandler(NSObject):
            def showAbout_(self, _sender):
                opts = {
                    "Credits": full,
                    "ApplicationName": "argo-anywhere",
                    "Version": __version__,
                    "ApplicationVersion": __version__,
                }
                if img is not None:
                    opts["ApplicationIcon"] = img  # override the Python icon
                NSApplication.sharedApplication().orderFrontStandardAboutPanelWithOptions_(opts)

        _about_handler = _AboutHandler.alloc().init()

        def _rewire_about() -> bool:
            # Re-point the standard "About" item to our handler. Returns True once
            # done. pywebview may not have built its menu yet when this first runs
            # (that's why the Dock icon lands but this didn't) -- so we also retry
            # on a short delay below.
            try:
                main_menu = app.mainMenu()
                if main_menu is None or main_menu.numberOfItems() == 0:
                    return False
                app_menu = main_menu.itemAtIndex_(0).submenu()
                if app_menu is None:
                    return False
                for i in range(app_menu.numberOfItems()):
                    item = app_menu.itemAtIndex_(i)
                    action = item.action()
                    title = str(item.title() or "")
                    if (action is not None and str(action) == "orderFrontStandardAboutPanel:") \
                            or title.startswith("About"):
                        item.setTarget_(_about_handler)
                        item.setAction_(b"showAbout:")
                        return True
            except Exception:
                pass
            return False

        if not _rewire_about():
            # Menu not built yet -> retry a few times on the main run loop.
            try:
                from PyObjCTools import AppHelper  # type: ignore

                for delay in (0.3, 0.8, 1.5, 3.0):
                    AppHelper.callLater(delay, _rewire_about)
            except Exception:
                pass
    except Exception:
        pass


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
            import webbrowser

            import webview

            # JS<->Python bridge (window.pywebview.api). Cross-platform.
            class _AppBridge:
                def __init__(self) -> None:
                    self.window = None  # set after the window is created

                def open_link(self, target: str) -> str:
                    # Open external links (the repo) in the user's REAL browser
                    # instead of trapping them in the app webview.
                    if isinstance(target, str) and target.startswith(("http://", "https://")):
                        webbrowser.open(target)
                        return "opened"
                    return "rejected"

                def to_background(self) -> str:
                    # "Run in background": keep the app (server + SSH channel)
                    # running but out of the way -- minimise the window instead
                    # of quitting. Reopen from the Dock / taskbar. Quit (X /
                    # Cmd-Q) still shuts down cleanly.
                    try:
                        if self.window is not None:
                            self.window.minimize()
                            return "backgrounded"
                    except Exception:
                        pass
                    return "unavailable"

            # On macOS a non-bundled Python process shows "Python" in the menu
            # bar with an empty About and the generic icon; brand it before the
            # Cocoa app/menu is built. No-op elsewhere (Windows/Linux use the
            # window title) and when run from the .app bundle (Info.plist wins).
            _brand_macos_app()

            _bridge = _AppBridge()
            _window = webview.create_window(
                "argo-anywhere", url, js_api=_bridge,
                width=1200, height=820, min_size=(900, 600),
            )
            _bridge.window = _window
            print(f"argo-anywhere: native window on {url}")
            # func runs after the Cocoa app is up -> Dock icon + About panel stick.
            webview.start(_install_macos_app_chrome)  # blocks until window closes
            _shutdown_web(app, server, thread)
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
    _shutdown_web(app, server, thread)
    return 0


def _shutdown_web(app, server, thread) -> None:
    """Shut the app down cleanly when the window closes / Ctrl-C.

    Closing the native window returns from ``webview.start``; without this the
    daemon server thread and any managed PTY children (a held ``connect`` + its
    SSH master, kept alive by the ws-detach) would be killed mid-flight as the
    process exits -- which orphans the ssh master and macOS reports as "quit
    unexpectedly". So we first stop every managed session (tearing the channel
    down cleanly), then let the server thread unwind.
    """
    try:
        reg = getattr(app.state, "registry", None)
        if reg is not None:
            for m in reg.list():
                try:
                    m.session.close()
                except Exception:
                    pass
    except Exception:
        pass
    server.should_exit = True
    try:
        thread.join(timeout=4)
    except Exception:
        pass


def _cmd_install_launcher(args: Sequence[str]) -> int:
    """Install a double-clickable launcher for the web UI (scrollback-style).

    Creates the OS-appropriate launcher(s) that run ``argo-anywhere app`` with
    the current interpreter baked in, so a non-terminal user can start the UI by
    double-clicking. Registered in the footprint, so ``argo-anywhere uninstall``
    removes them.
    """
    from pathlib import Path

    from .launcher import install

    parser = argparse.ArgumentParser(
        prog="argo-anywhere install-launcher",
        description="Install a double-clickable launcher for the web UI.",
    )
    parser.add_argument("--dest", help="override the install directory (Desktop / app-menu by default).")
    parser.add_argument("--desktop", action="store_true", help="only the Desktop launcher.")
    parser.add_argument("--app-bundle", action="store_true", help="only the macOS .app bundle.")
    ns = parser.parse_args(list(args))

    created = install(
        dest=Path(ns.dest) if ns.dest else None,
        desktop=ns.desktop,
        app_bundle=ns.app_bundle,
    )
    if not created:
        print("install-launcher: nothing created.", file=sys.stderr)
        return 1
    for p in created:
        print(f"created: {p}")
    print(
        "\nDouble-click it to open argo-anywhere (a native window if the [app] extra\n"
        "is installed, otherwise your browser). Remove with 'argo-anywhere uninstall'."
    )
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
    if argv and argv[0] == "install-launcher":
        return _cmd_install_launcher(argv[1:])
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
