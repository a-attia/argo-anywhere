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

## Where to read more

- [`README.md`](../README.md) — top-level user-facing entry point.
- [`docs/UPGRADING.md`](UPGRADING.md) — v1.x → v2.0 migration guide.
- [`docs/SECURITY.md`](SECURITY.md) — threat model + privacy posture.
- [`docs/TESTING.md`](TESTING.md) — live-verification guide.
- [`docs/AUDIT_2026-05-12.md`](AUDIT_2026-05-12.md) — full audit
  trail with all 43 findings + their resolutions.
- [`PLAN.md`](../PLAN.md) — design decisions D-001 through D-014;
  Open Questions section enumerates known limitations queued for
  v2.x consideration.

If you hit a limitation that isn't documented here, file an issue
at <https://github.com/a-attia/argo-anywhere/issues>.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance
from Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)) as part of
Phase 2c+3 of the v2.0 release.*
