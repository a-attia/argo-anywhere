# Known limitations

This document enumerates the known limitations of `argo_anywhere.sh`
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
  The single self-contained `argo_anywhere.sh` is load-bearing UX.
- **Linux-only `on_anl_compute_node` suffix match.** If CELS ever
  moves nodes to a different domain, the function silently returns
  "no" until updated.
- **`curl | bash` upstream installers used as-is** (audit L8).
- **No `[m]erge` option for YAML configs in the k/b/d/m/a prompt**;
  only `[b]ackup+overwrite` or `[k]eep` are useful for the on-node
  `argoproxy/config.yaml`.

The list below expands each limitation with rationale + workaround.

## Architecture

### Single-file distribution is load-bearing

The script lives as **one** `argo_anywhere.sh` at the repo root.
Users `curl one .sh -o argo_anywhere.sh && bash it`. The same file
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

### Claude Code v2.1.x + `claude-opus-4-7` returns "API returned empty or malformed response (HTTP 200)"

**Surfaced** during the v2.2.0 release-gate live test
(2026-05-18). The user runs `claude` against the proxy and gets:

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

**Verified workaround**: run Claude Code with any non-opus-4-7
model. We tested:

```sh
claude --model claude-sonnet-4-6      # works
claude --model claude-haiku-4-5       # works
claude --model claude-opus-4-1        # works
claude --model claude-opus-4-7        # fails reliably
```

Switching to opus-4-7 mid-session via `/model claude-opus-4-7`
also reliably reproduces the failure.

**Persistent workaround**: add to the `env` block in
`~/.claude/settings.json` (or the project-scope equivalent):

```json
{
  "env": {
    "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    "ANTHROPIC_BASE_URL": "http://localhost:64742",
    "ANTHROPIC_AUTH_TOKEN": "your-anl-username"
  }
}
```

The `ANTHROPIC_MODEL` setting overrides Claude Code's default
model selection for every session.

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

**Auto-default fix queued for v2.3**: pre-populate
`env.ANTHROPIC_MODEL=claude-sonnet-4-6` in `write_claudecode_config`
(with a one-line comment marker the user can delete to opt back
into Claude Code's default). This eliminates the foot-gun for
every user without requiring them to know about the underlying
bug. See [`PLAN.md`](../PLAN.md) Section 4 (Milestones) v2.3 row.

**Tracking**: candidate upstream issue at `Oaklight/argo-proxy`
issue #120 ("Opus 4.7 not working with claude-code"); the root
cause is upstream of argo-proxy too (Anthropic Vertex model
validation + Claude Code SSE parsing), so an argo-proxy fix would
have to be a translation-layer workaround (rewrite
`thinking.type.enabled` → `thinking.type.adaptive` for opus-4-7
on the fly).

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
v2.2.0. If you encounter it, please file an issue at
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
pattern from the argo-shim comparative audit.*
