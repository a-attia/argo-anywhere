# Security model

This document describes argo-anywhere's threat model, what it does to
defend its users, what it does NOT defend against, and the privacy
posture of the data flowing through it. It is for security-conscious
users + ANL admins who want to understand the behavior before
recommending it (or installing it on shared infrastructure).

As of v3.0.0 argo-anywhere is a Python package that owns the runtime
and drives the bash **engine** (vendored verbatim). The engine's
security model — SSH tunnel, identity attribution, CSPO defenses,
on-disk logging — is unchanged and is the bulk of this document. The
package adds one new local attack surface: an **optional loopback-only
web UI** (`argo-anywhere web` / `app`), covered in its own section
below.

## TL;DR

- **Scope**: a thin orchestrator. The script opens an SSH tunnel from
  your laptop to an ANL compute node and starts argo-proxy there. It
  does not handle prompts, model outputs, or any model-vendor
  authentication directly.
- **Identity**: each request is attributed to your ANL username (sent
  as the bearer token by argo-proxy to the Argo gateway). Calls show
  up in ANL's per-account usage reporting against your domain account.
- **Privacy posture**: ANL's published statement is that prompt content
  is not retained by the Argo gateway. The model vendors (Azure
  OpenAI / Anthropic Enterprise / Google) see prompts under their
  contractual terms with ANL.
- **Two recent privacy/correctness fixes** users should know about:
  - `verbose: false` is now the default in the on-node argo-proxy
    config (closes a prompt-on-disk leak; v2.0 P2 fix).
  - Claude Code default scope is now project (closes a silent
    OAuth-token override; v2.0 H6 fix).
- **CSPO defenses**: persistent on-disk SSH-failure lock with TTL +
  exponential backoff prevents accidentally racking up failed SSH
  attempts that could trigger ANL's IP-block defense.
- **Local web UI** (opt-in): binds `127.0.0.1` only + a DNS-rebinding
  Host-header guard; runs only allowlisted engine verbs (no shell
  passthrough). It is **unauthenticated** and shares your shell trust
  boundary — see [Local web UI](#local-web-ui-argo-anywhere-web--app).
- **What the script does not defend against**: a malicious laptop
  user, a malicious compute node, or a malicious upstream
  installer (`curl | bash` from `claude.ai` / `opencode.ai` is used
  as-is).

## Threat model

The script's adversary model is light:

| Threat | In scope? | Defense |
|:-------|:----------|:--------|
| Network adversary observing your SSH traffic | Yes (implicitly) | SSH itself; the script doesn't add anything below the SSH layer. |
| Network adversary observing the local tunnel (between your AI client and the SSH tunnel) | Yes | Tunnel binds to `127.0.0.1` only; not exposed on routable interfaces. |
| Remote adversary reaching the local web UI | Yes | Web server binds `127.0.0.1` only + a DNS-rebinding guard (Host header must name loopback, else 403/1008). Not reachable off-host. See [Local web UI](#local-web-ui-argo-anywhere-web--app). |
| Local process / browser page POSTing to the local web UI | Partial | The web UI is unauthenticated (no token / same-origin check), so any local process (or a web page in your browser, CSRF-style) that reaches `127.0.0.1:<port>` can trigger engine verbs incl. a Duo push. Mitigated by: argv allowlist (no shell passthrough), loopback bind, and the fact such a peer already shares your shell trust boundary. A loopback token / Origin check is queued as post-3.0 hardening. |
| Other users on your laptop | Partial | argo-proxy config files have OS-default permissions (typically 0644 for JSON, 0644 for YAML); your username (used as the Argo bearer token) is therefore readable by other local users. |
| Other users on the compute node | Yes | Strict identity check on argo-proxy reuse (v2.0 H5 fix); script refuses to attach to a running argo-proxy unless `cfg_user == want_user` is positively verified. |
| Accidental CSPO IP-block via SSH-failure burst | Yes | Persistent on-disk failure lock with TTL + exponential backoff (v2.0 C4/C5/C7 fixes); see [CSPO defenses](#cspo-defenses). |
| Adversary controlling the AI model vendor | No | Out of scope; ANL's contracts with the vendors are the relevant trust boundary. |
| Adversary controlling the ANL Argo gateway | No | Out of scope; you trust ANL or you don't run this. |
| Adversary on the compute node trying to read your prompts | Yes (for the on-disk-log path) | `verbose: false` is the default (v2.0 P2 fix); without verbose mode, argo-proxy doesn't write prompt bodies to disk. |
| Malicious upstream `curl \| bash` installer (opencode.ai, claude.ai) | No | Out of scope; the script trusts the upstream installers. Audit finding L8. |
| Compromised SSH multiplex socket | Partial | Sockets live in `~/.ssh/sockets/` with default permissions. ssh enforces socket file ownership before connecting. |
| Lost laptop with cached state | Partial | The local state directory contains your username, last-used node, and SSH-failure counters. None are secrets per se but disclose your usage pattern. |

The script is designed for the threat model of **a trusted user on a
trusted laptop, talking to a trusted (but multi-tenant) ANL
infrastructure**. It is NOT designed for adversarial co-tenancy of the
laptop or for running on a shared / kiosk machine.

## What gets logged where

A complete inventory of where prompt and identity data may persist:

### Laptop side

| Location | Contents | Sensitivity |
|:---------|:---------|:------------|
| `~/.config/argo_anywhere/user` | ANL username | low (PII; not a secret) |
| `~/.config/argo_anywhere/node` | Last-used compute node hostname | low (operational metadata) |
| `~/.config/argo_anywhere/ssh-fail-lock` | Epoch timestamp of most recent SSH-failure lock event | none (just an integer) |
| `~/.config/argo_anywhere/ssh-fail-lock-count` | Cumulative count of historical lock events (drives exponential backoff) | none |
| `~/.config/opencode/config.json` | OpenCode config including `provider.argo.options.baseURL` (proxy URL) and the bearer token (= ANL username) | low (PII) |
| `~/.claude/settings.json` (global scope) OR `./.claude/settings.local.json` (project scope; default since v2.0) | Claude Code config including `env.ANTHROPIC_API_KEY` (= ANL username; was `ANTHROPIC_AUTH_TOKEN` before 2026-07-13 canonical-name adoption — see docs/LIMITATIONS.md "Claude Code TUI is misleading") | low (PII) |
| `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>` | SSH multiplex master sockets | none (sockets, not data) |

No prompt content is logged on the laptop. The web UI keeps no data at
rest: it holds live PTY sessions in memory only and serves vendored
static assets; nothing it does writes prompt or identity data beyond
what the engine already writes above.

### Compute node side

| Location | Contents | Sensitivity |
|:---------|:---------|:------------|
| `~/.config/argoproxy/config.yaml` | argo-proxy config: ANL username, port, host, `verbose:` setting, `argo_url`, etc. | low (PII) |
| `~/.argo_anywhere.server.log` | Output of the script's bootstrap + `mode_server` invocation (which python, which venv, install messages) | low (operational; no prompt content unless `verbose: true`) |
| argo-proxy stdout (captured into `~/.argo_anywhere.server.log` via `tee` re-exec) | If `verbose: true`: full prompt + response bodies. If `verbose: false` (DEFAULT since v2.0): structured access logs without bodies. | **HIGH (with verbose: true); LOW (with verbose: false)** |
| `~/argovenv/` | Python venv with argo-proxy installed; no user data. | none |

The big one is the third row. Pre-v2.0 the script defaulted to
`verbose: true`, meaning every prompt and response was written to
the on-node log file. The file is owned by the user (typical
`umask 022` produces 0644), readable by anyone with SSH access to
that account on the node, plus root. On a shared compute node where
multiple ANL users may have account access (rare but possible), this
was a meaningful exposure.

v2.0 defaults to `verbose: false`, which produces structured access
logs (HTTP method, path, status code, latency) without prompt or
response bodies. Use `--verbose-server` (or
`ARGO_ANYWHERE_VERBOSE_SERVER=1`) to opt back in only when actively
debugging argo-proxy itself; remember to remove the flag for routine
use.

### What the Argo gateway sees

Every request `argo-proxy` forwards to the Argo gateway carries:

- **Bearer token** = your ANL username. This is how Argo attributes
  usage to your account.
- **Prompt body** as the API request payload. Per ANL's stated
  policy, prompt content is not retained by the gateway itself.
- **Vendor-side** (Azure OpenAI / Anthropic Enterprise / Google):
  the vendors see the prompts under their contractual terms with
  ANL. The "ANL doesn't store user data" statement is about the
  gateway, not the upstream vendors.

Refer to ANL's published Argo policy for the most current statement
on data handling. The script doesn't change ANL's policy; it just
relays your requests through the documented API.

## CSPO defenses

ANL's public-facing infrastructure includes a Consumer-Side
Per-Origin (CSPO) rate-limiter that blocks IPs after a burst of
failed SSH authentications. A typical block lasts 24h+ and affects
**every user sharing that IP** (e.g. everyone on the same NAT, or
everyone on the compute node when the script runs there). Avoiding
CSPO triggers is the script's largest defensive concern after
correctness.

The defenses (v2.0 Phase 2a + 2b):

- **In-memory + on-disk SSH-failure counter** (`ssh_attempt_pre` /
  `ssh_attempt_ok` / `ssh_attempt_fail`). Tracks consecutive failures
  across the script's SSH calls; after `SSH_FAIL_THRESHOLD` (default
  3) consecutive failures, the script locks further SSH attempts and
  refuses to make more.
- **Persistent on-disk lock** (`~/.config/argo_anywhere/ssh-fail-lock`)
  survives script restarts; user can't bypass the lock by Ctrl+C +
  re-run.
- **TTL with exponential backoff** (v2.0 C5 fix). Base TTL 30 minutes;
  doubles per repeat lock event up to a 24-hour cap. A successful SSH
  attempt resets the count to 0.
- **Threshold-1 reset on TTL expiry** (v2.0 C5 fix). When the TTL
  expires, the in-memory counter resets to `SSH_FAIL_THRESHOLD - 1`
  (NOT 0), so the user gets exactly one more attempt before
  re-locking — punishes "wait, then blindly retry" patterns without
  punishing "wait, fix, retry-succeeds" patterns.
- **Pre-action gates** at every SSH-issuing site (preflight,
  reachability check, `--probe-nodes` per-iteration, mid-loop hostname
  pick, monitor reconnect). Every SSH attempt is funneled through
  `ssh_attempt_pre`.
- **Burst-cap escalation in the reconnect loop** (v2.0 C7 fix). After
  3 burst events of repeated reconnect attempts, the script gives up
  with a notification rather than spinning forever.
- **Fails-open hardening** (v2.0 C4 fix). If the script can't write
  the on-disk lock file (read-only `$HOME`, full disk, NFS hiccup),
  it dies with `exit 3` rather than continuing with in-memory-only
  state that the user could bypass.

Recovery from a lock:

```sh
# wait for the TTL to expire (current TTL printed in the lock-fired message)
# OR delete the lock manually:
rm ~/.config/argo_anywhere/ssh-fail-lock
```

Even with the lock active, there's a recovery instruction printed
once that explains how to verify your SSH manually outside the
script (`ssh -o ConnectTimeout=5 <user>@logins.cels.anl.gov true`).

## Local web UI (`argo-anywhere web` / `app`)

The v3.0.0 package adds an **optional** loopback-only web UI: a browser
terminal (and a `pywebview` native-window wrapper) that can drive the
engine — `connect` incl. Duo, the live monitor, `configure`/`run`, and
read-only info views — without a native terminal. It runs only when you
start it (`argo-anywhere web` or `app`); it is not started by any other
subcommand and listens on nothing until you do.

### What it exposes

| Property | Behavior |
|:---------|:---------|
| Bind address | `127.0.0.1` only (default port `8799`). Never a routable interface. |
| DNS-rebinding guard | Every HTTP request and the WebSocket upgrade require a loopback `Host` header (`127.0.0.1` / `localhost` / `::1`); anything else gets `403` (HTTP) / close `1008` (WS). Defeats a malicious page that resolves an attacker domain to `127.0.0.1`. |
| Authentication | **None.** No token, no same-origin/CSRF check. |
| What a request can do | Spawn a PTY running the engine, but only via an **argv allowlist**: known verbs only, `--cli-tool`/`--scope` constrained to a `^[a-z0-9][a-z0-9-]{0,31}$` alphabet, `--port` range-checked. There is **no free-form / shell passthrough** — the browser can hand values only to the vendored engine, never to a shell. Returning verbs (`status`, `list-models`, `list-tools`) run captured with stdin closed. |
| ANL-reaching actions | Never auto-run. Channel `/health` and model-list calls (which traverse the tunnel) fire only on an explicit user action; the kill-guard refuses (409) to stop a session that owns a live channel unless you confirm. |
| Data at rest | None (see [What gets logged where](#laptop-side)). |

### Ratified posture (PLAN.md Q11)

The posture is **accepted as-is for v3.0.0**: loopback bind + Host-header
guard + argv allowlist are adequate for the project's threat model of a
**trusted user on a trusted laptop**. The rationale is the same as for
the on-node tunnel: anyone who can reach `127.0.0.1:<port>` on your
laptop is already a peer of your shell, and the server cannot be coerced
into running anything the engine itself wouldn't.

### The residual (queued hardening)

Because the UI is unauthenticated, it does **not** defend against a
**hostile local process** or a **malicious web page in your browser**
(CSRF-style) that POSTs to `127.0.0.1:<port>`. Such a caller could
trigger an engine verb — including a `connect` that fires a Duo push —
though it still cannot run arbitrary shell (the argv allowlist holds).
The loopback bind + Host guard stop *remote* and *DNS-rebinding*
attacks; they do not stop a same-host attacker.

A **loopback token or `Origin`/same-origin check** on state-changing
endpoints + the WebSocket is queued as post-3.0 hardening. Until then:
don't run the web UI on a laptop you share with an untrusted local user,
and close it when you're not using it (it listens only while running).

## Identity attribution

Every prompt sent through this script is attributed to a single
ANL username. The username flows as follows:

1. Resolved on the laptop (priority: `--user` flag → `ARGO_ANYWHERE_USER`
   env → `ARGO_OPENCODE_USER` legacy env → cached value at
   `~/.config/argo_anywhere/user` → `id -un` fallback).
2. Embedded in the AI client config:
   - **OpenCode**: `provider.argo.options.apiKey` = `<username>` in
     `~/.config/opencode/config.json`.
   - **Claude Code**: `env.ANTHROPIC_API_KEY` = `<username>` in
     `~/.claude/settings.json` (global) or
     `./.claude/settings.local.json` (project, default since v2.0).
     (The env-var name changed from `ANTHROPIC_AUTH_TOKEN` to
     `ANTHROPIC_API_KEY` on 2026-07-13; both are honored by Claude
     Code and both route requests correctly, but `ANTHROPIC_API_KEY`
     is Anthropic's canonical name. See docs/LIMITATIONS.md
     "Claude Code TUI is misleading" for the UX story that turned
     up during the same investigation.)
3. Sent as the bearer token by argo-proxy to the Argo gateway.

The script does NOT separate the laptop OS user (`id -un`) from the
Argonne identity (`ARGO_ANYWHERE_USER`). On a system where the local
account name differs from your Argonne username (the common case for
laptops where the OS account is your real name), be sure to set
`ARGO_ANYWHERE_USER` explicitly or use `--user` — otherwise the
fallback to `id -un` will attribute calls to whatever your laptop
account is called.

## Things this script does NOT defend against

Explicit non-defenses, listed so they're not surprises:

- **Adversarial co-tenancy of the laptop**. The state directory and
  AI client configs are written with default permissions (typically
  0644). Other local users on a multi-user laptop can read your
  username and operational metadata.
- **Adversarial co-tenancy of the compute node**. argo-proxy listens
  on `127.0.0.1` (localhost) on the node, so it's not exposed to
  other hosts. But other users on the same compute node who can
  somehow reach `127.0.0.1:<your-port>` (e.g. via `lsof` to see your
  port + their own SSH-forwarding) could send queries that argo-proxy
  attributes to your Argo account. Mitigations: pick a non-default port
  via `--port`, or just don't run on shared compute nodes you don't
  trust.

  **The inverse direction — you accidentally routing through *their*
  argo-proxy — is now defended at three points** (as of 2026-08-10;
  before that only the first existed, and it covered just one of them):

    1. **Pre-launch reuse** (H5): `mode_server` refuses to adopt an
       existing proxy unless it positively confirms the config's `user:`
       matches the Argo identity we were told to serve.
    2. **Post-launch confirmation** (`_listener_is_ours`): after starting
       argo-proxy, the wait loop confirms the process answering `/health`
       is owned by our OS account. A co-tenant's proxy answers
       identically, so a bare health check proved nothing.
    3. **Adopting a non-tunnel local listener** (`external-healthy`): the
       same ownership check now gates the branch that used to accept any
       healthy listener as usable.

  All three **fail closed** — missing `lsof`, a vanished pid, or an
  unreadable config means "cannot confirm", which is treated as "not
  ours". Point 3 can be opted out of with
  `ARGO_ANYWHERE_ALLOW_FOREIGN_PROXY=1` for a deliberately shared proxy.

  Remaining gap in this direction: a **warm reconnect** through an
  existing tunnel does not re-verify the far-end process. The tunnel
  itself is ours and its destination host and far-end port are pinned at
  creation, so the exposure is limited to our proxy dying mid-session and
  a co-tenant binding the freed port before we notice.
- **A same-host attacker against the local web UI**. When you run
  `argo-anywhere web` / `app`, the unauthenticated loopback server can
  be reached by any local process or (CSRF-style) a malicious browser
  page, which could trigger an engine verb incl. a Duo push. It cannot
  run arbitrary shell (argv is allowlisted) and is not reachable
  off-host (loopback bind + Host guard). A loopback token / Origin
  check is queued as hardening; see [Local web UI](#local-web-ui-argo-anywhere-web--app).
- **Compromised upstream installers**. The script runs `curl ... |
  bash` from `opencode.ai` and `claude.ai` to install the AI clients.
  No checksum verification (audit finding L8). If those domains are
  ever compromised, you would install whatever they served. This is
  a known, accepted, untreated trade-off (the alternative would be
  vendoring + signing the installers, which is more work than this
  script's scope justifies).
- **A malicious `~/.config/argoproxy/config.yaml` written by another
  process**. The on-node argo-proxy reads its config from this file;
  if a different process on the node overwrites it with a config
  pointing at a hostile `argo_url`, the next argo-proxy restart
  would route requests through that URL. The mitigation is operating
  system file permissions on `~/.config/argoproxy/config.yaml`,
  which the script does not enforce or verify.
- **A malicious SSH multiplex socket**. The script uses ssh's
  ControlMaster + ControlPath to multiplex SSH sessions through
  `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>`. ssh itself
  enforces socket-file ownership checks before connecting, but if
  another local user can write to your `~/.ssh/sockets/` (broken
  permissions on `~`), they could plant a malicious socket. The
  mitigation is OS-level home-directory permissions, which the
  script doesn't enforce or verify.

If your threat model includes any of the above, this script is the
wrong tool — direct ssh + manually-managed argo-proxy is more
auditable and more under your control.

## Reporting a security issue

File an issue at <https://github.com/a-attia/argo-anywhere/issues>
with `[security]` in the title; for sensitive disclosures, contact
the maintainer directly (see [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)
for contact). Please don't post exploits in public issues until
they've been triaged.

The script is research-grade infrastructure (one user, one
maintainer); response times are best-effort, not SLA-backed.

## Where to read more

- [`docs/AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) — full audit
  trail with all 43 findings (10 critical, 11 high, 10 medium, 10 low,
  3 info) and their resolutions.
- [`docs/AUDIT_2026-05_pre-rebuild.md`](AUDIT_2026-05_pre-rebuild.md) —
  archived prior audit (pre-v2.0).
- [`docs/UPGRADING.md`](UPGRADING.md) — what changes for v1.x users
  upgrading to v2.0 (covers the P2/H5/H6/H7 privacy + identity fixes).
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) — non-security limitations
  (single-instance constraint, no automated tests, etc.).

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)) as part of
Phase 2c+3 of the v2.0 release. Revised 2026-07-12 for v3.0.0: broadened
the intro to the Python package; added the ratified "Local web UI"
threat model (PLAN.md Q11) — loopback bind + Host guard + argv allowlist
accepted, local-process/CSRF residual documented, loopback-token/Origin
check queued as hardening.*
