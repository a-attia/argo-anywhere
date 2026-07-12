"""Resize smoke test for the P1a spike.

Reproduces the class of bug seen in the browser (full-screen program misdraws
because the PTY was left at the default 24x80 while the client rendered larger).
We send a resize control frame to 40x120, then run a command that reports the
PTY's actual window size via the TIOCGWINSZ ioctl, and assert it matches.

No ANL / no SSH. Run:
    spike/.venv/bin/python spike/smoke_test_resize.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import uvicorn
import websockets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PORT = 8797
CTRL = "\x00CTRL"
EXIT = "\x00EXIT"

TARGET_ROWS = 40
TARGET_COLS = 120


async def run() -> int:
    # A command that: waits briefly for the resize to land, reads its own PTY
    # window size, prints it as SIZE=<rows>x<cols>, then exits.
    os.environ["SPIKE_CMD"] = (
        "python3 -u -c "
        "\"import time,sys,struct,fcntl,termios; time.sleep(0.5); "
        "s=struct.unpack('HHHH', fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\\0'*8)); "
        "print('SIZE=%dx%d' % (s[0], s[1])); sys.exit(0)\""
    )
    os.environ["SPIKE_PORT"] = str(PORT)

    from server import app

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.ensure_future(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "server did not start"

    got_size = None
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
            # Resize BEFORE the child reads its size (child sleeps 0.5s).
            await ws.send(
                CTRL + json.dumps({"op": "resize", "rows": TARGET_ROWS, "cols": TARGET_COLS})
            )
            buf = ""
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    break
                if isinstance(msg, bytes):
                    buf += msg.decode(errors="replace")
                elif msg.startswith(EXIT):
                    break
                else:
                    buf += msg
                if "SIZE=" in buf:
                    line = [x for x in buf.splitlines() if "SIZE=" in x][0]
                    got_size = line.split("SIZE=", 1)[1].strip()
                    break
    finally:
        server.should_exit = True
        await server_task

    want = f"{TARGET_ROWS}x{TARGET_COLS}"
    ok = got_size == want
    print("--- P1a resize smoke test ---")
    print(f"  requested size: {want}")
    print(f"  PTY reported:   {got_size}")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
