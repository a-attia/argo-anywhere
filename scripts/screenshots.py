"""Regenerate the README screenshots from synthetic (scrubbed) demo data.

Maintainers only. Requires the ``dev`` extra (which pulls in ``rich`` and
``playwright``), plus (for ``client.png``) an SVG->PNG converter
(``rsvg-convert`` or ImageMagick ``magick``) and (for ``web.png``) a one-time
Playwright Chromium download:

    pip install -e ".[dev]"
    python -m playwright install chromium     # one-time, for the web shot
    python scripts/screenshots.py             # both shots
    python scripts/screenshots.py client      # just the client shot
    python scripts/screenshots.py web         # just the web shot

Produces, under ``assets/screenshots/``:
  - client.svg / client.png : the client "ALL GREEN" status box, rendered via
    rich (no browser).
  - web.png : the web-UI dashboard (channel UP), rendered by serving the REAL
    app with the data endpoints (``/api/status`` etc.) overridden by faked
    JSON, then screenshotting it with headless Chromium. No ANL contact; no
    live channel needed.

All identity is shown as ``<angle-bracket>`` placeholders -- no real username,
node, or credentials. See ``PRELUDE`` / ``_SECTIONS`` and ``_FAKE_STATUS``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "screenshots"
_SRC = Path(__file__).resolve().parent.parent / "src"

# All ANL-/user-specific identifiers are shown as <angle-bracket> placeholders,
# not plausible fake values, so the screenshot reads unambiguously as a template.
# The default port 64742 is public (documented throughout the README), so it is
# shown as-is.
PRELUDE = r"""[argo-anywhere] Using ANL username: <ANL-username>
[argo-anywhere] Using port: 64742  (source: cached port)
[argo-anywhere] Selected node: <ANL-compute-node>
[argo-anywhere] Opening multiplexed SSH master (Duo prompt expected once)...
[ ok ]   master ready (subsequent SSH calls will reuse this connection)
[argo-anywhere] Copying engine to <ANL-compute-node>:~/.argo-anywhere.sh
[argo-anywhere] Running server bootstrap on <ANL-compute-node>...
[ ok ] argo-proxy: argo-proxy 3.2.1
[ ok ] Server is up on <ANL-compute-node>:64742.
[argo-anywhere] Opening tunnel: localhost:64742 -> <ANL-compute-node>:64742
[ ok ] Tunnel is live. argo-proxy reachable at http://localhost:64742/v1"""

# The status-box content, as (title, verdict, sections). We render it below with
# the SAME algorithm the engine's print_summary_box uses (SECTION 4 of
# argo-anywhere.sh): inner width = max visible line width + 2; each row is
# "V<space>content<pad>V"; rules are ML + MH*inner + MR. Unicode glyphs match
# BOX_STYLE=unicode.
_TITLE = "argo-anywhere  --  status summary"
_VERDICT = "ALL GREEN  -  tunnel up, proxy healthy, 44 model(s)"
_SECTIONS: list[tuple[str, list[str]]] = [
    ("Connection", [
        "Local listener   : pid <pid> bound to 127.0.0.1:64742",
        "Proxy /health    : healthy  (http://localhost:64742/health)",
        "Tunnel uptime    : 00:17",
    ]),
    ("Models", [
        "Available        : 44 at /v1/models  (e.g. argo:gpt-4o, argo:o3-mini)",
        "OpenCode models  : 27 configured (27 reachable)",
    ]),
    ("Configuration", [
        "Port             : 64742",
        "Cached username  : <ANL-username>",
        "Cached node      : <ANL-compute-node>",
    ]),
    ("Next step", [
        "Run 'opencode' in another terminal.",
    ]),
]
_EPILOGUE = r"""[argo-anywhere] Channel is up; point any OpenAI-compatible client at
[argo-anywhere]   http://localhost:64742/v1  with Authorization: Bearer <ANL-username>"""

# Unicode box glyphs (BOX_STYLE=unicode in the engine).
_TL, _TR, _BL, _BR = "╔", "╗", "╚", "╝"
_H, _V, _ML, _MR, _MH = "═", "║", "╠", "╣", "─"


def _draw_box() -> list[str]:
    """Reproduce print_summary_box (unicode) exactly, returning box lines."""
    body: list[tuple[str, bool]] = []  # (text, is_section_label)
    for label, rows in _SECTIONS:
        body.append((label, True))
        body += [(r, False) for r in rows]

    maxw = max(
        [len(_TITLE), len(_VERDICT)] + [len(t) for t, _ in body]
    )
    inner = maxw + 2  # 1 space padding each side

    def row(content: str) -> str:
        # "V space content pad V" -- pad fills to inner-1 after the leading space.
        pad = inner - 1 - len(content)
        return f"{_V} {content}{' ' * max(pad, 0)}{_V}"

    hbar, mbar = _H * inner, _MH * inner
    out = [f"{_TL}{hbar}{_TR}", row(_TITLE), f"{_ML}{mbar}{_MR}", row(_VERDICT),
           f"{_ML}{mbar}{_MR}"]
    for i, (text, is_label) in enumerate(body):
        if is_label and i != 0:
            out.append(f"{_ML}{mbar}{_MR}")
        out.append(row(text))
    out.append(f"{_BL}{hbar}{_BR}")
    return out


# Section-label texts (rendered blue like the engine's C_BLU rows).
_SECTION_LABELS = frozenset(
    [_TITLE] + [label for label, _ in _SECTIONS]
)


# ANL-/user-specific values are shown as <angle-bracket> placeholders (not fake
# values), so they read unambiguously as "substitute this". We deliberately do
# NOT color them inline: rich's export_svg does not preserve exact monospace
# cell width across mid-line style-run boundaries, so a colored <...> span
# breaks the box-border alignment. The angle brackets alone mark them clearly.


def _log_line(line: str):
    """Colorize an engine log line (prelude/epilogue) to match the palette.

    Built as a SINGLE Text with stylize() sub-ranges (never append()) so rich's
    SVG export produces one continuous run per line -- multiple appended spans
    make export_svg insert visible gaps at the boundaries.
    """
    from rich.text import Text

    t = Text(line)
    if line.startswith("[ ok ]"):
        t.stylize("bold green")
    elif line.startswith("[argo-anywhere]"):
        t.stylize("cyan", 0, len("[argo-anywhere]"))
    return t


def _box_line(line: str):
    """Colorize one drawn box line: dim borders, blue labels, green verdict.

    One Text with stylize() sub-ranges only (no append()) -- see _log_line for
    why (SVG export gaps at multi-span boundaries).
    """
    from rich.text import Text

    t = Text(line)
    label = line[1:-1].strip() if len(line) >= 2 else line
    if set(line) <= {_TL, _TR, _BL, _BR, _ML, _MR, _H, _MH}:
        t.stylize("dim green")  # a pure border/rule row
    else:
        # Dim the two border glyphs; color the interior content.
        t.stylize("dim green", 0, 1)
        t.stylize("dim green", len(line) - 1, len(line))
        if label == _VERDICT:
            t.stylize("bold green", 1, len(line) - 1)
        elif label in _SECTION_LABELS:
            t.stylize("bold blue", 1, len(line) - 1)
    return t


def render_client() -> list[Path]:
    """Render the ALL GREEN box to SVG (crisp) and PNG (for PyPI/GitHub)."""
    from rich.console import Console
    from rich.text import Text

    box = _draw_box()
    lines = (
        [_log_line(ln) for ln in PRELUDE.splitlines()]
        + [Text("")]
        + [_box_line(ln) for ln in box]
        + [_log_line(ln) for ln in _EPILOGUE.splitlines()]
    )

    # Width the console to the box + a little margin so nothing wraps.
    width = max(len(ln) for ln in box) + 4
    console = Console(record=True, width=width)
    console.print(Text("\n").join(lines))

    svg = OUT / "client.svg"
    svg.write_text(
        console.export_svg(title="argo-anywhere connect", font_aspect_ratio=0.61),
        encoding="utf-8",
    )
    png = _svg_to_png(svg)
    return [svg] + ([png] if png else [])


def _svg_to_png(svg: Path) -> Path | None:
    """Convert SVG -> PNG. Prefer headless Chromium (crisp browser font
    rendering at 2x, matching web.png); fall back to rsvg-convert / ImageMagick.

    PyPI's README renderer ignores SVG, so a PNG is required for the project
    page; GitHub renders both. We ship the SVG too (crisper on GitHub at zoom).
    """
    png = svg.with_suffix(".png")

    # Preferred: Chromium at device_scale_factor=2 -- sharper text than librsvg.
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        sync_playwright = None
    if sync_playwright is not None:
        # Read the SVG's pixel size to set an exact viewport (no scrollbars).
        import re

        txt = svg.read_text(encoding="utf-8")
        mw = re.search(r'width="(\d+(?:\.\d+)?)"', txt)
        mh = re.search(r'height="(\d+(?:\.\d+)?)"', txt)
        w = int(float(mw.group(1))) if mw else 1000
        h = int(float(mh.group(1))) if mh else 1000
        html = (
            "<!doctype html><meta charset=utf-8>"
            "<style>html,body{margin:0;padding:0;background:#0c0c0c}"
            f"img{{display:block;width:{w}px;height:{h}px}}</style>"
            f'<img src="{svg.name}">'
        )
        html_path = svg.with_suffix(".render.html")
        html_path.write_text(html, encoding="utf-8")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": w, "height": h}, device_scale_factor=2
                )
                page.goto(html_path.as_uri(), wait_until="networkidle")
                page.wait_for_timeout(150)
                page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": w, "height": h})
                browser.close()
            return png
        finally:
            html_path.unlink(missing_ok=True)

    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-z", "3", "-o", str(png), str(svg)], check=True)
        return png
    if shutil.which("magick"):
        subprocess.run(["magick", "-density", "288", str(svg), str(png)], check=True)
        return png
    print(
        "  (no chromium / rsvg-convert / magick; wrote SVG only -- convert to "
        "PNG manually for the README)",
        file=sys.stderr,
    )
    return None


# -- web-UI screenshot (real app + faked data, via headless Chromium) ------

# The faked /api/status the dashboard renders. Shapes match app.py exactly:
#   package: {package_version, engine_version, ...}
#   cached:  {user, node, port}
#   listeners: [{port, command, pid}]   (tunnelUp := a listener on cached.port)
#   sessions:  [{id, verb, alive, owns_channel, detached, uptime_s, ...}]
# Identity is <placeholder>; the default port 64742 is public.
_FAKE_STATUS = {
    "package": {"package_version": "3.0.0", "engine_version": "2.2.1-dev"},
    "cached": {"user": "<ANL-username>", "node": "<ANL-compute-node>", "port": 64742},
    "listeners": [
        {"port": 64742, "command": "ssh", "pid": 0},
        {"port": 8799, "command": "python", "pid": 0},
    ],
    "sessions": [
        {
            "id": "connect-1", "verb": "connect", "alive": True,
            "owns_channel": True, "detached": False, "uptime_s": 1037,
            "exitstatus": None,
        },
    ],
}
_FAKE_HEALTH = {"up": True, "status": "healthy", "latency_ms": 12, "port": 64742}


def _serve_faked_app(port: int):
    """Start the REAL FastAPI app with the data endpoints overridden by faked
    JSON, on a background uvicorn thread. Returns (server, thread)."""
    import threading

    sys.path.insert(0, str(_SRC))
    from fastapi.responses import JSONResponse

    from argo_anywhere.web.app import create_app

    app = create_app(engine_argv=("connect",))

    # Override the data endpoints AFTER create_app so ours win (FastAPI uses the
    # first matching route; adding to the front of the table shadows the app's).
    # Starlette Route endpoints take the request positionally.
    async def _status(_request):
        return JSONResponse(_FAKE_STATUS)

    async def _sessions(_request):
        return JSONResponse({"sessions": _FAKE_STATUS["sessions"]})

    async def _health(_request):
        return JSONResponse(_FAKE_HEALTH)

    app.router.routes.insert(0, _route("/api/status", _status))
    app.router.routes.insert(0, _route("/api/sessions", _sessions))
    app.router.routes.insert(0, _route("/api/health", _health))

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


def _route(path, endpoint):
    from starlette.routing import Route

    return Route(path, endpoint, methods=["GET"])


def render_web() -> Path | None:
    """Serve the real app with faked data and screenshot the dashboard."""
    import time
    import urllib.request

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print(
            "  (playwright not installed; skipping web.png. "
            "pip install -e '.[dev]' && python -m playwright install chromium)",
            file=sys.stderr,
        )
        return None

    port = 8790
    server, _thread = _serve_faked_app(port)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):  # wait for the server
        try:
            urllib.request.urlopen(f"{base}/healthz", timeout=0.5)  # noqa: S310 (loopback)
            break
        except OSError:
            time.sleep(0.1)

    png = OUT / "web.png"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1200, "height": 820}, device_scale_factor=2
            )
            page.goto(base, wait_until="networkidle")
            # Let the dashboard's initial /api/status render settle. We care about
            # the monitor visual, not the embedded terminal, so we crop to the
            # rendered content height instead of the full (mostly-empty) viewport.
            page.wait_for_timeout(600)
            # The layout containers stretch to the full viewport height, so
            # measure the actual rendered content: the lowest bottom edge among
            # the header + monitor cards. Clip to that + a small margin so the
            # shot is tight (no big empty void below the cards).
            content_h = page.evaluate(
                "() => { let mb = 0;"
                " document.querySelectorAll('.topbar, .card').forEach("
                "   c => { mb = Math.max(mb, c.getBoundingClientRect().bottom); });"
                " return Math.ceil(mb); }"
            )
            page.screenshot(
                path=str(png),
                clip={"x": 0, "y": 0, "width": 1200, "height": content_h + 24},
            )
            browser.close()
    finally:
        server.should_exit = True
    return png


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    OUT.mkdir(parents=True, exist_ok=True)

    if which in ("all", "client"):
        for p in render_client():
            print(f"wrote {p.relative_to(OUT.parent.parent)}")
    if which in ("all", "web"):
        p = render_web()
        if p:
            print(f"wrote {p.relative_to(OUT.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
