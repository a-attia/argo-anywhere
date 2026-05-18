# Comparative audit: `argo-shim` ↔ `argo-anywhere`

*Created 2026-05-18 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Scope:
`argo-shim` v0.2.0 (Python; local HTTP proxy) compared against
`argo-anywhere` @ commit `108e5d6` / v2.2.0 (bash; SSH-tunnel
orchestrator). Compiled while landing Phase 4 (v2.2.0). This audit
sits alongside [`AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) (the
43-finding fresh-eyes audit; 42-of-43 closed at v2.2.0) and the
archived [`AUDIT_2026-05_pre-rebuild.md`](AUDIT_2026-05_pre-rebuild.md);
together those three audit documents are the complete design-decision
trail through v2.2.0.*

---

## Table of contents

- [Executive comparison (slide-ready)](#executive-comparison-slide-ready)
- [1. Architectural orientation](#1-architectural-orientation)
- [2. Verbatim audit](#2-verbatim-audit)
- [3. Scrutiny: what's right, what's wrong](#3-scrutiny-whats-right-whats-wrong)
  - [Verified-true claims](#verified-true-claims)
  - [Verified-wrong claims](#verified-wrong-claims)
  - [Reclassification: MUST / SHOULD / COULD / CANNOT](#reclassification-must--should--could--cannot)
- [4. Disagreements with the audit's recommendations](#4-disagreements-with-the-audits-recommendations)
- [5. Reverse direction: findings argo-shim should adopt](#5-reverse-direction-findings-argo-shim-should-adopt)
- [6. Adoption roadmap](#6-adoption-roadmap)
- [7. STATUS blocks (live tracker)](#7-status-blocks-live-tracker)

---

## Executive comparison (slide-ready)

A presentation-slide-sized summary. Copy this section verbatim into
a slide; the longer audit body below is the supporting evidence.

### One-sentence framing

**`argo-shim`** is a Python local HTTP proxy that intercepts every
Claude Code request between the AI tool and the SSH tunnel.
**`argo-anywhere`** is a bash SSH-tunnel orchestrator that
port-forwards straight through to `argo-proxy` on the compute node
and configures the local AI CLI tool to point at the forward.

They solve the same user problem (running AI coding tools against
the ANL Argo gateway from a laptop) from opposite layers of the
stack.

### What `argo-shim` does that `argo-anywhere` doesn't

| Capability | Why `argo-shim` can; `argo-anywhere` can't |
|:---|:---|
| Force `stream=true` on `/messages` requests + SSE reassembly | Local HTTP layer can rewrite the request body. **Already solved upstream** by `argo-proxy`'s `anthropic_stream_mode: force` default (v3.x). |
| Strip empty `thinking` blocks from cached turns | Same local-HTTP requirement. **Plausible upstream bug** but unconfirmed; would need a `Oaklight/argo-proxy` issue to verify. |
| Transparent per-request tunnel auto-recovery | Local HTTP layer can retry under a lock. `argo-anywhere`'s monitor reconnects within seconds; Claude Code retries on its own. Acceptable UX gap. |

### What `argo-anywhere` does that `argo-shim` doesn't

| Capability | Why it matters |
|:---|:---|
| **Persistent on-disk SSH-failure lock** with TTL + exponential backoff (D-012) | `argo-shim`'s in-memory tracker resets on restart and is circumventable. CSPO defense correctness is strictly better in `argo-anywhere`. |
| **`%r-%h-%p`** `ControlPath` tokens, not `%C` | `%C` proved fragile when `~/.ssh/config` rewrites jump-host names. `argo-shim` inherits the `%C` fragility bug. |
| **Multi-tool API contract** (`setup_<name>_cli_tool` + 4 peers per tool) | `argo-shim` is Claude-Code-first; OpenCode is bolted on. `argo-anywhere` adds new tools as ~5-function applications. |
| **Per-tool scope framework** (D-017/D-018/D-019) with conflict detection + `[k/s/a]` prompt | `argo-shim`'s `--no-auth` workaround is a blunt instrument. |
| **`status` / `stop` / `clean` / `update-models`** | `argo-shim` has only "run the shim"; status is manual `curl`, cleanup is manual `ps`+`grep`+`kill`. |
| **Jump-host shell-restriction handling** | `argo-anywhere` opens the mux master against the compute node, not the jump host (`logins.cels.anl.gov` is shell-restricted). `argo-shim` would break if its destination was a jump host. |
| **Server-side persistence** (screen / tmux / nohup) | `argo-shim`'s upstream proxy dies when the UAN session ends. `argo-anywhere` keeps the proxy alive on the node. |

### Why we are NOT building `argo-anywhere`'s own local HTTP shim

1. **Single-file `curl`-and-run distribution is load-bearing** (D-001).
   Adding a background Python process means second lifecycle, second
   port, second crash mode, second cleanup target.
2. **The headline `argo-shim` advantage (stream forcing) is already
   solved upstream** by `argo-proxy` v3.x's `anthropic_stream_mode:
   force` default. `argo-anywhere` inherits the fix automatically.
3. **Transport-layer manipulation belongs at `argo-proxy`**, not in a
   second proxy layer on the laptop. Future fixes go upstream.

### Live-tested adoption decisions (v2.2.0 → v2.3)

| ID | Effort | Disposition |
|:---|:---|:---|
| **SH-04** | trivial | **v2.2.1** — inline `lsof`+`ps` in port-collision messages |
| **SH-02** | trivial | **v2.3** — `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"` in `settings.json` (needs upstream-source verification first) |
| **SH-03** | small | **v2.3** — `no_proxy` injection + `HTTP_PROXY` detection (don't strip user-set proxy keys) |
| **SH-01** | medium | **v2.3** — random `apiKeyHelper` token; eliminates H7 privacy warning |
| **SH-05** | small | **v2.3 maybe** — `--test` flag; `argo-proxy config env test` already exists upstream so this is convenience-only |
| **SH-STREAM** | n/a | **CANNOT** — already handled upstream by `argo-proxy` |
| **SH-THINK** | n/a | **CANNOT** — likely upstream `argo-proxy` issue; file there if reproducible |
| **Phase C local-shim** | very large | **REJECTED** — breaks D-001 single-file UX; supersedes already-solved upstream problems |

---

## 1. Architectural orientation

`argo-shim` and `argo-anywhere` are independent projects that emerged
in parallel as solutions to a shared user problem: running AI coding
CLI tools (OpenCode, Claude Code, aider, cursor, codex, gemini)
against the ANL Argo gateway from a laptop, regardless of the
laptop's network. Both projects depend on the upstream
[`Oaklight/argo-proxy`](https://github.com/Oaklight/argo-proxy)
project, which provides the actual Argo-to-{OpenAI, Anthropic,
GenAI} translation.

The architectural divergence:

```
LAPTOP                              JUMP / COMPUTE NODE
======                              ===================

argo-shim:
  AI tool
    │
    ▼ HTTP                              ssh tunnel        REAL API
  local Python      ──────────────────────────────────►  CELS API
  HTTP proxy        (intercepts every request:
  (`argo-shim`)     stream-force, strip empty thinking,
                    transparent retry, header injection,
                    token-based auth)

argo-anywhere:
  AI tool                                         compute node
    │                                                  │
    ▼ HTTP                                             ▼
  ──────── ssh -L tunnel ─────────────────────►  argo-proxy
  (no laptop-side HTTP layer; just a port-forward)  (screen/tmux/nohup,
                                                     venv, PyYAML)
                                                          │
                                                          ▼
                                                       CELS API
```

The choice between layers is consequential:

- `argo-shim`'s **local HTTP layer** can rewrite requests and
  responses arbitrarily. This is the right place to compensate for
  upstream gateway quirks (Vertex's 10-minute non-streaming
  timeout; Vertex's empty-thinking-block cache corruption). It is
  the wrong place for SSH-failure tracking and CSPO defense (those
  need on-disk persistence across restarts).
- `argo-anywhere`'s **server-side argo-proxy + SSH tunnel** can do
  none of the request-shape rewriting (we never see the requests
  in clear text on the laptop) but gives us full
  install-installer-pythonvenv-screen-session-config-writer
  orchestration on the compute node. The persistent on-disk lock
  for SSH failures + the multi-tool dispatch architecture + the
  scope framework all live cleanly at this layer.

Neither layer is strictly superior; they make different
correctness/UX tradeoffs.

---

## 2. Verbatim audit

The audit was compiled by the user 2026-05-18 and reproduced here
unchanged. The original was a single-message dump; I have preserved
its section structure, tables, and code snippets without editing.
My scrutiny commentary appears in Section 3.

---

> ## argo-anywhere vs argo-shim: Full Comparative Audit
>
> (Completed 2026-05-18. argo-anywhere at commit 108e5d6; argo-shim at v0.2.0.)
>
> ---
>
> ### 1. Architecture Summary
>
> | Dimension | argo-anywhere | argo-shim |
> |:---|:---|:---|
> | Language | Bash + Python heredocs | Python (stdlib only) |
> | Distribution | `curl … -o script.sh && bash it` | `pip install` / `uvx` |
> | Network path | AI tool → SSH tunnel → argo-proxy on compute node → CELS API | AI tool → local HTTP shim → SSH tunnel → CELS API directly |
> | Server-side | argo-proxy (screen/tmux/nohup, venv, PyYAML config) | None |
> | SSH target | ANL compute node (compute-386-01, etc.) | homes.cels.anl.gov |
> | Jump host | logins.cels.anl.gov | logins.cels.anl.gov |
> | Tools supported | OpenCode, Claude Code (aider/cursor planned) | Claude Code (OpenCode secondary, config-only) |
> | HTTP interception | None (argo-proxy handles on the node) | Full: path rewrite, header injection, stream-forcing, token auth |
>
> The fundamental architectural divergence: argo-shim inserts a
> local HTTP proxy process on the laptop between the AI tool and
> the SSH tunnel. argo-anywhere has no laptop-side HTTP layer — it
> opens a port-forward straight through to argo-proxy on the
> compute node.
>
> This one difference has cascading implications for every feature
> discussed below.
>
> ---
>
> ### 2. What argo-shim does that argo-anywhere cannot (without a local shim layer)
>
> These features live exclusively in argo-shim's HTTP proxy layer.
> They cannot be ported to argo-anywhere without adding a comparable
> local HTTP process:
>
> #### 2A. Force stream=true on all /messages requests + SSE reassembly
>
> argo-shim code (`_shim.py:256-264`):
>
> ```python
> if req_json.get("stream") is not True:
>     forced_stream = True
>     req_json["stream"] = True
>     body = json.dumps(req_json).encode("utf-8")
> ```
>
> When the client originally sent `stream: false` (or omitted it),
> the shim forces `True` upstream, then reassembles the SSE event
> stream back into a single JSON object
> (`_reassemble_sse_to_message`) before returning it to the client.
>
> Why it matters: Vertex AI (the backend behind Argo) returns HTTP
> 500 for non-streaming requests it estimates will take more than
> 10 minutes — this triggers when Claude Code sends large
> tool-result payloads (file reads, web searches). argo-shim's
> README explicitly documents this as a fixed known issue.
> argo-anywhere has no equivalent fix.
>
> Adoption path for argo-anywhere: This needs a local HTTP proxy.
> Two options:
>
> - Option A: Add `--local-shim` mode that starts a Python
>   subprocess on the laptop listening on `SHIM_PORT`, with the SSH
>   tunnel forwarding to `TUNNEL_PORT` on the node and the shim
>   sitting in between. `SHIM_PORT` becomes what Claude Code points
>   at.
> - Option B: Push the fix upstream into argo-proxy (which is a
>   separate project, `oaklight/argo-proxy`). File an upstream
>   issue pointing at argo-shim's implementation as a reference.
>
> Option B is lower argo-anywhere effort but depends on upstream
> maintainer responsiveness.
>
> #### 2B. Strip empty thinking blocks from request history
>
> argo-shim code (`_shim.py:244-254`):
>
> ```python
> for msg in req_json.get("messages", []):
>     content = msg.get("content")
>     if isinstance(content, list):
>         cleaned = [b for b in content
>                    if not (b.get("type") == "thinking" and not b.get("thinking"))]
>         if len(cleaned) != len(content):
>             msg["content"] = cleaned
> ```
>
> Why it matters: Argo/Vertex strips thinking content from cached
> conversation turns but preserves the block structure. When Claude
> Code sends those turns back in subsequent messages, the empty
> thinking blocks cause the API to reject the request. This silently
> breaks extended-thinking conversations mid-session.
>
> Adoption path: Same as 2A — requires HTTP proxy layer.
>
> #### 2C. Tunnel auto-recovery transparent to the client
>
> argo-shim code (`_shim.py:285-303`): On `ConnectionRefusedError`
> from upstream, `recover_tunnel()` is called under a lock (prevents
> multiple threads racing on recovery), then the request is retried.
> The AI tool never sees the failure.
>
> argo-anywhere's monitor loop detects failures and notifies the
> user, but the reconnect requires the monitor to signal the parent,
> which then respawns the `ssh -N -L` foreground process. Claude
> Code sees a connection error during the window between detection
> and reconnect. argo-shim's request-scoped retry means the tool is
> never interrupted.
>
> Adoption path: Without an HTTP proxy layer, transparent retry at
> the HTTP level isn't possible. The current argo-anywhere behavior
> (reconnect within a few seconds; Claude Code retries on its own)
> is acceptable but not as seamless.
>
> ---
>
> ### 3. What argo-shim does that argo-anywhere COULD adopt directly
>
> These are design choices that don't require the HTTP proxy layer:
>
> #### 3A. Per-session auth token (apiKeyHelper) — RECOMMENDED
>
> argo-shim generates `secrets.token_urlsafe(32)` at startup and
> writes it as:
>
> ```json
> { "apiKeyHelper": "echo <token>" }
> ```
>
> argo-anywhere writes the ANL username directly:
>
> ```bash
> env["ANTHROPIC_AUTH_TOKEN"] = user    # argo_anywhere.sh:2695
> ```
>
> The username is personally-identifying and static. The privacy
> warning at `argo_anywhere.sh:4383` is correct but the real fix is
> argo-shim's approach: generate a random token, write it as
> `apiKeyHelper`, and let the token be the bearer credential. This:
>
> - Prevents the ANL username from appearing in any config file
>   (privacy improvement)
> - Automatically invalidates the Claude Code credential when the
>   proxy isn't running (the token is per-session; a stale token
>   won't accidentally talk to a different proxy)
> - Removes the H7 privacy warning (which currently causes noise on
>   every client run)
>
> Adoption implementation (Python heredoc in
> `write_claudecode_config`):
>
> ```python
> import secrets
> token = secrets.token_urlsafe(32)
> data["apiKeyHelper"] = f"echo {token}"
> env.pop("ANTHROPIC_AUTH_TOKEN", None)   # remove the username-as-token
> env["ANTHROPIC_BASE_URL"] = f"http://localhost:{port}"
> ```
>
> The token is ephemeral (not cached) — each client run generates a
> fresh one and rewrites `settings.json`, which is already
> argo-anywhere's behavior. The argo-proxy on the node doesn't
> validate the bearer token content (it's a username by convention
> in the current protocol), so the token doesn't need to match —
> but this is worth verifying against argo-proxy's auth model.
>
> Status: New finding; not in current audit doc. Call it **SH-01**.
>
> #### 3B. CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1" in settings.json — RECOMMENDED
>
> argo-shim always writes this to the env block of
> `~/.claude/settings.json`:
>
> ```python
> settings = {
>     "env": {
>         "CLAUDE_CODE_SKIP_ANTHROPIC_AUTH": "1"
>     }
> }
> ```
>
> argo-anywhere does not write this key. On fresh installs where no
> `ANTHROPIC_AUTH_TOKEN` satisfies Claude Code's auth check, Claude
> Code can fall into an OAuth login flow that confuses users who
> expect to just run `claude`. The D-017 hybrid default (fresh
> installs → global scope) was motivated partly by avoiding this;
> `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"` is the direct fix.
>
> Adoption: One additional key in `write_claudecode_config`'s Python
> heredoc. Zero risk; pure improvement.
>
> Status: New finding. Call it **SH-02**.
>
> #### 3C. Proxy environment variable detection and no_proxy handling — RECOMMENDED
>
> argo-shim (`_shim.py:1031-1035`):
>
> ```python
> proxy_set = any(os.environ.get(v) for v in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"))
> no_proxy_hosts = (os.environ.get("NO_PROXY", "") + "," + os.environ.get("no_proxy", "")).strip(",")
> if proxy_set and not any(h in no_proxy_hosts for h in ("localhost", "127.0.0.1")):
>     print(f"\nProxy detected. Start Claude Code with:")
>     print(f"  no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1 claude")
> ```
>
> Additionally, argo-shim writes `no_proxy: localhost,127.0.0.1`
> into `settings.json` so Claude Code bypasses the system proxy for
> the local shim while preserving proxy for internet access.
>
> argo-anywhere does neither. ANL HPC nodes (and Aurora UANs
> specifically, per argo-shim's README) commonly set
> `HTTP_PROXY`/`HTTPS_PROXY`, which then intercepts Claude Code's
> connection to `localhost:PORT` and breaks the tunnel connection
> silently.
>
> Adoption: Two additions to `write_claudecode_config` and/or
> post-tunnel output:
>
> 1. In the Python heredoc: add `no_proxy`/`NO_PROXY` to the env
>    block (same logic as argo-shim's `update_claude_settings`).
> 2. In the shell post-tunnel message block: check
>    `${HTTP_PROXY:-}${HTTPS_PROXY:-}${http_proxy:-}${https_proxy:-}`
>    and emit the hint when non-empty.
>
> The `no_proxy` write to `settings.json` is the stronger fix
> (survives across shell sessions). The shell hint is defensive
> belt-and-suspenders.
>
> Status: New finding. Call it **SH-03**.
>
> #### 3D. Port collision message shows who owns the port
>
> argo-shim (`_shim.py:431-447`):
>
> ```python
> def _port_in_use_info(port):
>     result = subprocess.run(["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"], ...)
>     for pid in result.stdout.strip().split('\n'):
>         ps = subprocess.run(["ps", "-o", "pid=,user=,comm=", "-p", pid], ...)
>         return ps.stdout.strip()   # "12345 jdoe ssh"
> ```
>
> argo-anywhere (`argo_anywhere.sh:3284-3290`): the collision guard
> says:
>
> ```
> "Port ${PROXY_PORT} is already in use locally."
> "  Identify: lsof -nPi :${PROXY_PORT} -sTCP:LISTEN"
> ```
>
> argo-anywhere tells the user to run the command; argo-shim runs
> it and prints the result. The argo-anywhere approach requires an
> extra manual step for diagnosis.
>
> Adoption: Small shell addition. After the lsof detect, run
> `lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN -F p 2>/dev/null | head -2`
> and pipe through `ps`. The `|| true` wrapping is already correct
> under `set -euo pipefail`.
>
> Status: New finding. Call it **SH-04** (minor).
>
> #### 3E. Test environment flag
>
> argo-shim has `--test` which switches `REAL_HOST` to
> `apps-test.inside.anl.gov`. This lets developers test against the
> staging endpoint without editing any file.
>
> argo-anywhere has no equivalent. If argo-proxy supports a test
> endpoint, adding `ARGO_ANYWHERE_TEST=1` / `--test` that rewrites
> the target URL in the argo-proxy config would be useful.
>
> Status: New finding. Call it **SH-05** (low priority; depends on
> infrastructure availability).
>
> #### 3F. Port pair auto-retry (without prompting) on derived ports
>
> argo-shim: when `listen_port` is auto-derived (not `--port`), it
> retries up to 10 port increments silently before raising. When
> `--port` is explicit, it tries exactly once and errors.
>
> argo-anywhere: has `--auto-port` / `ARGO_ANYWHERE_AUTO_PORT=1`
> that does sequential search, but it's opt-in. The default is to
> prompt with `[a]uto-pick / [m]anually enter / [a]bort`.
>
> argo-shim's approach is simpler for the common case (auto-derived
> port; nobody explicitly chose it; just find the next free one).
> This is already in argo-anywhere but gated on `--auto-port`.
> Whether to change the default is a UX decision — the current
> prompt is safe and explicit.
>
> Status: Noted; no new finding (existing flag covers this).
>
> ---
>
> ### 4. What argo-anywhere does better than argo-shim
>
> These are argo-anywhere strengths that argo-shim lacks or does
> worse:
>
> #### 4A. CSPO defense: persistent on-disk lock with TTL + exponential backoff
>
> argo-shim (`SSHAttemptTracker`): in-memory counter, 3-strike
> limit, resets on restart. A user can circumvent by restarting the
> shim. No backoff — after tripping, it's just blocked until
> restart.
>
> argo-anywhere: persistent `${STATE_DIR}/ssh-fail-lock` +
> `ssh-fail-lock-count`, 30-min initial TTL doubling per event up
> to 24h, survives restarts. Tracker wraps `scp`, bootstrap SSH,
> port probe SSH, clean SSH, and monitor reconnect. This is
> strictly more robust.
>
> argo-shim's in-memory tracker is a documented gap in its own
> README. argo-anywhere's D-012 design is the right model.
>
> #### 4B. Multi-tool orchestration and install
>
> argo-shim is Claude Code-first. OpenCode support is a single
> config-writing function. No install logic, no version detection,
> no model list management.
>
> argo-anywhere installs both tools, manages server-side (venv,
> argo-proxy, screen/tmux/nohup), handles node picker, probes
> reachability, and has a full per-tool API contract for adding
> new tools cleanly.
>
> #### 4C. Config merge with user-key preservation
>
> argo-shim's `update_claude_settings` reads the existing file and
> deep-merges:
>
> ```python
> env = settings.setdefault("env", {})
> env["ANTHROPIC_BASE_URL"] = new_url
> ```
>
> But it also removes stale proxy vars unconditionally
> (`del env[var]` for HTTP_PROXY etc.) which could destroy
> intentional user-set values. argo-anywhere's Python heredoc
> preserves all keys it doesn't own explicitly, and the
> `handle_config_file` `[k/b/d/m/a]` prompt gives the user full
> control when the file has changed.
>
> #### 4D. Scope framework (project vs global, conflict detection)
>
> argo-shim writes exclusively to `~/.claude/settings.json`
> (global). It documents the 401 / project-override issue and
> suggests `--no-auth` as the workaround. argo-anywhere's D-017
> hybrid scope policy with `_claudecode_check_conflicts` +
> `prompt_scope_switch` is the correct architectural solution.
>
> #### 4E. %r-%h-%p ControlPath instead of %C
>
> argo-shim uses:
>
> ```python
> "-o", f"ControlPath=~/.ssh/argo-shim-%C",
> ```
>
> argo-anywhere explicitly switched from `%C` to `%r-%h-%p` tokens
> (`AGENTS.md` documents why: `%C` proved fragile when
> `~/.ssh/config` rewrites jump-host names, producing two different
> socket paths for the same logical connection). argo-shim inherits
> the `%C` fragility bug.
>
> #### 4F. Full subcommand surface (status / stop / clean / update-models)
>
> argo-shim has only one mode (run the shim). Status is manual
> (`curl`). Cleanup is manual (`ps aux | grep ssh`).
> argo-anywhere's `status`, `stop`, `clean`, `update-models` are
> production-quality operational tools.
>
> #### 4G. Jump-host shell restriction handled correctly
>
> argo-shim opens its `ControlMaster` against `homes.cels.anl.gov`
> (which is shell-capable). argo-anywhere can't do this against
> `logins.cels.anl.gov` (its equivalent jump-host) because that
> host rejects shell access — it documents this and opens the
> master against the compute node instead.
>
> If argo-shim's topology were to change to use
> `logins.cels.anl.gov` as the destination (rather than
> ProxyJump), it would break. This is a latent fragility not
> present in argo-anywhere.
>
> ---
>
> ### 5. New argo-anywhere audit findings (discovered during this comparison)
>
> | ID | Severity | Finding | Location |
> |:---|:---|:---|:---|
> | SH-01 | Medium | ANL username written in clear text as `ANTHROPIC_AUTH_TOKEN`; per-session token (`apiKeyHelper` + `secrets.token_urlsafe`) would eliminate the H7 privacy warning entirely and stop leaking identity into config files | `write_claudecode_config` (`:2695`), claudecode dispatcher (`:4383`) |
> | SH-02 | Low | `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"` not written to `settings.json`; fresh installs without an existing auth token may see an unexpected OAuth prompt | `write_claudecode_config` |
> | SH-03 | Medium | No proxy env var detection (`HTTP_PROXY`/`HTTPS_PROXY`) and no `no_proxy` injection; HPC/compute nodes with system proxies silently break Claude Code's connection to the local tunnel port | `write_claudecode_config`, post-tunnel output block |
> | SH-04 | Low | Port collision message instructs user to run `lsof` manually; running it inline and printing PID+user+command would make diagnosis faster | `open_tunnel` (`:3285-3289`), `ensure_or_reuse_tunnel` |
> | SH-05 | Low | No test-environment flag; adding `ARGO_ANYWHERE_TEST=1` / `--test` that switches the argo-proxy target URL to `apps-test.inside.anl.gov` would ease development/debugging | Section 2 (user-editable config) |
>
> ---
>
> ### 6. argo-shim issues / design gaps (for completeness)
>
> These are things argo-shim gets wrong that argo-anywhere already
> handles correctly:
>
> | argo-shim issue | Notes |
> |:---|:---|
> | In-memory-only SSH failure tracker | Resets on restart; circumventable. argo-anywhere D-012 is the correct design. |
> | Uses `%C` ControlPath token | Fragile on jump-host name rewriting. argo-anywhere switched to `%r-%h-%p`. |
> | `OPENCODE_CONFIG` hardcoded to `~/.config/opencode/opencode.json` | OpenCode's actual config file is `~/.config/opencode/config.json`. The file will not be found for most users. |
> | No server-side persistence | Proxy dies when the UAN session ends; user must restart manually. No screen/tmux equivalent. |
> | `--no-auth` workaround for project-scope conflict | Disabling auth at the shim level is a blunt instrument; argo-anywhere's scope framework + conflict detection is the right architectural fix. |
> | No multi-tool support | OpenCode path (`--opencode`) is bolted on top of the Claude Code proxy. No pluggable per-tool API contract. |
> | No status/stop/clean | All operational management is manual (kill PIDs, `rm` files by hand). |
> | No node picker / reachability probing | Single fixed destination (`homes.cels.anl.gov`). |
> | No `[k/b/d/m/a]` config prompt | Silent overwrite or no-write; no "show me the diff" or "merge only my keys". |
>
> ---
>
> ### 7. Adoption roadmap (prioritized)
>
> Phase A — Low-effort, high-value (no architectural change):
>
> 1. **SH-02**: Add `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"` to
>    `write_claudecode_config`'s env block. Two-line addition to
>    the Python heredoc.
> 2. **SH-03**: Add `no_proxy`/`NO_PROXY` to the env block in
>    `write_claudecode_config`. Check `$HTTP_PROXY` / `$HTTPS_PROXY`
>    in the post-tunnel shell output and print the hint when
>    non-empty.
> 3. **SH-04**: In the collision detection path (`open_tunnel` +
>    `ensure_or_reuse_tunnel`), add a brief
>    `lsof -nPi ":${PROXY_PORT}" -sTCP:LISTEN` + `ps` inline to
>    print who owns the port.
>
> Phase B — Medium-effort, significant improvement:
>
> 4. **SH-01**: Replace `ANTHROPIC_AUTH_TOKEN = username` with
>    `apiKeyHelper = echo <random_token>` in
>    `write_claudecode_config`. Eliminates the H7 privacy warning
>    (which becomes obsolete), improves session isolation. Needs a
>    note in `docs/UPGRADING.md` (the env key changes).
>
> Phase C — Large-effort, structural feature (future):
>
> 5. Local HTTP shim mode: Add a `--local-shim` flag (or make it
>    default) that starts a local Python HTTP proxy (can be lifted
>    almost verbatim from argo-shim's `ProxyHandler` +
>    `ThreadedTCPServer`) on `SHIM_PORT`, with the SSH tunnel
>    forwarding to `TUNNEL_PORT` on the node. The shim provides:
>    - Stream-forcing + SSE reassembly (fixes Vertex AI 500 errors
>      — SH-STREAM)
>    - Empty thinking block stripping (SH-THINK)
>    - Transparent tunnel recovery
>
>    This is an opt-in or default-off addition initially. It would
>    be a new Python heredoc (~300 lines, all stdlib) that launches
>    in the background and is cleaned up on `stop`/`clean`/Ctrl-C.
>
> ---
>
> ### 8. Summary judgment
>
> argo-anywhere and argo-shim solve the same user problem from
> different directions. argo-shim's local HTTP proxy is the right
> layer for transport-level manipulation (stream forcing,
> thinking-block stripping) but gives up server-side orchestration,
> multi-tool support, CSPO robustness, and operational tooling.
> argo-anywhere has all of the latter but is blind to the HTTP
> layer.
>
> The three high-leverage adoptions (SH-01, SH-02, SH-03) require
> no architectural change and address real user pain. The
> local-shim option (Phase C) is the only way to match argo-shim's
> Vertex AI compatibility and thinking-block robustness, and is
> worth planning as a future phase once the existing multi-tool
> backlog (aider, cursor, generic) stabilizes.

---

## 3. Scrutiny: what's right, what's wrong

This section verifies each substantive audit claim against the
actual source. Method: cross-checked against (a) `argo_anywhere.sh`
at commit `108e5d6` / v2.2.0, (b) the upstream Anthropic Claude
Code `settings.json` reference at `docs.anthropic.com`, (c) the
upstream `Oaklight/argo-proxy` README, and (d) live probes against
the running deployment on `compute-01.cels.anl.gov`.

### Verified-true claims

| Audit claim | Verification |
|:------------|:-------------|
| `write_claudecode_config` writes `env.ANTHROPIC_AUTH_TOKEN = <username>` at line 2695 | ✅ Confirmed at `argo_anywhere.sh:2694-2695` |
| `env.ANTHROPIC_BASE_URL = http://localhost:{port}` (no `/v1`) | ✅ Matches upstream `argo-proxy` README's documented Claude Code value |
| `apiKeyHelper` is a real, documented Claude Code `settings.json` key | ✅ Anthropic docs: "Custom script … executed in `/bin/sh`, to generate an auth value. This value will be sent as `X-Api-Key` and `Authorization: Bearer` headers" |
| `env` block in `settings.json` supports arbitrary env vars | ✅ Anthropic docs: "Environment variables that will be applied to every session" |
| No `HTTP_PROXY` / `no_proxy` / `NO_PROXY` handling in `argo-anywhere` | ✅ `grep` of `argo_anywhere.sh` returns zero matches on any proxy-env-var name |
| Port-collision message tells user to run `lsof` manually | ✅ `argo_anywhere.sh:3288`: `Identify: lsof -nPi :${PROXY_PORT} -sTCP:LISTEN` |
| H7 privacy warning fires on every claudecode setup | ✅ `argo_anywhere.sh:4383-4385` |
| `argo-anywhere` uses `%r-%h-%p` `ControlPath` tokens (vs argo-shim's `%C`) | ✅ Documented in AGENTS.md per the historical rationale (jump-host name rewrites would produce two different socket paths for what was logically the same connection) |
| `argo-anywhere`'s D-012 persistent SSH-failure lock is stronger than argo-shim's in-memory counter | ✅ Architectural distinction is real per the source-code comparison |
| `argo-anywhere` has multi-tool API contract + `status`/`stop`/`clean`; `argo-shim` doesn't | ✅ Self-evident from `mode_*` + `setup_*_cli_tool` functions in `argo_anywhere.sh` |

### Verified-wrong claims

#### MAJOR — SH-STREAM (2A) is already fixed upstream; the audit's framing is outdated

The audit claims:

> "argo-anywhere has no equivalent fix" for "Vertex AI returns HTTP
> 500 for non-streaming requests it estimates will take more than
> 10 minutes."

**Upstream `argo-proxy` v3.x already has this fix.** From the
`argo-proxy` README's configuration options reference:

| Option | Description | Default |
|:--|:--|:--|
| `anthropic_stream_mode` | Non-streaming Anthropic handling: `force`/`retry`/`passthrough` | `force` |

And the CLI flag `argo-proxy serve --anthropic-stream-mode retry`
exists. The `force` default means `argo-proxy` itself forces
`stream=true` upstream and reassembles before returning to the
client.

**We write `config_version: "3"`** (`argo_anywhere.sh:4806`) and do
not override `anthropic_stream_mode`, so we already inherit `force`.
The Phase C local-shim recommendation in the audit is solving an
upstream-already-solved problem. Any current Vertex 500 incident
on `argo-anywhere` is either (a) a regression in a specific
`argo-proxy` release or (b) needs a different fix altogether.

**Disposition**: SH-STREAM is **CANNOT-NEED-DO**. Document as
"already handled at the proxy layer; pin `argo-proxy` ≥ v3.0 to
ensure default `force` mode."

#### MODERATE — SH-01's caveat about argo-proxy's auth model is moot for our deployment

The audit says:

> "the argo-proxy on the node doesn't validate the bearer token
> content (it's a username by convention) … but this is worth
> verifying against argo-proxy's auth model."

Verified: `argo-proxy` has TWO modes. The default uses the `user:`
field from `config.yaml` for Argo-side attribution;
`--username-passthrough` makes the bearer token the attribution.
**`argo-anywhere` writes the `user:` field
(`argo_anywhere.sh:4806-4810` area) AND does NOT pass
`--username-passthrough`.** Therefore a random opaque bearer token
is benign for us.

So SH-01 IS safe to land — but for a different reason than the
audit's reasoning, and the audit underweighted the precondition.
(Anyone who copies our `write_argoproxy_config` and adds
`--username-passthrough` would break this.)

#### MINOR — SH-THINK (2B) is plausible but independently unconfirmed

The audit claims Argo/Vertex strips thinking-block content but
preserves structure, causing API rejection on cached-turn replay.
The evidence offered is "argo-shim's code does this." That's
circumstantial — argo-shim could be carrying a workaround for a bug
already fixed upstream, OR for a bug still present.

A search of open issues at `Oaklight/argo-proxy` did not surface a
specific empty-thinking-block ticket.

**Disposition**: SH-THINK is **MUST-VERIFY-BEFORE-DOING-ANYTHING**.
If a real-world report comes in, file an issue at
`Oaklight/argo-proxy` referencing argo-shim's `_shim.py:244-254` and
asking whether the upstream proxy has equivalent handling. **Do not
build a local-shim layer to work around it.**

#### MINOR — SH-05's `apps-test.inside.anl.gov` is already in argo-proxy config

The audit recommends adding `--test` to switch the target URL.
`argo-proxy` already has `argo-proxy config env [prod|dev|test]`
for this. We don't need to mirror it; we just need to either (a)
let users edit `argo_base_url` in `~/.config/argoproxy/config.yaml`
(already possible — `write_argoproxy_config` preserves user-set
values via the Python merge), or (b) add a thin `--test-env`
passthrough that runs `argo-proxy config env test` on the node.
Lower-priority than the audit suggests.

### Reclassification: MUST / SHOULD / COULD / CANNOT

#### MUST do (high value, low risk, verified correct, no precondition)

| ID | Why it's MUST |
|:--|:--|
| **SH-04** | Tiny shell change; runs `lsof` + `ps` inline instead of telling the user to. Pure UX improvement. Closes a real "extra-step-to-diagnose" gap. Zero risk. No upstream dependency. |
| **File upstream issue at `Oaklight/argo-proxy` for SH-THINK if a real report comes in** | Free; takes 10 minutes; either confirms we don't need to do anything OR triggers an upstream fix. Either outcome is win. |

#### SHOULD do (high value, requires verification but worthwhile)

| ID | Verification gate |
|:--|:--|
| **SH-03** (`no_proxy` injection + `HTTP_PROXY` hint) | Verify which env-var case Claude Code's HTTP client honors (`no_proxy` vs `NO_PROXY` — write both for safety, do NOT strip existing user values). |
| **SH-01** (random `apiKeyHelper` token, eliminates H7 warning) | Verify `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` default behavior; verify on-node `argo-proxy` is NOT running `--username-passthrough` (which it isn't in our writer, but make it explicit in PLAN.md as a precondition that SH-01 depends on). UPGRADING.md note required. |
| **SH-02** (`CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"`) | Find where this is documented (or confirm it's stable internal). If undocumented, file upstream issue first; do not land an undocumented Claude Code internal. |

#### COULD do (real value, low priority)

| ID | Why low priority |
|:--|:--|
| **SH-05** (`--test` mode) | `argo-proxy` already has `argo-proxy config env test`; we can just document the workflow without adding a new flag. If we want to add a `--test-env` passthrough, fine, but it's pure convenience over an existing upstream feature. |

#### CANNOT / SHOULDN'T do

| ID | Why we shouldn't |
|:--|:--|
| **SH-STREAM** (local-shim stream forcing) | Already solved upstream by `anthropic_stream_mode: force` default. The architectural cost of a local-shim layer (breaks D-001, second lifecycle, second crash mode) is much higher than the audit acknowledges, and the headline justification doesn't hold. |
| **SH-THINK** (local-shim thinking-block stripping) | UNLESS upstream confirms `argo-proxy` doesn't handle it AND won't add it, this belongs upstream not in our laptop layer. |
| **Phase C local-shim mode in general** | Same architectural objections. We've invested in D-006 (single argo-proxy per user per node), D-001 (single-file), D-007 (no symlinks). The local-shim would be a meaningful architectural reversal. |
| **Stripping user-set `HTTP_PROXY` / `HTTPS_PROXY` from the env block** | The audit criticizes argo-shim for exactly this (audit Section 4C: "removes stale proxy vars unconditionally … could destroy intentional user-set values"). We must not import the bug while importing the feature. |

---

## 4. Disagreements with the audit's recommendations

### Tier 1 / Phase C local-shim: NO

The audit's roadmap suggests adding a ~300-line Python heredoc local
HTTP shim to match argo-shim's stream-forcing + thinking-block
stripping + transparent retry. We push back hard for four reasons:

1. **SH-STREAM is already solved upstream** (see Section 3 above).
   The headline justification doesn't hold.
2. **D-001 single-file `curl`-and-run UX** is one of our load-bearing
   design properties. Adding a background Python process means:
   a second lifecycle to manage, a second port to track, a second
   crash mode (what happens if the shim dies but the SSH tunnel
   stays up?), a second cleanup target, a second set of OS
   portability concerns. The blast radius is much larger than a
   300-line addition suggests.
3. **Transparent retry at the HTTP layer is genuinely useful** but
   our existing monitor-loop reconnect handles it for most cases.
   The audit acknowledges this: "argo-anywhere's reconnect within
   a few seconds; Claude Code retries on its own — acceptable but
   not as seamless." That's an acceptable UX gap given the cost.
4. **The right place to fix transport-layer manipulation IS upstream
   `argo-proxy`.** `argo-proxy` already does API translation,
   stream-mode forcing, force-conversion, model name normalization
   — it's the correct layer. Building a second proxy layer on the
   laptop because the upstream layer is incomplete is a maintenance
   trap.

### SH-01 timing: land in v2.3, not v2.2.0

The audit puts SH-01 in "Phase B — medium effort". We agree it's
higher-risk than SH-02/SH-03 because:

- It changes the bearer credential the user sees on the wire.
- It interacts with `apiKeyHelper`'s TTL
  (`CLAUDE_CODE_API_KEY_HELPER_TTL_MS`) — we'd need to set this
  or accept Claude Code's default.
- It needs an UPGRADING.md note (privacy posture change).
- It supersedes H7 in PLAN.md but doesn't break the existing config
  — just an additive change.

This is exactly the kind of change that benefits from one extra
release cycle of soak time, not pressure into v2.2.0. **v2.3 is the
right home.**

### SH-02 / SH-03 timing: also v2.3, with verification

On reflection (now that the audit was scrutinized against source
rather than skimmed):

- **SH-02** (`CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"`) — we want to
  verify what this key actually does before landing it. The audit
  asserts it prevents the OAuth prompt; it wasn't found in the
  Anthropic settings.json reference page within the available
  excerpt (which truncated mid-key-list). It might be an
  undocumented internal env var. Landing an undocumented Claude
  Code internal in our config writer creates an upstream-breakage
  risk. **MUST-VERIFY.**
- **SH-03** (`no_proxy` injection + `HTTP_PROXY` detection) —
  genuinely good for HPC users, but with two caveats:
  - Writing `no_proxy` into `env.no_proxy` AND `env.NO_PROXY`
    (both? one?) needs verification — Node and Python libraries
    vary on which case they check.
  - The audit also suggests stripping pre-existing
    `HTTP_PROXY`/`HTTPS_PROXY` from the `env` block. This is exactly
    the kind of unconditional-delete-of-user-keys that the audit
    ITSELF criticizes argo-shim for in section 4C. Don't do that.

Both can land cleanly with verification work, but verification work
+ smoke + re-test are not free. Committing to a v2.3 release with
SH-01+SH-02+SH-03 properly tested is the cleaner path than rushing
them into v2.2.0.

---

## 5. Reverse direction: findings argo-shim should adopt

The audit lists 9 argo-shim issues. The high-leverage ones to share
back if we ever publish or cross-link the comparative audit:

| # | Finding | Notes |
|:--|:--|:--|
| AS-01 | **Persistent on-disk SSH-failure lock with TTL + exponential backoff** (mirror our D-012) | argo-shim's in-memory tracker is genuinely circumventable; this is a real security regression. |
| AS-02 | **`%r-%h-%p` `ControlPath` tokens** (avoid `%C` fragility with `ssh_config` rewrites) | Direct port; trivial fix. |
| AS-03 | **`OPENCODE_CONFIG` hardcoded path is wrong** — `~/.config/opencode/opencode.json` doesn't exist; the real path is `~/.config/opencode/config.json`. | File upstream issue / PR. |

These are useful credibility-builders if we ever cross-publish, but
no action required from `argo-anywhere`. Listed here for completeness
and for the slide-comparison's "what we do better" framing.

---

## 6. Adoption roadmap

By-release schedule, reflecting the disposition reached after
scrutiny:

### v2.2.0 (released 2026-05-18)

None of the SH-* findings landed in v2.2.0. The release is the
Phase 4 scope-framework + port-as-state + cross-client coherence
bundle. The argo-shim audit was filed for v2.2.x follow-up rather
than v2.2.0 inclusion.

### v2.2.1 (queued; no scheduled trigger)

| ID | Item |
|:---|:---|
| **SH-04** | Inline `lsof`+`ps` in port-collision messages (`open_tunnel` + `ensure_or_reuse_tunnel`). SIGPIPE-safe wrapping per D-011. |
| **SCOPE-NOOP** | (Not from argo-shim; surfaced during Phase 4 Test 12 live test.) Suppress `_<tool>_check_conflicts` A.1 prompt when the writer would produce a no-op against the existing target. |

### v2.3 (queued)

| ID | Item | Verification gate |
|:---|:---|:---|
| **SH-02** | `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"` default | Verify it's a documented Claude Code env key before landing |
| **SH-03** | `no_proxy` / `NO_PROXY` injection + `HTTP_PROXY` detection hint | Verify both env-var cases; do NOT strip user-set proxy keys |
| **SH-01** | Random `apiKeyHelper` token; deprecate username-as-token; eliminates H7 warning | Confirm `argo-proxy` deployment isn't running `--username-passthrough`; UPGRADING.md note required |
| (B4 from Phase 4) | Cursor out-of-integration documentation | Needs manually-collected citations (docs.cursor.com is JS-only and webfetch-unreachable) |
| (Phase 4 follow-up) | Pre-populate `env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `write_claudecode_config` | Works around the upstream-stack opus-4-7 limitation surfaced during v2.2.0 release-gate live test (see `docs/LIMITATIONS.md`) |

### v2.3 maybe

| ID | Item |
|:---|:---|
| **SH-05** | `--test` flag for `apps-test.inside.anl.gov`. Lower-priority since `argo-proxy config env test` already exists upstream; could be a thin passthrough. |

### Rejected

| ID | Why rejected |
|:---|:---|
| **SH-STREAM** | Already handled at the upstream `argo-proxy` layer by `anthropic_stream_mode: force` default. |
| **SH-THINK** | Would require local HTTP shim layer; the bug belongs upstream. If a real-world report comes in, file an issue at `Oaklight/argo-proxy`. |
| **Phase C local-shim** | Would break D-001 single-file `curl`-and-run distribution; supersedes upstream-fixable problems; second lifecycle / second crash mode is a maintenance trap. |

### Deferred (independent of argo-shim audit)

| ID | Item |
|:---|:---|
| **Phase 5** | Aider integration as a clean application of the v2.2.0 per-tool API contract. No scheduled trigger; fires when a user requests it. |
| **Phase 6+** | Generic OpenAI-compatible `--cli-tool` (e.g. `--cli-tool generic --config-path <PATH>`). Under consideration. |

---

## 7. STATUS blocks (live tracker)

As each SH-* finding is closed (or explicitly rejected), append a
STATUS block here so this audit remains a live closure tracker
alongside `AUDIT_2026-05-12.md`. Format mirrors the STATUS-block
convention used in that earlier audit.

### SH-01 — random `apiKeyHelper` token

**STATUS** (2026-05-18, v2.2.0 release): not yet landed. Queued
for v2.3 with verification gate: confirm `argo-proxy` deployment is
not running `--username-passthrough` (which it isn't in our
writer), add UPGRADING.md note, set `CLAUDE_CODE_API_KEY_HELPER_TTL_MS`
or accept default.

### SH-02 — `CLAUDE_CODE_SKIP_ANTHROPIC_AUTH: "1"`

**STATUS** (2026-05-18, v2.2.0 release): not yet landed. Queued
for v2.3 with verification gate: confirm the env key is a documented
Claude Code setting (search reference more carefully than the
initial scrutiny found).

### SH-03 — `no_proxy` injection + `HTTP_PROXY` detection

**STATUS** (2026-05-18, v2.2.0 release): not yet landed. Queued
for v2.3 with TWO constraints: (1) write both `no_proxy` and
`NO_PROXY` case variants for safety; (2) do NOT strip existing
user-set proxy keys (the audit's recommendation to do so would
import argo-shim's own bug per Section 4C of the verbatim audit).

### SH-04 — inline `lsof`+`ps` in port-collision messages

**STATUS** (2026-05-18, v2.2.0 release): not yet landed. Queued
for v2.2.1 (next patch release). Small surgical change; SIGPIPE-safe
wrapping per D-011 required.

### SH-05 — `--test` flag

**STATUS** (2026-05-18, v2.2.0 release): COULD-do; lower priority
than the other SH-* items. `argo-proxy config env test` already
exists upstream so this would be convenience-only. Maybe v2.3,
maybe defer indefinitely.

### SH-STREAM — local-shim stream forcing

**STATUS** (2026-05-18, v2.2.0 release): **REJECTED**. Already
solved upstream by `argo-proxy`'s `anthropic_stream_mode: force`
default (v3.x). Documented as a known limitation rather than a
bug to fix. If users hit Vertex 500 on large non-streaming
requests, the fix is to update `argo-proxy` on the node, not to
add a local-shim layer to `argo-anywhere`.

### SH-THINK — local-shim empty-thinking-block stripping

**STATUS** (2026-05-18, v2.2.0 release): **REJECTED (provisional)**.
Plausible but independently unconfirmed against upstream
`argo-proxy`'s open-issue list. If a real-world report surfaces,
file an issue at `Oaklight/argo-proxy` with argo-shim's
implementation as reference; do not build a local-shim layer.

### Phase C — local-shim mode

**STATUS** (2026-05-18, v2.2.0 release): **REJECTED**. See Section
4 of this audit for the four-point rationale. The decision is
captured in `PLAN.md` Section 4 (Milestones) as an explicit
"Phase C — REJECTED" line with cross-reference to this audit.

---

## Cross-references

- [`AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) — the 43-finding
  fresh-eyes audit (42-of-43 closed at v2.2.0).
- [`AUDIT_2026-05_pre-rebuild.md`](AUDIT_2026-05_pre-rebuild.md) —
  archived pre-v2.0 audit (provenance only).
- [`PLAN.md`](../PLAN.md) Section 4 (Milestones) — v2.2.1 / v2.3 /
  Phase 5 / Phase 6+ / Phase C REJECTED entries cross-reference
  this document.
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) — to be extended with
  Claude Code v2.1.x + opus-4-7 limitation surfaced during the
  v2.2.0 release-gate live test (workaround:
  `claude --model claude-sonnet-4-6` or set
  `env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `settings.json`).

---

*End of audit. See Section 7 for the live STATUS tracker; append
new STATUS blocks as SH-* items close.*
