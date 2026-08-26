# Start here: install and migrate

Pick the **one** row that matches you. Each path is 2–3 steps; everything after
this section is reference detail you only need if something surprises you.

> **Installing from `main` (unreleased).** Wherever a step below says
> `pipx install argo-anywhere`, install from the repo `main` branch instead:
> `pipx install 'argo-anywhere @ git+https://github.com/a-attia/argo-anywhere@main'`
>
> **Single-mode install (post-v3.1.0).** `pipx install argo-anywhere` includes
> the web UI (`argo-anywhere web`) and the native desktop app
> (`argo-anywhere app`, `install-launcher`) by default. The old `[web]` /
> `[app]` / `[all]` extras have been dropped — any old command line that
> spells `argo-anywhere[web]` or `argo-anywhere[app]` should be simplified to
> `argo-anywhere` (pip/pipx accept the bracket form for a while as a no-op
> harmless request, but there is nothing extra to install).

### New to argo-anywhere

1. **Install:** `pipx install argo-anywhere`
2. **Connect** (one Duo prompt): `argo-anywhere connect`
3. In another terminal, **run a tool** against that channel:
   `argo-anywhere run aider` (or `opencode` / `claudecode`). Prefer no terminal?
   `argo-anywhere install-launcher` gives you a double-click app.

### Coming from any v3.x on the PyPI package

`pipx upgrade argo-anywhere` is the whole procedure — no state migration in any
v3 → v3 step.

> **If you are on v3.3.0, upgrade now.** It shipped three regressions: `[a]
> abort` at a prompt did not abort, a failed run could leave a wrong port
> cached, and auto-port-by-default could silently migrate a live session.
> v3.3.1 was prepared but never published, so v3.3.0 stayed the current
> release until v3.4.0 — which makes it the version you are most likely
> running. v3.4.0 carries all three fixes. If you cannot upgrade yet,
> `pipx install "argo-anywhere==3.2.1"` is safe.

> **Upgrade from v3.2.1 or earlier if you share a compute node.** Older
> versions can attach to *another user's* argo-proxy — it answers the health
> check identically, so the tool reported success while your requests went out
> under their Argo identity. v3.3.1+ refuses to route through a proxy it
> cannot attribute to you, and derives a different default port per user so
> co-tenants collide far less often.

Per-release detail is in [`CHANGELOG.md`](../CHANGELOG.md). The rest of this
section covers the v3.0.x → v3.1.0 UX changes, which are the only ones that
alter a workflow you may have muscle memory for.

**What changed in v3.1.0:**

- **Web UI launcher:** requires you to pick a **working directory** (absolute
  path; blank no longer silently inherits the server's cwd). Pre-fills with
  the most-recently-used path or `~` on first run; **Browse…** button in the
  desktop app; missing directories prompt "Create + Launch" (never silent).
- **Web UI verbs:** `client` removed from the launcher's dropdown — use
  `connect` + `configure` + `run` instead. `client` still exists in the CLI.
- **Web UI terminals:** the embedded panel is now split into **Channel**
  (persistent; owns `connect`) and **Utility** (ephemeral; `configure` /
  `setup` / `tunnel`) — both toggle together via the existing show/hide.
- **`run`/`client`** hard-blocked from in-browser terminals (would die on tab
  close). Use a native terminal — the launcher shows the recommended one.
- **Scope field** is a dropdown now, not free-text — no more `--scope projct`
  typos.
- **New `--cwd PATH` engine flag** (CLI parity with the launcher's field).
  Under `--scope project` it enforces a forbid-list (`$HOME` exact + system
  dirs) so `--scope project` can't accidentally litter dotfiles in `~`. See
  [`PLAN.md` D-031](../PLAN.md).
- **Light / dark theme toggle** in the top bar (cycles `auto → dark → light →
  auto`; persists in `~/.argo_anywhere/web_state.json`).
- **`~/.argo_anywhere/web_state.json`** is new (small; auto-created; safe to
  delete — regenerates on next launch with defaults). Holds the MRU list,
  divider position, and theme choice.
- **Multi-instance guard.** `argo-anywhere web` / `app` now refuse to start if
  another argo-anywhere is already listening on the same port (or if
  something else is on that port). Message tells you the peer's pid + version
  and suggests the next port. Bypass with `--force`. Also useful when
  running a dev-mode instance alongside the pipx-installed one:
  `PYTHONPATH=src python -m argo_anywhere web --port 8800`.
- **Native `~/.ssh/config` respect** ([D-032](../PLAN.md)). If
  `ssh <alias>` works for your ANL nodes, `argo-anywhere --node <alias>`
  works too — username is inferred from your ssh_config (unless you
  override with `--user`), and our SSH `-J` is skipped when the alias
  already routes via its own ProxyJump/ProxyCommand (preventing the
  jump-loop error). New `--jump-host HOST` /
  `ARGO_ANYWHERE_JUMP_HOST=HOST` for the cohort that needs a
  non-default jump host without a mature ssh_config. If you hit issues
  with `--jump-host` in production, please open an issue with your
  setup so we can extend the live-verification guide. See
  [README "Using your own `~/.ssh/config` route"](../README.md#using-your-own-sshconfig-route-d-032-v320)
  for the walkthrough.

### Coming from v2.x (you ran `bash argo-anywhere.sh …` or `curl … .sh`)

1. **Install the package:** `pipx install argo-anywhere`. It bundles the engine
   and owns everything now — you can delete your old `argo-anywhere.sh` file.
2. **Nothing to migrate by hand.** Your cached username / node / port and the
   install manifest move themselves on the first run.
3. **Tidy the old version's leftovers** — superseded copies on your laptop *and*
   on the compute node. Run `argo-anywhere clean` after `connect`, which reuses
   the live channel so the node cleanup costs no extra Duo. Preview it first
   with `argo-anywhere clean --dry-run`.

> If you added `. ~/.argo_anywhere/env` to your `~/.zshrc` / `~/.bashrc` for the
> old version, remove that line — the package doesn't use it.

### Coming from v1.x (you ran `argo_opencode.sh`)

1. **Install the package:** `pipx install argo-anywhere`.
2. The **first run refuses to start** while v1.x state is present and prints the
   exact 2–3 cleanup commands — run them, then re-run.
3. Continue as **New to argo-anywhere** above.

---

No hidden state: everything argo-anywhere puts on your machine is visible with
`argo-anywhere info` and removable with `argo-anywhere uninstall` (which also
restores your AI-tool configs to their pre-argo state).

---
## Behavior changes between releases

Per-release detail lives in [`CHANGELOG.md`](../CHANGELOG.md) — what shipped,
what broke, what to do about it, from v3.1.0 onward. That is the document to
read when you want to know why something moved.

For releases before v3.1.0, and for the v1.x → v2.x and v2.x → v3.0.0
migrations in full detail, see
[`UPGRADING_HISTORY.md`](UPGRADING_HISTORY.md). You need it only if you are
resurrecting a genuinely old install; everything current is covered above.

## Things that did not change

Across every version bump, these have held:

- **Your cached state** (`~/.config/argo_anywhere/`), SSH sockets, and the
  whole connect/Duo flow carry forward. No v3 → v3 upgrade migrates state.
- **The engine is one self-contained `bash` file**, `scp`'d to the compute node
  and re-exec'd there as `server`. v3 vendors it verbatim rather than
  replacing it.
- **bash 3.2+ target** (macOS default), so the engine runs on a stock Mac.
- **One Duo prompt per session**, via the SSH multiplex master.
- **Your AI-tool configs are yours.** argo-anywhere records whether it created
  or modified each one, and `argo-anywhere uninstall` restores them.

## Where to read more

- [`README.md`](../README.md) — top-level user-facing entry point.
- [`CHANGELOG.md`](../CHANGELOG.md) — per-release detail (v3.1.0 onward).
- [`UPGRADING_HISTORY.md`](UPGRADING_HISTORY.md) — the full v1 → v2 → v3.0.0
  archive.
- [`docs/SECURITY.md`](SECURITY.md) — threat model, CSPO defenses, privacy
  posture.
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) — known limitations.
- [`docs/TESTING.md`](TESTING.md) — live-verification guide.

If something broke during your upgrade that isn't covered here, file an issue
at <https://github.com/a-attia/argo-anywhere/issues> with the invocation that
failed and the relevant log lines.

---

*Created 2026-05-15 by Ahmed Attia (with substantial AI assistance from Claude
per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Revised 2026-08-25: reduced to
the install-and-migrate router it had become in practice, moving ~880 lines of
per-release history for v1.x → v3.0.0 into
[`UPGRADING_HISTORY.md`](UPGRADING_HISTORY.md) so the routing advice is the
document rather than its preface.*
