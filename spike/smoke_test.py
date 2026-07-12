"""Headless plumbing smoke test for the P1a spike.

Drives the /ws WebSocket the same way the browser would (raw text keystrokes +
JSON control frames), against a PTY running a scripted interactive command, and
asserts the round-trip works: prompt appears, our input is echoed/processed,
computed output returns, resize is accepted, and clean exit is reported.

No ANL / no SSH. Run:
    spike/.venv/bin/python spike/smoke_test.py
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

PORT = 8798
CTRL = "\x00CTRL"
EXIT = "\x00EXIT"


async def run() -> int:
    # Use a scripted interactive command: prints a marker, reads a line, echoes
    # a computed answer, then exits. Exercises prompt-out / input-in / out-again.
    os.environ["SPIKE_CMD"] = (
        "python3 -u -c "
        "\"import sys; print('READY>'); "
        "x=sys.stdin.readline().strip(); "
        "print('ANSWER=' + str(int(x)*2)); "
        "sys.exit(7)\""
    )
    os.environ["SPIKE_PORT"] = str(PORT)

    from server import app  # imported after env is set

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.ensure_future(server.serve())

    # Wait for startup.
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "server did not start"

    saw_ready = False
    saw_answer = False
    exit_status = None
    sent_input = False

    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
            # Send a resize control frame first (browser does this on open).
            await ws.send(CTRL + json.dumps({"op": "resize", "rows": 30, "cols": 100}))

            buf = ""
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    print("TIMEOUT waiting for PTY output", file=sys.stderr)
                    break

                if isinstance(msg, bytes):
                    buf += msg.decode(errors="replace")
                else:
                    if msg.startswith(EXIT):
                        info = json.loads(msg[len(EXIT):])
                        exit_status = info.get("exitstatus")
                        break
                    buf += msg

                if "READY>" in buf and not saw_ready:
                    saw_ready = True
                if saw_ready and not sent_input:
                    # Respond to the prompt like a user typing "21<Enter>".
                    await ws.send("21\n")
                    sent_input = True
                if "ANSWER=42" in buf:
                    saw_answer = True
    finally:
        server.should_exit = True
        await server_task

    ok = saw_ready and saw_answer and exit_status == 7
    print("--- P1a plumbing smoke test ---")
    print(f"  prompt received (READY>):     {saw_ready}")
    print(f"  input processed (ANSWER=42):  {saw_answer}")
    print(f"  clean exit reported (7):      {exit_status == 7} (status={exit_status})")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
