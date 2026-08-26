# Known limitations

This document enumerates the known limitations of `argo-anywhere.sh`
that prospective users + contributors should understand before
adopting it. Each limitation includes the rationale (why it's that
way), the workaround (if any), and whether lifting it is on the
roadmap.

## TL;DR

- **One argo-proxy per user per node.** Running `client` twice with
  different ports or different nodes can collide.
- **No automated test suite, no CI.** Smoke tests run manually;
  end-to-end verification is via [`docs/TESTING.md`](TESTING.md).
- **bash 3.2+ target.** No bash-4 features. macOS default is bash
  3.2; we don't require users to install a newer one.
- **Single-file architecture.** No `src/`/`tests/`/`experiments/`.
  The single self-contained `argo-anywhere.sh` is load-bearing UX.
- **Linux-only `on_anl_compute_node` suffix match.** If CELS ever
  moves nodes to a different domain, the function silently returns
  "no" until updated.
- **`curl | bash` upstream installers used as-is** (audit L8).
- **Extended thinking is unavailable in aider + OpenCode**, and on the
  v5 Claude models only the `adaptive` request shape works. Claude Code
  handles this itself; see
  [Extended thinking](#extended-thinking-what-works-where).
- **No `[m]erge` option for YAML configs in the k/b/d/m/a prompt**;
  only `[b]ackup+overwrite` or `[k]eep` are useful for the on-node
  `argoproxy/config.yaml`.

The list below expands each limitation with rationale + workaround.

## Architecture

### Single-file distribution is load-bearing

The script lives as **one** `argo-anywhere.sh` at the repo root.
Users `curl one .sh -o argo-anywhere.sh && bash it`. The same file
is `scp`'d to the compute node and re-exec'd as `server`. Splitting
into modules / a Python package would break both flows.

**Rationale**: this is the project's UX contract. Documented as
design decision D-001 in [`PLAN.md`](../PLAN.md). One file, one
download, no `pip install`.

**Workaround**: none needed; this is by design.

**Roadmap**: not changing.

### bash 3.2+ target (macOS default)

The script targets bash 3.2 (the version macOS ships by default,
unchanged for licensing reasons since macOS 10.5). This means no
bash-4 features:

- no `${var,,}` or `${var^^}` (case mutation)
- no `mapfile` / `readarray`
- no `declare -A` (associative arrays)
- no `printf -v` with format string reuse
- no `${var/pattern/replacement/g}` global replacement (only single
  replacement)

**Rationale**: requiring users to `brew install bash` for an
orchestration script is a portability tax we're not willing to
charge.

**Workaround**: contributors writing new code should test on macOS
bash 3.2 + on a recent Linux bash 5.x. The two are the supported
matrix.

**Roadmap**: not changing for v2.x. May reconsider for v3.x if
macOS finally ships bash 5.

### No automated test suite, no CI

The script is testable only end-to-end against real SSH + real Duo
MFA + real argo-proxy on a real ANL compute node. Mocking that
stack is more complex than the value it provides; a mocked CI would
test the mocks, not the script. Smoke tests are documented inline
in [`AGENTS.md`](../AGENTS.md) "Project-specific facts" and the
end-to-end live verification is in [`docs/TESTING.md`](TESTING.md).

**Rationale**: lightest tool that does the job. Documented as
project-specific override in `AGENTS.md` ("no automated test suite;
no CI").

**Workaround**: per-batch smoke tests are catalogued in
`AGENTS.md`; per-phase live test plans live in `notes/test_plan_phase*.md`
and are run manually before tagging a release.

**Roadmap**: a CI job that runs `bash -n` (syntax check) and
`shellcheck` on every push would be cheap and is on the wishlist
but not implemented.

## Operational

### Single-instance constraint: one argo-proxy per user per node

The script assumes each user runs **one** argo-proxy per compute
node and **one** SSH tunnel per local port. Concrete pinch points:

- `SCREEN_SESSION="argovproxy"` is a single global constant.
  argo-proxy is always started inside the screen / tmux / nohup
  session named `argovproxy` — no per-port suffix.
- `~/.config/argoproxy/config.yaml` is the single argo-proxy config
  file on the node. Its `port:` line is mutated on each invocation.
- `local_tunnel_status` checks "is something on this port?" — can't
  tell which destination the tunnel targets.
- `status` / `stop` / `clean` operate on a single `PROXY_PORT`
  value. No "show me ALL my tunnels" view exists.

Implications:

| Scenario | What happens |
|:---------|:-------------|
| Run `client` twice with **different ports on the same node** | Second run detects the mismatch and asks before killing the first run's argo-proxy (G1 detect-and-warn check from audit). |
| Run `client` twice with **same port to different nodes** | Detect-and-warn check refuses; the script prints which node the existing tunnel targets and tells you to either `stop` first or pick a different port. |
| Run `client` twice with **same port to the same node** | Reuses the existing tunnel + remote argo-proxy (the common case; works fine). |

**Rationale**: simplifies the data model + the recovery story. Most
users want one argo-proxy. The audit-doc P3 (silent misroute on
different-node pick) was the load-bearing fix that made the
detect-and-warn checks reliable.

**Workaround**: if you genuinely need two argo-proxies (e.g.
benchmarking different model sets at different ports), run two
separate argo-proxy processes manually, OUTSIDE the script's
management. The script's `--port` flag still works for picking
which one your laptop's tunnel targets.

**Roadmap**: lifting the constraint is documented as out-of-scope
for v2.0 in [`PLAN.md`](../PLAN.md) "Open Questions". The touchpoints
are listed there. Possible v2.x follow-up if the demand is real.

### MFA (Duo) workflow: one prompt per session

Under MFA mode (the default), the script opens an SSH multiplex
master to the chosen compute node on first invocation, which
triggers exactly one Duo prompt. Subsequent SSH calls within the
master's `ControlPersist` window (default 1 hour) reuse the master
silently — no further Duo prompts.

Implications:

- After Ctrl+C'ing a foregrounded `client`, the master stays alive
  (this is intentional; see the Ctrl+C exit summary). Re-running
  `client` within the hour skips Duo.
- After 1 hour idle (or after `ssh -O exit -S <sock> placeholder`),
  the master closes and the next `client` run re-prompts Duo.
- `--probe-nodes` opens a separate master per node it tests (each
  is a distinct SSH destination). Expect one Duo prompt per
  reachable node when `--probe-nodes` is used.

**Rationale**: ANL CELS hosts use Duo. Without multiplexing, every
SSH call (preflight, scp, remote bootstrap, tunnel, monitor
reconnect, ...) would be a separate Duo prompt — unworkable.

**Workaround**: for non-Duo hosts, use `--no-mfa` (or
`ARGO_ANYWHERE_NO_MFA=1`) to disable multiplexing. Saves the
multiplex setup cost.

**Roadmap**: not changing.

### Jump host shell restriction

`logins.cels.anl.gov` is jump-only — its login shell rejects all
command execution ("This account is currently not available"). The
script therefore opens the multiplex master against the picked
compute NODE, not the jump host. Implications:

- `mode_client` reorders pick-node before preflight under MFA
  (because the master needs a real shell behind it).
- `ssh -O check / -O exit / -O ...` against `logins.cels.anl.gov`
  always fails (no shell to satisfy `true`).

**Rationale**: this is an ANL CELS infrastructure detail, not a
script choice. Documented in `AGENTS.md` "Jump-host shell
restriction".

**Workaround**: none possible from the script side.

**Roadmap**: would need ANL to change its login-shell policy.

### SSH socket duplication with mixed alias/fqdn use (D-032, v3.1.0)

The multiplex socket path uses the literal host string the user
typed: `~/.ssh/sockets/argo-anywhere-<user>-<host>-<port>`. If a
user runs `argo-anywhere --node polaris-login` in one session and
`argo-anywhere --node compute-386-02.cels.anl.gov` in another (same
physical host, resolved via the alias in the first run), argo
opens two mux sockets for what is logically the same connection.
Consequences:

- Two Duo prompts across the two sessions (each socket needs its
  own master).
- `ssh -O check` / `stop` against one socket doesn't affect the
  other. `argo-anywhere stop` cleans up the socket for the
  alias/fqdn that produced the cache entry, leaving the other
  behind until it hits its `ControlPersist` timeout.

**Workaround**: pick one form per compute node (alias OR fqdn) and
stick with it. The cache stores whatever you used first; subsequent
runs reuse it.

**Rationale**: the socket path can't be keyed on the resolved fqdn
without a per-run `ssh -G` call (~ms overhead) on every SSH
invocation. That's an unwarranted cost for a papercut.

**Roadmap**: no runtime-detection is planned. Users who observe the
duplication can pick a canonical form + `argo-anywhere clean` to
wipe the stale caches.

### Custom jump host (`--jump-host`) is not live-tested in CI

The `--jump-host HOST` flag (D-032) sets `ANL_JUMP` for the run.
Unit tests cover the flag's plumbing + the invariant that all 42
`ANL_JUMP` references pick up the mutated global (grep-based tests
in `tests/test_engine_ssh_config.py`). What's NOT covered by
argo-anywhere's own test suite: whether the alternate jump host
you point at can actually reach ANL compute nodes and forward the
SSH connection through to argo-proxy. If you use `--jump-host` in
production and hit issues, please open an issue with your setup
(sanitised `~/.ssh/config` snippet + the `-vvv` output of a manual
`ssh -J <user>@<your-jump-host> <user>@<compute-node>`) so we can
extend the live-verification guide (`docs/TESTING.md`).

## CLI surface

### Filename-based per-tool selection has been removed

Pre-v2.0, the script's invocation name picked the per-tool setup
path (`argo_opencode.sh` → opencode setup, `argo_claudecode.sh` →
claudecode setup, etc.). The v1.x convention used per-tool symlinks
to the same canonical script.

v2.0 removed the filename-based dispatch (audit decision D-007 in
`PLAN.md`). Selection is now exclusively explicit:

- `--cli-tool <name>` flag (or `CLI_TOOL_OVERRIDE` env)
- Interactive picker if neither is set
- `setup` subcommand always shows the picker (alias for `client
  --cli-tool ...` that ignores `--cli-tool`)

**Rationale**: filename-based dispatch broke under
`git clone core.symlinks=false` (Bug 1 in audit) and was the root
cause of several silent-misroute issues. Single canonical filename
is more auditable.

**Workaround**: shell aliases. See [`docs/UPGRADING.md`](UPGRADING.md)
"Update your shell aliases" for the recommended pattern.

**Roadmap**: not changing.

### `[m]erge` option in the k/b/d/m/a prompt is JSON-only

The `handle_config_file` k/b/d/m/a prompt offers `[m]erge: only
update keys this script manages (requires jq for JSON)`. For
`~/.config/opencode/config.json` the merge actually works (jq +
preserve other top-level keys). For
`~/.config/argoproxy/config.yaml` the merge prints "YAML merge not
supported here" and the user must pick `[b]` or `[k]`.

**Rationale**: the YAML merge IS implemented in the writer
(`write_argoproxy_config` uses PyYAML to merge keys), but it
happens BEFORE the prompt — by the time the user is asked, the
proposed file has already been merged. The `[m]` option in the
prompt would be a no-op vs `[b]`. The current text is misleading;
audit finding L-future will track making the YAML prompt offer
only `[b]/[d]/[k]/[a]` (no `[m]`).

**Workaround**: pick `[b]` for YAML configs; the merge has already
happened in the proposed file (preserves all your custom keys).
Pick `[d]` first to inspect the diff if uncertain.

**Roadmap**: minor UX cleanup; not yet filed.

## Domain detection

### `on_anl_compute_node` only matches `*.cels.anl.gov`

The function decides "are we on an ANL compute node?" by suffix
match against `.cels.anl.gov`. The other signal (string-comparing
`hostname -f` against `ANL_NODES` entries) was dead code and was
removed in v2.0 Phase 2c (audit M1). Implication:

- If CELS ever moves nodes to a different domain (e.g.
  `.alcf.anl.gov`), the function silently returns "no" until the
  suffix match is updated.
- The on-node short-circuit (skip the SSH tunnel; point the client
  straight at `127.0.0.1:PORT`) wouldn't fire on the new domain.

**Rationale**: documented as known-and-accepted limitation. The
"properly-correct" fix would be IP-resolution comparison; that's
slower for very-rarely-hit correctness.

**Workaround**: if CELS does move, update the case-statement
matching `*.cels.anl.gov` in `on_anl_compute_node` to also match
the new suffix. One-line edit.

**Roadmap**: would need explicit ANL infrastructure change.

## Trust + supply chain

### Upstream installers (`opencode.ai`, `claude.ai`) used as-is

The script runs `curl -fsSL https://opencode.ai/install | bash`
and `curl -fsSL https://claude.ai/install.sh | bash` to install
the AI clients. No checksum verification (audit finding L8).

**Rationale**: the alternative would be vendoring + signing the
installers, which is more work than this script's scope justifies.
Both upstreams use HTTPS so a network-level adversary can't trivially
substitute the install script, but a compromised upstream domain
would deliver compromised binaries.

**Workaround**: if your threat model rules this out, install the AI
clients manually before running the script. The script detects
existing installs (`command -v opencode` / `command -v claude`) and
skips the install step entirely.

**Roadmap**: not changing.

### `~/.config/argoproxy/config.yaml` permissions not enforced

The script writes the on-node argo-proxy config with default
umask permissions (typically 0644). It doesn't enforce a tighter
mode.

**Rationale**: the file contains your ANL username (PII, not a
secret) and the proxy port — neither is sensitive enough to
warrant changing the file mode. The historical `verbose: true`
default WAS an issue because the resulting log file leaked
prompts; that's fixed (P2 fix; default is now `verbose: false`).

**Workaround**: `chmod 600 ~/.config/argoproxy/config.yaml` after
the script writes it, if your threat model demands it. The script
won't overwrite the mode on subsequent writes (it uses `cp` /
`mv` semantics that preserve target permissions when present).

**Roadmap**: not changing.

## Upstream stack: argo-proxy + AI CLI tools

These are limitations rooted in the upstream stack (Anthropic Argo
gateway, `Oaklight/argo-proxy`, the AI CLI tools themselves) rather
than in argo-anywhere. They surface through argo-anywhere because
that's the layer the user invokes, but the root cause + the fix
sit upstream.

### Extended thinking: what works where

**Last measured**: 2026-08-25, live against `compute-01.cels.anl.gov`
(argo-proxy 3.2.3, llm-rosetta 0.7.1). Full method + evidence in
[`notes/impl_thinking_support.md`](../notes/impl_thinking_support.md).

Two facts govern everything below. The Argo gateway accepts **two
different thinking vocabularies** depending on which API path you use,
and it accepts them **per model**, not uniformly.

On the native Anthropic path (`/v1/messages`), the parameter is
`thinking.type`, and support splits by model generation:

| Model | `thinking.type: enabled` | `thinking.type: adaptive` |
|:---|:---|:---|
| `claude-opus-4.1`, `claude-opus-4.5`, `claude-sonnet-4.5` | works | **fails silently** |
| `claude-haiku-4.5`, `claude-sonnet-4.6`, `claude-opus-4.6`, `claude-opus-4.8` | works | works |
| `claude-opus-4.7` | answers, but no thinking observed | answers, but no thinking observed |
| **`claude-sonnet-5`, `claude-opus-5`** | **fails silently** | works |

**There is no single shape that works everywhere.** The older models take
only `enabled`; the v5 models take only `adaptive`; the middle generation
takes either. Whichever shape a given model rejects, it rejects the same
way: HTTP 200 with a zero-byte body when streaming, and a misleading
parse error when not — see "The v5 failure signature" below.

This is why picking a thinking mode is the client's job and not ours: the
correct value is per-model, the split does not follow version order, and
it changes as ANL adds models. Regenerate the table above with
`python scripts/probe_capabilities.py` rather than trusting it.

**Claude Code v2.1.241 handles this correctly on its own.** It ships a
per-model table and sends `adaptive` for exactly the models that need
it; `claude --model claude-opus-5` works today with no configuration
from us. Older Claude Code releases predate the v5 models and may send
`enabled` to them — if you see an empty response on a v5 model, upgrade
Claude Code first.

**On the OpenAI-compatible path (`/v1/chat/completions`), thinking is
not currently reachable at all.** That path uses a different parameter
(`reasoning.mode`, accepting only `auto` / `enabled` / `disabled` —
`adaptive` is rejected outright), and every value returns an empty
`reasoning_content`. This affects **aider and OpenCode**, which both use
that path. Neither sends a thinking parameter by default, and
`aider --reasoning-effort high` is silently dropped before it reaches
the wire. No configuration on our side or yours changes this; the
limitation is in the gateway/shim layer.

**Why argo-anywhere writes no thinking configuration**: for Claude Code
it would duplicate a table the client already gets right, at the risk of
going stale faster than the client does; for aider and OpenCode it would
write keys that provably do nothing. See the impl note for the full
argument.

**Regenerating this table**: `python scripts/probe_capabilities.py`
(maintainer script; needs a live channel and spends a little gateway
quota). It measures both API paths per model and flags any model whose
thinking shape fails silently.

**Treat these as permanent, not as bugs awaiting a fix.** The gap that
causes the silent failures is in the upstream shim's per-model table,
and the Argo API has a long backlog; we are not filing reports we do not
expect to be actioned. If upstream does fix any of it, the probe script
will show it on the next run.

### The v5 failure signature (why it misleads)

When a v5 model does get `thinking.type: enabled` — from an older client,
or a direct API call — the failure does **not** announce itself the way
the opus-4-7 era failure did.

- **Streaming**: HTTP 200, zero bytes. No error event at all.
- **Non-streaming**: HTTP 502 with
  `Failed to parse upstream response: ... 'choices[0].message' does not
  match any variant of ...`

That message reads like a response-parsing defect in the proxy, not a
rejected request parameter. It sends you looking at the wrong layer. If
you see it, check the thinking shape before anything else.

### RESOLVED (fixed upstream 2026-06): Claude Code + `claude-opus-4-7` returned "empty or malformed response (HTTP 200)"

> **Status: fixed upstream; no user action needed.** Retained for
> provenance, because the failure mode is instructive and the diagnosis
> path is reusable. `llm-rosetta >= 0.6.10` sets
> `thinking_type: adaptive` for `claudeopus47` (and `claudeopus48`) in
> the `argo--anthropic` shim's `reasoning.model_overrides`, which is the
> conversion the ANL gateway requires. Verified still present in
> `llm-rosetta 0.9.0` (2026-08-21). **Opus 4.7 and 4.8 work; earlier
> revisions of this document told users to avoid them, which was wrong
> from roughly 2026-06 onward.** The same shim has **no rows for the v5
> models** — see "Extended thinking" above for the live gap.

**Surfaced** during the v2.2.0 release-gate live test
(2026-05-18). The user ran `claude` against the proxy and got:

```
API Error: API returned an empty or malformed response (HTTP 200)
— check for a proxy or gateway intercepting the request
```

**Diagnosed** by enabling `verbose: true` on the on-node argo-proxy
and tracing the request/response cycle:

1. Claude Code 2.1.143 sends `POST /v1/messages` with
   `thinking: {"type": "enabled", "budget_tokens": N}` when
   targeting `claude-opus-4-7`.
2. ANL's Argo / Vertex deployment rejects with HTTP 400:
   ```
   "thinking.type.enabled" is not supported for this model.
   Use "thinking.type.adaptive" and "output_config.effort" to
   control thinking behavior.
   ```
3. argo-proxy v3.x correctly surfaces the upstream error as a
   SSE `event: error` payload with HTTP 200 status (which is the
   correct shape per the SSE specification — the HTTP transport
   succeeded; the application-level error is the body).
4. Claude Code 2.1.143 fails to parse the `event: error` SSE
   shape (it expects `message_start` / `content_block_*` /
   `message_stop`) and surfaces "API returned an empty or
   malformed response (HTTP 200)."

**Workaround at the time** (no longer needed — opus-4-7 works): run
Claude Code with any non-opus-4-7 model. As tested on 2026-05-18:

```sh
claude --model claude-sonnet-4-6      # worked
claude --model claude-haiku-4-5       # worked
claude --model claude-opus-4-1        # worked
claude --model claude-opus-4-7        # failed reliably (fixed 2026-06)
```

Switching to opus-4-7 mid-session via `/model claude-opus-4-7`
also reproduced the failure.

**Persistent workaround at the time**: add to the `env` block in
`~/.claude/settings.json` (or the project-scope equivalent at
`./.claude/settings.local.json`):

```json
{
  "env": {
    "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    "ANTHROPIC_BASE_URL": "http://localhost:64742",
    "ANTHROPIC_API_KEY": "your-anl-username"
  }
}
```

The `ANTHROPIC_MODEL` setting overrides Claude Code's default
model selection for every session.

> **Note on the auth-var name** (2026-07-13): earlier versions of
> this document showed `ANTHROPIC_AUTH_TOKEN` here.
> `ANTHROPIC_API_KEY` is Anthropic's canonical name for the same
> env var (both are honored by Claude Code and both route
> requests correctly); we adopted the canonical spelling on
> 2026-07-13 as future-proofing. See "Claude Code TUI is
> misleading" below for the UX story that turned up during the
> same investigation.

**Why we don't fix it upstream-of-us**:

- The bug is in the Anthropic Vertex deployment's `thinking.type`
  validation (rejecting `enabled` for opus-4-7) AND in Claude Code
  2.1.x's SSE error-event handling. Neither is something argo-anywhere
  can fix at our layer.
- argo-proxy is doing the right thing by surfacing the upstream
  error as an SSE error event (RFC-compliant; the SSE spec
  explicitly defines `event: error` as a valid payload type).
- Hiding the error by retrying without `thinking` would be a
  silent correctness regression (the user asked for thinking;
  giving them a response without it is wrong).

**Auto-default fix formerly queued for v2.3** — pre-populating
`env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `write_claudecode_config` —
is **obsolete and will not ship as specified**. It would now pin users
to a model two generations old to dodge a bug that no longer exists. The
live successor question (whether to write a *floor* for older Claude
Code releases against the v5 models) is Option 2 in
[`notes/impl_thinking_support.md`](../notes/impl_thinking_support.md),
and is not currently recommended.

**Resolution**: fixed upstream in the translation layer, exactly as
anticipated below. `llm-rosetta` rewrites
`thinking.type.enabled` → `adaptive` per model via
`reasoning.model_overrides`; the `claudeopus47` row landed in v0.6.10
(2026-06-19) and `claudeopus48` alongside it. Original tracking:
`Oaklight/argo-proxy` issue #120 ("Opus 4.7 not working with
claude-code"). The root cause sat upstream of argo-proxy too (Anthropic
Vertex model validation + Claude Code SSE parsing).

### Claude Code TUI is misleading: shows subscription-tier text even when routing goes through argo

**Applies to**: `claudecode` (Claude Code v2.1.x with an active
personal-subscription OAuth session in `~/.claude.json`).

**Symptom**: after `argo-anywhere configure --cli-tool claudecode`
(or the full `client` verb), `claude` starts and shows a welcome
banner like:

```
Claude Code v2.1.207
Welcome back!

  Opus 4.8 · API Usage Billing
  ~/AHMED_HOME/TMP3
```

Plus a **Select model** picker that lists `Fable 5`, `Sonnet 5`,
`Haiku 4.5`, etc. with `$/Mtok` prices — the tiers offered by
your personal-subscription account. Users reasonably conclude
that Claude Code is talking to `api.anthropic.com` under their
personal subscription, not through argo-proxy.

**What's actually happening** (verified 2026-07-13 on Claude Code
v2.1.207): both `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`
DO override the OAuth session and route requests to
`ANTHROPIC_BASE_URL` correctly. The welcome banner + model
picker are **UI content pulled from `~/.claude.json`'s OAuth
account state** (plan tier, billing type, available-model
catalog), NOT from what's currently being served. The TUI shows
this metadata regardless of the actual endpoint.

Additional confusion source: the visible warning banner —

> ⚠ claude.ai connectors are disabled because `ANTHROPIC_API_KEY`
> or another auth source is set and takes precedence over your
> claude.ai login

— fires whenever ANY non-OAuth auth source is set, including our
own env var. It correctly signals "auth source detected" but says
nothing about which base URL the request will hit.

**How to verify argo routing is actually working**:

```bash
# Test 1: an argo-only model id. If routing goes to argo, this
# succeeds; if routing goes to Anthropic direct, this fails.
claude --print --model claude-4.5-haiku "reply ok"

# Test 2: an obviously-invalid model. The ERROR shape reveals the
# routing:
claude --print --model bogus-xyz "reply ok"
# argo-proxy shape:  API Error: 400 {"error":"Upstream API error: ..."}
# Anthropic shape:   There's an issue with the selected model (bogus-xyz)...

# Test 3: a dead-port stress test (destroys the tunnel; run only
# if you can restart it). If routing respects our BASE_URL, the
# request hangs against the dead port instead of succeeding.
```

If Test 1 succeeds and Test 2 shows the `Upstream API error`
shape, requests ARE reaching argo. The subscription-tier text
in the TUI is cosmetic-only.

**Our writer** (as of 2026-07-13) writes both an
`ANTHROPIC_API_KEY` (which is Anthropic's official name for the
auth env var; it works reliably across Claude Code versions).
Pre-2026-07-13 versions wrote `ANTHROPIC_AUTH_TOKEN` instead
(also honored by Claude Code, but the two-name-for-same-thing
history has caused confusion). Older configs are auto-migrated
in place by `_migrate_claudecode_config_in_place` at the next
`configure` — a stale `ANTHROPIC_AUTH_TOKEN` matching your ANL
username (the fingerprint of a value we wrote) is stripped and
replaced with `ANTHROPIC_API_KEY`. A user-owned
`ANTHROPIC_AUTH_TOKEN` with any other value (e.g. a personal
OAuth token you set for another reason) is preserved untouched.

**Related detector** (2026-07-13): the engine runs
`_check_env_shadow_and_warn <tool>` after `configure` / before
`run` `exec`s the binary. It scans the shell env for variables
that would shadow our written config (per-tool list in
`<tool>_shadowing_env_vars`). If any are set, a loud warning
fires with the exact `unset <VAR>` commands to run. Applies to
`opencode` / `claudecode` / `aider`.

**Wishlist / possible future improvement**: write an explicit
`"model"` key to our config that names an argo-served model
(e.g. `claude-4.6-sonnet`), so the TUI's welcome-banner default
is at least accurate to argo's offering. Left unimplemented
today because (a) it would trample a user preference set in
`~/.claude/settings.json` (`"model": "opus"`), and (b) `opus`
etc. are also served by argo, so the default still works —
just with misleading pricing text.

### Vertex returns HTTP 500 on large non-streaming `/messages` requests

**Symptom**: Anthropic Messages requests with `stream: false` and
large input (typically a file-read tool result of ~100KB+ or a
web-search tool result of comparable size) fail with HTTP 500
after ~10 minutes of upstream processing. Originally documented
by the `argo-shim` project's README as a fixed known issue.

**Status in argo-anywhere**: **already mitigated upstream** by
`argo-proxy` v3.x's `anthropic_stream_mode: force` default. When
`argo-proxy` sees `stream: false`, it transparently forces
`stream: true` on the upstream Vertex request and reassembles the
SSE event stream back into a single JSON response for the client.
This bypasses Vertex's 10-minute non-streaming timeout entirely.

**What you need to do**: ensure your on-node `argo-proxy` is
v3.0.0 or newer. The script's bootstrap installs `argo-proxy` via
`pip` from PyPI without a version pin, so fresh installs get the
latest stable; you can verify with:

```sh
ssh -J <user>@logins.cels.anl.gov <user>@<node> 'argo-proxy --version'
```

Older `argo-proxy` versions (pre-v3.0.0) had different schema
defaults and may not have this mitigation. If you see Vertex 500
errors on large non-streaming requests, the fix is to update
`argo-proxy` on the compute node:

```sh
ssh -J <user>@logins.cels.anl.gov <user>@<node> 'argo-proxy update install'
```

You can also override the behavior explicitly by adding
`anthropic_stream_mode: passthrough` (or `retry`) to
`~/.config/argoproxy/config.yaml` on the node, but the default
`force` is the right value for almost all users.

**Why we don't add a local-shim layer**: see
[`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](AUDIT_2026-05-18_argo-shim-comparison.md)
Section 4. Briefly: the `argo-shim` project does this at the
laptop layer; we don't because (a) argo-proxy already solves it
at the right layer (server-side), (b) adding a second proxy layer
on the laptop would break our single-file `curl`-and-run
distribution (D-001), and (c) the maintenance cost of a second
lifecycle / second crash mode is much larger than the user-facing
benefit.

### Empty `thinking` blocks in cached conversation turns (open question)

**Reported pattern** (in the `argo-shim` project, not yet
independently verified by us): when extended-thinking is enabled
across multiple turns, Argo / Vertex may strip the `thinking`
content from cached previous turns but preserve the empty block
structure. When the next request replays those turns, the empty
blocks trigger an API rejection that silently breaks the session.

**Status in argo-anywhere**: **not independently confirmed**. We
haven't surfaced this pattern in any of our own live tests through
v2.2.0, nor in the 2026-08-25 thinking sweep (which was
single-turn throughout, so it would not have exercised the cached-turn
replay this describes). If you encounter it, please file an issue at
<https://github.com/a-attia/argo-anywhere/issues> with the
session transcript + the argo-proxy verbose log entries; we'll
escalate to `Oaklight/argo-proxy` with the supporting evidence.

**Tracking**: not currently filed at `Oaklight/argo-proxy`; would
need a real-world reproducer to file.

**Why we don't pre-emptively work around it**: see Vertex 500
above. The fix belongs upstream (at argo-proxy or at Anthropic);
adding a local-shim layer in argo-anywhere to compensate is the
wrong layer and would break D-001.

## Where to read more

- [`README.md`](../README.md) — top-level user-facing entry point.
- [`docs/UPGRADING.md`](UPGRADING.md) — v1.x → v2.x migration guide
  (covers v2.0, v2.1, v2.2 deltas).
- [`docs/SECURITY.md`](SECURITY.md) — threat model + privacy posture.
- [`docs/TESTING.md`](TESTING.md) — live-verification guide.
- [`docs/AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) — fresh-eyes
  audit with all 43 findings + their resolutions (42-of-43 closed
  at v2.2.0).
- [`docs/AUDIT_2026-05-18_argo-shim-comparison.md`](AUDIT_2026-05-18_argo-shim-comparison.md)
  — comparative audit `argo-anywhere` ↔ `argo-shim` (5 SH-*
  findings; Phase C local-shim REJECTED; slide-ready Executive
  comparison section at the top).
- [`PLAN.md`](../PLAN.md) — design decisions D-001 through D-021;
  Section 4 (Milestones) enumerates v2.2.1 / v2.3 / Phase 5 / Phase 6+
  follow-up work; Section 11 (Open Questions) enumerates broader
  known limitations queued for consideration.

If you hit a limitation that isn't documented here, file an issue
at <https://github.com/a-attia/argo-anywhere/issues>.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)) as part of
Phase 2c+3 of the v2.0 release. Revised 2026-05-18 (Phase 4 /
v2.2.0) to add the "Upstream stack" section covering (a) the Claude
Code 2.1.x + `claude-opus-4-7` + `thinking.type.enabled` HTTP-200
silent-failure surfaced during the v2.2.0 release-gate live test,
(b) the already-mitigated Vertex 500 on large non-streaming
requests (handled by argo-proxy's `anthropic_stream_mode: force`
default), and (c) the open-but-unconfirmed empty-thinking-blocks
pattern from the argo-shim comparative audit. Revised 2026-08-25:
replaced the opus-4-7 limitation with a measured "Extended thinking"
support matrix (the opus-4-7 breakage was fixed upstream in 2026-06;
the section is retained below it, marked RESOLVED, for provenance) and
recorded the v5 `adaptive`-only gap plus the aider / OpenCode ceiling —
see [`notes/impl_thinking_support.md`](../notes/impl_thinking_support.md).*
