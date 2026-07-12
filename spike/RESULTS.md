# P1 spike results — consolidated

> **Consolidated 2026-07-10 into
> [`notes/impl_python_webui.md`](../notes/impl_python_webui.md).**
> That note is now the single source of truth for the Python-package + web-UI
> work (plan, proven results, decisions, P0 state, residuals). This file is a
> stub; the full original P1a/P1b/cold-Duo results are in git history.

**One-line summary:** the P1 gate — *can the whole `connect` flow, including a
cold Duo challenge, be driven from a browser terminal over a WebSocket-bridged
PTY?* — **PASSED** (P1a plumbing + P1b real engine 2026-07-09; live cold-Duo
observation 2026-07-10). See the consolidated note's
[What is proven](../notes/impl_python_webui.md#what-is-proven) section.

The proof-of-concept code that produced these results still lives in this
directory (`server.py`, `smoke_test*.py`, `static/`) as the reference the P0
web layer was lifted from.
