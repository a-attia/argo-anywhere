"""P1a spike: PTY <-> WebSocket <-> xterm.js plumbing proof.

Goal of this spike (P1a): prove that a real interactive command running on a
pseudo-terminal can be driven entirely from an xterm.js terminal in the
browser -- keystrokes flow in, output (incl. prompts) flows out, resize works,
and clean exit is detected. NO ANL / NO SSH here (avoids any IP-block risk per
the engine's CSPO defense). The command to run is chosen via the SPIKE_CMD env
var so we can swap in progressively-more-realistic stand-ins, and finally the
real `argo_anywhere.sh connect` (that switch is P1b, done at the keyboard).

Run:
    SPIKE_CMD='python3 -i' spike/.venv/bin/python spike/server.py
    # then open http://127.0.0.1:8799
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import struct
import termios
import fcntl
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ptyprocess import PtyProcess

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"

# The command the PTY runs. Default is a harmless local interactive stand-in.
# Progression for P1a:
#   'python3 -i'                 -> interactive REPL (prompts, line editing)
#   'bash -i'                    -> interactive shell
#   'ssh localhost'             -> exercises a real ssh PTY password/host prompt (local, safe)
# P1b (at the keyboard, real ANL):
#   'bash /path/to/argo_anywhere.sh connect'  -> real Duo prompt
DEFAULT_CMD = "python3 -i"
SPIKE_CMD = os.environ.get("SPIKE_CMD", DEFAULT_CMD)

HOST = os.environ.get("SPIKE_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPIKE_PORT", "8799"))

# DNS-rebinding guard (scrollback-style): only accept Host headers that name
# loopback. The read/exec API is unauthenticated, so we refuse requests whose
# Host is an attacker-controlled name resolving to 127.0.0.1.
ALLOWED_HOSTS = {
    f"127.0.0.1:{PORT}", f"localhost:{PORT}",
    "127.0.0.1", "localhost",
}

app = FastAPI()


@app.middleware("http")
async def _host_guard(request, call_next):
    from starlette.responses import PlainTextResponse

    host = request.headers.get("host", "")
    if host and host not in ALLOWED_HOSTS:
        return PlainTextResponse("forbidden host", status_code=403)
    return await call_next(request)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico")
async def favicon():
    # Silence the browser's automatic favicon request (was a noisy 404).
    from starlette.responses import Response

    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Push a window size to the PTY so full-screen prompts render correctly."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


@app.websocket("/ws")
async def pty_ws(ws: WebSocket) -> None:
    # Host guard on the WS upgrade too (middleware only covers HTTP).
    host = ws.headers.get("host", "")
    if host and host not in ALLOWED_HOSTS:
        await ws.close(code=1008)
        return
    await ws.accept()

    argv = shlex.split(SPIKE_CMD)
    # Spawn the command on a fresh PTY. env carries TERM so xterm.js gets
    # sensible escape sequences.
    env = dict(os.environ)
    env.setdefault("TERM", "xterm-256color")
    proc = PtyProcess.spawn(argv, env=env, dimensions=(24, 80))
    fd = proc.fd

    loop = asyncio.get_running_loop()
    closed = asyncio.Event()

    def _on_readable() -> None:
        # Called by the event loop when the PTY has bytes for us.
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if not data:
            loop.remove_reader(fd)
            closed.set()
            return
        # Ship raw bytes to the browser terminal as-is.
        asyncio.ensure_future(_safe_send_bytes(ws, data))

    async def _safe_send_bytes(sock: WebSocket, data: bytes) -> None:
        try:
            await sock.send_bytes(data)
        except Exception:
            closed.set()

    loop.add_reader(fd, _on_readable)

    async def _pump_client_to_pty() -> None:
        # Read messages from the browser: raw text = keystrokes; JSON control
        # frames = resize / signal.
        try:
            while not closed.is_set():
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                data = msg.get("bytes")
                if text is not None:
                    if text.startswith("\x00CTRL"):
                        _handle_control(text[5:])
                        continue
                    os.write(fd, text.encode())
                elif data is not None:
                    os.write(fd, data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            closed.set()

    def _handle_control(payload: str) -> None:
        try:
            ctl = json.loads(payload)
        except Exception:
            return
        if ctl.get("op") == "resize":
            rows = int(ctl.get("rows", 24))
            cols = int(ctl.get("cols", 80))
            try:
                _set_winsize(fd, rows, cols)
            except Exception:
                pass
        elif ctl.get("op") == "signal":
            sig = ctl.get("sig")
            if sig == "INT":
                try:
                    proc.kill(signal.SIGINT)
                except Exception:
                    pass

    pump = asyncio.ensure_future(_pump_client_to_pty())

    # Wait until either side closes.
    await closed.wait()

    # Teardown: stop reading, terminate the child, report exit status.
    try:
        loop.remove_reader(fd)
    except Exception:
        pass
    pump.cancel()
    exit_status = None
    try:
        if proc.isalive():
            proc.terminate(force=True)
        proc.wait()
        exit_status = proc.exitstatus
    except Exception:
        pass
    try:
        await ws.send_text(
            "\x00EXIT" + json.dumps({"exitstatus": exit_status})
        )
    except Exception:
        pass
    try:
        await ws.close()
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    print(f"[spike] PTY command: {SPIKE_CMD!r}")
    print(f"[spike] open http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
