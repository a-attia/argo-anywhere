# Live-test plan — v3.1.0 (extras consolidation + PyYAML fix + D-032 ssh-config-native)

**Status**: **OPEN** — awaiting execution against the four commits merged to
`main` after `v3.0.1`. This is the at-the-keyboard gate before tagging v3.1.0.
**Owner**: Ahmed Attia (with Claude).
**Created**: 2026-07-15.

**Commits under test**:
- `5565048` — build(pyproject): consolidate extras to single-mode default install
- `4fd9356` — docs(notes): design records for PyYAML self-heal + ssh-config-native support
- `b80970c` — fix(engine): guarantee PyYAML in venv + drop dead [m] menu option
- `4b8c445` — feat(engine): D-032 ssh-config helpers + --jump-host plumbing (no-op patch)
- `86d2845` — feat(engine): D-032 Sub-fixes A/B/C wired in (ssh-config-native support live)
- `9d45344` — docs(engine): D-032 docs + PLAN.md D-032 + this file
- `68e4a00` — feat(web): D-032 launcher node/user/jump-host fields + build_launch_argv extension (C4)
- `0626659` — feat(web): D-032 /api/ssh-hosts alias picker + refresh button (C5)
- `643de22` — feat(web): D-032 /api/preview-launch panel + AGENTS.md coupling subsection (C6)
- `99f1e46` — docs(audit): post-execution audit of the v3.1.0 D-032 + PyYAML sequence

## CSPO discipline (read first)

- **One clean SSH/Duo attempt per real-infra test.** 3 failures within 15 min
  risks a weekend lockout. The real-infra tests below (T4, T5) each hit exactly
  one SSH + one Duo prompt.
- **Never** run a non-dry `uninstall` / `stop` / `clean` against the port with
  your live channel. Where a test needs uninstall, use `--dry-run` **and** a dead
  `--port` (e.g. 59999) **and** a sandbox `HOME`.
- `argo-anywhere info` and the footprint scan reach nothing; `/health` is not
  polled by `info`.
- **D-032 preview endpoint safety**: `/api/preview-launch` uses `ssh -G` which
  does NOT authenticate — no Duo, no failure-counter interaction. Fire it
  freely during Track W tests.

## Preconditions

Install the branch so the console script has all the commits.

**Pre-merge (branch not yet pushed): install from the local working tree** — no
GitHub round-trip, tests the exact local state:

```sh
cd <repo>                          # the argo-anywhere checkout
pipx install --force .
argo-anywhere --version            # 3.1.0-dev or the version at test time
```

**Post-push / post-publish:** the git-URL / PyPI forms work once the branch is on
GitHub / PyPI.

---

## Track 1: extras consolidation (commit `5565048`)

**T1 — `pipx install argo-anywhere` delivers web+app out of the box.**

Steps:
1. `pipx uninstall argo-anywhere` (from a clean starting state).
2. `pipx install argo-anywhere` (from the local working tree per Preconditions).
3. `pipx list` — verify `argo-anywhere` is installed; note the venv path.
4. Inspect the installed venv's site-packages: `ls ~/.local/pipx/venvs/argo-anywhere/lib/python*/site-packages/ | grep -E 'fastapi|uvicorn|webview'`.

**Expect:**
- `fastapi`, `uvicorn`, and `pywebview` are all present in the venv (no `[app]` or `[web]` extras spec used).
- `argo-anywhere web` and `argo-anywhere app` both start (T2).

**T2 — `argo-anywhere web` and `argo-anywhere app` both work without extras.**

Steps:
1. `argo-anywhere web --port 8801` in one terminal. Browser to
   `http://127.0.0.1:8801` — page loads.
2. Kill T2's server (Ctrl-C).
3. `argo-anywhere app --port 8802` — native window opens (or browser
   fallback if the platform webview backend is missing).

**Expect:** both verbs work with zero extras-related error messages. No prompt to
install `[app]` or `[web]`.

**T3 — `install-launcher` works out of the box.**

Steps:
1. `argo-anywhere install-launcher --dry-run` — lists what would be created.
2. `argo-anywhere install-launcher` — actually creates the launcher(s).
3. macOS: verify `~/Desktop/argo-anywhere.command` and
   `~/Applications/argo-anywhere.app` exist. Linux: verify
   `~/.local/share/applications/argo-anywhere.desktop` and
   `~/Desktop/argo-anywhere.sh`.
4. Double-click the launcher (or `open` it) — app opens.
5. `argo-anywhere uninstall --dry-run` — reports the launcher files.
6. `argo-anywhere uninstall` — removes them cleanly.

**Expect:** launcher install + uninstall round-trip; no "install
`argo-anywhere[app]` first" error.

---

## Track 2: PyYAML self-heal + [m] menu accuracy (commit `b80970c`)

**T4 — PyYAML self-heal on a fresh compute node.**

Steps (all on the laptop unless prefixed with `# (on <node>):`):
1. Pick an ANL compute node you have not connected to for a while, or where
   `~/argovenv` was previously wiped: `argo-anywhere --node <node> connect`.
2. Watch the bootstrap log stream. After the `argo-proxy` install line, verify
   these lines appear:
   ```
   [ ok ] argo-proxy: argo-proxy <version>
   [ ok ] PyYAML installed in /home/<user>/argovenv.       # OR
   [ ok ] PyYAML in /home/<user>/argovenv: <version>
   ```
3. `# (on <node>):` `~/argovenv/bin/python -c 'import yaml; print(yaml.__version__)'`
   — succeeds.

**Expect:** PyYAML is present in the venv after every bootstrap, regardless of
whether argo-proxy shipped it transitively. The
`[ ok ] PyYAML in <venv>: <version>` line appears on every subsequent bootstrap
even when no install was needed.

**T5 — `[m]` menu option is suppressed for YAML files.**

Steps (requires an existing tunnel; combine with T4):
1. On the compute node, add a spurious key to the config so the writer's
   proposed file differs: `echo 'argo_test_key: preserved' >> ~/.config/argoproxy/config.yaml`.
2. From the laptop, re-run `argo-anywhere --node <node> connect`.
3. On the compute node's `~/.argo-anywhere.server.log`, watch the
   `handle_config_file` prompt:
   ```
   [warn] argo-proxy config already exists at /home/<user>/.config/argoproxy/config.yaml and differs from the proposed version.
   
     Choose how to handle /home/<user>/.config/argoproxy/config.yaml:
       [k] keep existing (no changes)
       [b] backup existing to .bak.<timestamp>, then overwrite
       [d] show diff (existing -> proposed), then ask again
       [a] abort
   Your choice [k/b/d/a]:
   ```

**Expect:**
- The `[m]` option is **absent** from the menu (was present pre-fix).
- The prompt reads `[k/b/d/a]` not `[k/b/d/m/a]`.
- Typing `m` at the prompt gives a teaching message: "Merge is not offered for
  YAML here (the writer already merges before this prompt). Pick [k]/[b]/[d]."

---

## Track 3: D-032 ssh-config engine (commits `4b8c445`, `86d2845`, `9d45344`)

**T6 (Scenario X) — `--node <ssh-config-alias>` end-to-end.**

**Precondition**: your `~/.ssh/config` has a block like:
```
Host polaris-login             # or whatever your alias is
    HostName compute-XX.cels.anl.gov
    User <your-ANL-username>
    ProxyJump <your-ANL-username>@logins.cels.anl.gov
```
and `ssh polaris-login` works (one Duo prompt).

Steps:
1. Clear any relevant caches so the inference path fires:
   `rm -f ~/.config/argo_anywhere/user`
2. `argo-anywhere --cli-tool opencode client --node polaris-login`
   (no `--user`, no `--no-jump`).
3. Watch the log stream.

**Expect:**
- Alias detection: log line `Note: 'polaris-login' is an ssh_config alias
  (resolves to compute-XX.cels.anl.gov); proceeding via ~/.ssh/config.`
- Username inference: log line `Using ANL username: <your-ANL-username>
  (source: ssh-config:polaris-login)`.
- Jump-host skip: log line `Note: polaris-login already routes via ~/.ssh/config;
  not adding our -J <your-user>@logins.cels.anl.gov.` (fires ONCE per session
  via dedup, even though `ssh_jump_args` is called ~10 times).
- Single Duo prompt (from the alias's own ProxyJump).
- ALL GREEN status card.
- **Cache invariant**: `cat ~/.config/argo_anywhere/user` — verify the file is
  STILL ABSENT (ssh-config-inferred usernames are never cached, per D-032).

**T7 — `--jump-host HOST` overrides `ANL_JUMP` in status output.**

Steps:
1. `ARGO_ANYWHERE_JUMP_HOST=bastion.example.com argo-anywhere status`
2. Inspect the status card.

**Expect:**
- The `Jump host: bastion.example.com` line appears (was
  `logins.cels.anl.gov` pre-D-032).
- Command exits cleanly (0 or 1 based on your actual tunnel state; the
  jump-host override is not connecting to anything, just displaying).

**T8 — `--jump-host ""` (CLI-empty) dies with a helpful message.**

Steps:
1. `argo-anywhere --jump-host "" help ; echo "rc=$?"`

**Expect:**
- Exit code non-zero.
- Error message includes `--no-jump` as the "skip jump host" instruction.

**T9 — `ARGO_ANYWHERE_JUMP_HOST=""` (env-empty) is treated as `--no-jump`.**

Steps:
1. `ARGO_ANYWHERE_JUMP_HOST="" argo-anywhere status`

**Expect:**
- Runs cleanly (no die).
- If the status card renders a "Jump host: (skipped)" or similar treatment when
  `ARGO_ANYWHERE_NO_JUMP=1` is on, that's what should appear. (If it still
  shows `logins.cels.anl.gov`, that's an audit item for a follow-up commit —
  D5 elevation from C3 was to update the status card to reflect no-jump state;
  document what actually happens here.)

---

## Track 4: D-032 ssh-config web UI (commits `68e4a00`, `0626659`, `643de22`)

**Precondition**: your `~/.ssh/config` has the Track-3 T6 alias block
(a `Host polaris-login` entry, or whatever alias you tested with in T6).
Web tests reuse the same alias for consistency.

**W1 — launcher fields end-to-end.**

Steps:
1. `argo-anywhere app --port 8801` (or `argo-anywhere web --port 8801` +
   open `http://127.0.0.1:8801` in a browser).
2. Click the "Launch" button in the top-right to open the launcher popover.
3. Verify the "SSH target overrides" `<details>` element is present + collapsed
   below the working-directory field.
4. Expand it. Type `polaris-login` into the "compute node" field; leave
   "ANL username" and "jump-host" empty; leave "skip jump host" unchecked.
5. Verify the compute-node field's datalist populates with your ssh_config
   alias list (should include `polaris-login`).
6. Click Launch (target = embedded terminal by default).

**Expect:**
- The launcher POST reaches the engine with `--node polaris-login` in argv
  (verify via the Channel or Utility panel's opening log lines).
- Same ssh-config-native behavior as Track 3 T6: single Duo prompt,
  `Note: 'polaris-login' is an ssh_config alias ...` log line,
  `Using ANL username: <ANL-username> (source: ssh-config:polaris-login)`.
- ALL GREEN status in the embedded terminal.

**W2 — divergence highlighted in preview panel.**

Steps:
1. Reopen the launcher popover.
2. Type `polaris-login` in "compute node".
3. Type `some-other-user` in "ANL username" (deliberately different from
   the alias's `User <name>`).
4. Wait ~1 second for the debounced `/api/preview-launch` to fire.

**Expect:**
- The preview panel auto-expands with an amber summary chip
  `⚠ Divergence — review before launch`.
- The preview body shows the `User: some-other-user ⚠ ssh_config says
  <ANL-username>` divergence line in the theme's warn color.
- Clicking Launch WOULD proceed with `some-other-user` (engine's
  precedence: explicit --user wins over ssh_config inference); the
  preview is informational.

**W3 — picker offers ssh_config aliases.**

Steps:
1. Reopen the launcher popover.
2. Focus the compute-node field. Verify the datalist dropdown shows
   your aliases from `~/.ssh/config`.

**Expect:**
- Aliases like `polaris-login` present.
- Wildcard patterns (`*`, `?`, `[abc]`) and negated patterns (`!gateway`)
  absent.
- Click the refresh button (↻) — verify `curl -s
  http://127.0.0.1:8801/api/ssh-hosts?refresh=1` succeeds and the
  datalist repopulates.

**W4 — `/api/preview-launch` IP-block safety smoke.**

Steps:
1. `curl -s -X POST -H 'content-type: application/json' -d '{"node":
   "some-random-unresolvable-alias"}' http://127.0.0.1:8801/api/preview-launch`

**Expect:**
- Response: `{"state": "unresolved"}`.
- Zero Duo prompts triggered by the request.
- `~/.config/argo_anywhere/ssh-fail-lock` NOT created (D-012 tracker
  untouched).

---

## Closure gate

**Sign here when the plan passes**:

- Track 1 (extras): PASS / FAIL — date, tester, notes.
- Track 2 (PyYAML + [m] menu): PASS / FAIL — date, tester, notes.
- Track 3 (D-032 engine): PASS / FAIL — date, tester, notes.
- Track 4 (D-032 web UI): PASS / FAIL — date, tester, notes.

Any FAIL: file an issue with the STDERR from the failed test + `argo-anywhere info
--json` output; fix + amend the offending commit; re-run the failed track only.

Once ALL FOUR TRACKS pass, tag `v3.1.0` and publish from CI.

---

*Created 2026-07-15 by Ahmed Attia (with substantial AI assistance from Claude
per `CONTRIBUTORS.md`). Structure mirrors `notes/test_plan_v3_branch.md`'s
proven format. Track W tests are placeholders until C4-C6 land; this file
gets appended to as those commits stabilize.*
