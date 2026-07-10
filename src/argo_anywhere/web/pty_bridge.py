"""Bridge a WebSocket to a :class:`argo_anywhere.driver.PtySession`.

Wire protocol (matches ``web/static/index.html``, lifted from the P1 spike):

- **client -> server**: raw text/bytes are keystrokes written to the PTY; a text
  frame beginning with ``\\x00CTRL`` carries a JSON control message
  (``{"op": "resize", "rows", "cols"}`` or ``{"op": "signal", "sig": "INT"}``).
- **server -> client**: raw bytes are PTY output; a final text frame beginning
  with ``\\x00EXIT`` carries ``{"exitstatus": <int|null>}``.

The session must already be spawned and the WebSocket already accepted; this
function pumps until either side closes and does NOT close the session (the
caller owns its lifecycle).
"""

from __future__ import annotations

import asyncio
import json

from starlette.websockets import WebSocket, WebSocketDisconnect

from ..driver import PtySession

CTRL_PREFIX = "\x00CTRL"
EXIT_PREFIX = "\x00EXIT"


async def run_pty_bridge(ws: WebSocket, session: PtySession) -> None:
    """Pump bytes between ``ws`` and ``session`` until either side closes."""
    loop = asyncio.get_running_loop()
    fd = session.fileno()
    closed = asyncio.Event()

    def _on_readable() -> None:
        # The event loop calls this when the PTY master has bytes (or EOF).
        data = session.read()
        if not data:
            loop.remove_reader(fd)
            closed.set()
            return
        asyncio.ensure_future(_safe_send_bytes(data))

    async def _safe_send_bytes(data: bytes) -> None:
        try:
            await ws.send_bytes(data)
        except Exception:
            closed.set()

    def _handle_control(payload: str) -> None:
        try:
            ctl = json.loads(payload)
        except Exception:
            return
        op = ctl.get("op")
        if op == "resize":
            try:
                session.set_winsize(int(ctl.get("rows", 24)), int(ctl.get("cols", 80)))
            except Exception:
                pass
        elif op == "signal" and ctl.get("sig") == "INT":
            session.interrupt()

    async def _pump_client_to_pty() -> None:
        try:
            while not closed.is_set():
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                data = msg.get("bytes")
                if text is not None:
                    if text.startswith(CTRL_PREFIX):
                        _handle_control(text[len(CTRL_PREFIX):])
                    else:
                        session.write(text.encode())
                elif data is not None:
                    session.write(data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            closed.set()

    loop.add_reader(fd, _on_readable)
    pump = asyncio.ensure_future(_pump_client_to_pty())

    await closed.wait()

    # Teardown: stop reading, reap the child, report exit status to the client.
    try:
        loop.remove_reader(fd)
    except Exception:
        pass
    pump.cancel()

    exit_status = session.exitstatus
    if session.isalive():
        session.terminate(force=True)
        try:
            exit_status = session.wait(timeout=3)
        except Exception:
            exit_status = session.exitstatus

    try:
        await ws.send_text(EXIT_PREFIX + json.dumps({"exitstatus": exit_status}))
    except Exception:
        pass
    try:
        await ws.close()
    except Exception:
        pass
