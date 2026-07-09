# Live-test plan -- aider (Phase 5a) + lifecycle commands (D-024 connect/configure/run + D-025 install/uninstall)

**Status**: **PASSED 2026-07-09** — all 10 tests green (Test 4 full
`--ensure` channel-down bring-up deferred to a from-scratch run; the
already-up no-op path passed). 7 amendments landed mid-test (see
`notes/impl_lifecycle_commands.md` "Live-test amendments"): A conflict
text, B configure-box suppression, C de-OpenCode-centric summary,
update-models tool-awareness, connect verb-message, run box suppression,
+ the `$SB` sandbox guard in this plan. Real `~/.argo_anywhere` migrated
to the bin/ layout during Test 10 (channel stayed up throughout).
**Owner**: Ahmed Attia. **Created**: 2026-07-09.
**Covers**: aider integration (Phase 5a) + the three-level verb split
(`connect` / `configure` / `run`, D-024) + symmetric install/uninstall
with the install manifest (D-025). Companion design docs:
[`impl_codex_aider.md`](impl_codex_aider.md) +
[`impl_lifecycle_commands.md`](impl_lifecycle_commands.md).

This plan follows the project's live-verification discipline
([`docs/TESTING.md`](../docs/TESTING.md)): real SSH + real Duo + real
argo-proxy on a real ANL compute node. Run it before tagging the release
that ships these features.

---

## How to read this plan

- Each test is: **what it proves**, then a numbered set of steps, then
  the **PASS** criteria. Explanatory notes are in prose ABOVE each code
  block; the code blocks are comment-free so they paste cleanly into any
  shell (bash or zsh -- macOS defaults to zsh, which mis-parses inline
  `# (parens)` comments).
- Commands assume you run from the repo working tree, invoking
  `bash argo_anywhere.sh ...` (so you test the working-tree code, not a
  previously-installed canonical copy). Where a test needs the INSTALLED
  copy, it says so explicitly.
- Two similarly-named files appear; keep them distinct:
  - `~/.aider.conf.yml` -- the aider config we write.
  - `~/.aider.model.settings.yml` -- the sibling per-model settings we
    also write (disables `temperature` for reasoning models).

## SAFETY RULES (read first)

Some of these commands tear down state. To avoid killing a channel other
work depends on:

1. **Never run a non-dry `uninstall` / `stop` / `clean` while a channel
   you care about is up on that port.** The ownership guard protects
   *shared/foreign* channels, but a channel that is legitimately YOURS
   (`ours-*`) WILL be reclaimed by `uninstall` -- that's correct, but be
   sure you meant it.
2. **Prefer `--dry-run` first** for every `install` / `uninstall` /
   `clean` step; only run the live version once the dry-run plan looks
   right.
3. The **install/uninstall isolation tests** (Test 7-9) use a throwaway
   `HOME` AND a dead `--port` so they cannot touch your real channel or
   real `~/.argo_anywhere`. Do not remove either isolation.

---

## Pre-test snapshot

Record the starting state so you can confirm nothing unexpected changed.
Run each line and note the output.

Script version + syntax:

```sh
bash argo_anywhere.sh -h >/dev/null && echo "usage OK"
grep -m1 '^SCRIPT_VERSION=' argo_anywhere.sh
```

Current channel + cache (if you have one running):

```sh
cat ~/.config/argo_anywhere/port
curl -fsS --max-time 3 "http://localhost:$(cat ~/.config/argo_anywhere/port 2>/dev/null)/health"
```

Current install layout (flat vs bin/) and configs that already exist:

```sh
ls -la ~/.argo_anywhere 2>/dev/null
ls -la ~/.argo_anywhere/bin 2>/dev/null
ls -la ~/.aider.conf.yml ~/.aider.model.settings.yml ~/.config/opencode/config.json 2>/dev/null
```

---

## Test 1 -- aider end-to-end via the fused `client` flow

**Proves**: aider installs (self-contained installer), config + model-
settings are written, and a real chat works through the tunnel including
opus-4.8 (the temperature/reasoning fix).

Steps:

1. Bring up the aider flow (Duo prompt expected once). Pick a node.

```sh
bash argo_anywhere.sh --cli-tool aider client
```

2. Wait for the ALL GREEN summary. In another terminal, confirm the two
   files exist and the model default carries the `argo:` prefix:

```sh
cat ~/.aider.conf.yml
grep -c 'use_temperature: false' ~/.aider.model.settings.yml
```

3. Run aider on the default model and ask it to identify itself:

```sh
aider --message "reply with exactly: DEFAULT-OK"
```

4. Run aider on opus-4.8 (the model that returned empty before the fix):

```sh
aider --model openai/argo:claude-opus-4.8 --message "which model family are you?"
```

**PASS**:
- `~/.aider.conf.yml` has `openai-api-base: http://localhost:<port>/v1`,
  `openai-api-key: <your-ANL-username>`, `model: openai/argo:gpt-4o`,
  and `model-settings-file:` pointing at the sibling file.
- The settings file has 40+ `use_temperature: false` entries.
- Step 3 prints `DEFAULT-OK` (non-zero tokens received).
- Step 4 returns a real Claude/Anthropic answer (NOT "Empty response").

---

## Test 2 -- `connect` holds the shared channel; `configure` reuses it

**Proves**: the level-1/level-2 split -- `connect` owns the channel in
one window; `configure` in another window detects and reuses it WITHOUT
opening a second tunnel or firing Duo again.

Steps:

1. In WINDOW 1, bring up the channel and leave it running:

```sh
bash argo_anywhere.sh connect
```

2. Wait for ALL GREEN. In WINDOW 2, configure two tools at once against
   the existing channel:

```sh
bash argo_anywhere.sh configure opencode aider
```

3. Confirm WINDOW 2 did NOT open its own tunnel (no Duo prompt, no
   "Opening multiplexed SSH master" line) and returned to the prompt
   (did not block in a monitor).

**PASS**:
- WINDOW 2 prints `Channel is up on http://localhost:<port> (reusing it)`.
- No Duo prompt in WINDOW 2; no second SSH master opened.
- Both tools report configured; WINDOW 2 returns to the shell prompt.
- WINDOW 1 is still holding the channel (still in its monitor loop).

---

## Test 3 -- `configure` with NO channel fails loud with a hint

**Proves**: D-e -- `configure` does not silently open a channel; it tells
the user to run `connect` (or pass `--ensure`).

With NO channel running (stop WINDOW 1 from Test 2 first, or use a fresh
terminal on a port with nothing on it), run:

```sh
bash argo_anywhere.sh configure aider --port 59987
```

**PASS**: dies with `No argo-anywhere channel is answering ...` and the
two-line hint (`connect` in another window, or `--ensure`). Nothing is
configured; no tunnel opened.

**Note**: `--port 59987` writes that port into the cache (write-through,
D-020). After this test, reset the cache to your real port:

```sh
echo <your-real-port> > ~/.config/argo_anywhere/port
```

---

## Test 4 -- `configure --ensure` brings the channel up

**Proves**: the one-shot escape hatch -- `configure --ensure` establishes
the channel if it is not up, then configures.

With no channel up, run (Duo prompt expected; pick a node):

```sh
bash argo_anywhere.sh configure aider --ensure
```

**PASS**: it reports the channel was not up, brings it up (tunnel +
proxy), configures aider, and returns. A subsequent
`bash argo_anywhere.sh status` reports ALL GREEN.

---

## Test 5 -- `run` configures + launches a client

**Proves**: level-2+3 -- `run TOOL` configures then execs the client.

With a channel up (from Test 4), run:

```sh
bash argo_anywhere.sh run aider
```

**PASS**: aider launches (you land in aider's prompt). Type `/exit` to
leave. If aider is not yet on PATH in this shell, `run` instead prints a
"open a new shell" note rather than failing -- that is acceptable.

---

## Test 6 -- regression: existing verbs unchanged

**Proves**: `client` / `setup` / `tunnel` / `status` / `stop` still work.

```sh
bash argo_anywhere.sh --cli-tool opencode client
```

In another terminal, once ALL GREEN:

```sh
opencode
```

**PASS**: OpenCode connects and answers as before; no behavior change
from the aider / verb work.

---

## Test 7 -- `install` (isolated; dry-run then live)

**Proves**: explicit install builds the `bin/` layout + wrappers + env +
manifest stamp, and migrates a flat-layout install.

These steps use a THROWAWAY HOME and a DEAD port so they cannot touch
your real setup. Set up the sandbox.

**IMPORTANT**: `$SB` must be set in the SAME terminal you run every
sandbox command in. If it is empty, paths like `"$SB/created.yml"`
expand to `/created.yml` and target the filesystem ROOT. So every
sandbox block below begins by RE-ASSERTING `SB` and guarding against an
empty value -- run each block in one shell, and if you open a new
terminal, re-run the `SB=...` guard line first.

```sh
SB=/tmp/argo_lifecycle_test; : "${SB:?SB must be set}"; case "$SB" in /tmp/*) ;; *) echo "REFUSING: SB not under /tmp"; return 2>/dev/null || exit 1;; esac
rm -rf "$SB" && mkdir -p "$SB" && echo "sandbox ready at $SB"
```

Dry-run first (should change nothing):

```sh
HOME="$SB" bash argo_anywhere.sh install --dry-run --port 59987
ls -la "$SB/.argo_anywhere" 2>/dev/null
```

Then live:

```sh
HOME="$SB" bash argo_anywhere.sh install -y --port 59987
ls -1 "$SB/.argo_anywhere/bin"
grep -o 'argo_anywhere/bin' "$SB/.argo_anywhere/env" | head -1
python3 -c "import json;print(json.load(open('$SB/.argo_anywhere/manifest.json')).get('installed_at'))"
```

**PASS**:
- Dry-run creates nothing under `$SB/.argo_anywhere`.
- Live install creates `bin/argo_anywhere.sh`, `bin/install`,
  `bin/uninstall`; `env` mentions `argo_anywhere/bin`; the manifest has a
  non-null `installed_at`.

---

## Test 8 -- `uninstall --restore-configs` (isolated; the honest-restore test)

**Proves**: D-c -- uninstall deletes configs the script CREATED and
restores configs the script MODIFIED to their pre-argo original.

Continue in the sandbox from Test 7. **Re-assert `SB` first** (guards
against an empty value targeting `/`; run in the SAME shell as Test 7 or
this line re-establishes it). Then seed two configs + manifest
provenance: one "created by us", one "modified by us" with an original
backup.

```sh
SB=/tmp/argo_lifecycle_test; : "${SB:?SB must be set}"; case "$SB" in /tmp/*) ;; *) echo "REFUSING"; return 2>/dev/null || exit 1;; esac
printf 'argo-wrote-this\n' > "$SB/created.yml"
printf 'argo-modified-this\n' > "$SB/modified.yml"
printf 'USER-ORIGINAL\n' > "$SB/modified.yml.bak.20260101-000000.111"
python3 - "$SB/.argo_anywhere/manifest.json" "$SB/created.yml" "$SB/modified.yml" <<'PY'
import json,sys,datetime
mf,created,modified=sys.argv[1:4]
d=json.load(open(mf)); now=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
d["configs"][created]={"first_touched":now,"preexisted":False,"created_by_us":True}
d["configs"][modified]={"first_touched":now,"preexisted":True,"created_by_us":False}
json.dump(d,open(mf,'w'),indent=2)
PY
```

Dry-run the restore (changes nothing):

```sh
HOME="$SB" bash argo_anywhere.sh uninstall --dry-run --restore-configs -y --port 59987
```

Then live:

```sh
HOME="$SB" bash argo_anywhere.sh uninstall --restore-configs -y --port 59987
echo "created.yml exists: $([ -f "$SB/created.yml" ] && echo yes || echo no)"
cat "$SB/modified.yml"
echo "canonical exists: $([ -d "$SB/.argo_anywhere" ] && echo yes || echo no)"
```

**PASS**:
- Dry-run prints "would remove ... created.yml" and "would restore ...
  modified.yml" and changes nothing.
- Live: `created.yml` is GONE; `modified.yml` contains `USER-ORIGINAL`;
  the canonical dir is GONE.

---

## Test 9 -- ownership guard (isolated; the safety property)

**Proves**: uninstall NEVER kills a channel it does not own. This is the
fix for the methodology defect where a sandboxed uninstall killed a live
shared listener.

The dead port `59987` has no listener, so uninstall must simply not try
to kill anything there. To positively exercise the guard, you can ALSO
check the classification of your real channel (read-only; does not kill):

```sh
HOME="$SB" bash argo_anywhere.sh uninstall --dry-run -y --port 59987
```

Then (read-only) confirm the guard would classify YOUR real channel as
yours (so a real uninstall on the real port would correctly reclaim it),
without running uninstall on it:

```sh
bash argo_anywhere.sh status
```

**PASS**:
- The dead-port uninstall never reports killing a listener.
- `status` on your real port reports ALL GREEN (the guard reads it as
  `ours-healthy-mux` internally; you are NOT asked to uninstall it).

Clean up the sandbox (guarded so an empty `SB` can't `rm -rf /`):

```sh
SB=/tmp/argo_lifecycle_test; : "${SB:?SB must be set}"; case "$SB" in /tmp/*) rm -rf "$SB" && echo "removed $SB";; *) echo "REFUSING to rm '$SB'";; esac; unset SB
```

---

## Test 10 -- real `bin/` migration (optional; touches real ~/.argo_anywhere)

**Proves**: your real flat-layout install (`~/.argo_anywhere/argo_anywhere.sh`)
migrates into `bin/` cleanly on the next `install`.

Only run this if you are comfortable letting the script reorganize your
real `~/.argo_anywhere`. Back it up first:

```sh
cp -R ~/.argo_anywhere ~/.argo_anywhere.pretest_backup
bash argo_anywhere.sh install --dry-run
```

If the dry-run plan looks right (it should report a flat-layout
migration), run it live:

```sh
bash argo_anywhere.sh install
ls -1 ~/.argo_anywhere/bin
which argo_anywhere.sh 2>/dev/null || echo "(source ~/.argo_anywhere/env in a new shell to test PATH)"
```

**PASS**: `~/.argo_anywhere/bin/argo_anywhere.sh` exists; the old flat
`~/.argo_anywhere/argo_anywhere.sh` is gone (moved); `env` points at
`bin/`. Restore your backup afterward if you want the pre-test state:

```sh
rm -rf ~/.argo_anywhere && mv ~/.argo_anywhere.pretest_backup ~/.argo_anywhere
```

---

## Post-test checklist

- [ ] Test 1 aider (default + opus-4.8) both answer.
- [ ] Test 2 configure reuses the connect channel (no 2nd tunnel/Duo).
- [ ] Test 3 configure-without-channel fails with the hint.
- [ ] Test 4 configure --ensure brings the channel up.
- [ ] Test 5 run launches the client.
- [ ] Test 6 opencode/claudecode regression clean.
- [ ] Test 7 install (dry + live) builds bin/ + manifest.
- [ ] Test 8 uninstall restores configs honestly (delete created;
      restore modified).
- [ ] Test 9 ownership guard: never kills a channel it doesn't own.
- [ ] Test 10 (optional) real bin/ migration.
- [ ] Port cache reset to your real port after Tests 3/7-9.
- [ ] Record any amendments as separate commits (project convention);
      note the final HEAD SHA for the release tag.

## After the run

Report which tests passed and paste any unexpected output. Per the
project's amendment-mid-test cadence, any defect found here is fixed as a
separate commit before tagging; the tag points at the final amended HEAD.
Fold results back into `notes/impl_codex_aider.md` (Phase 5a) and
`notes/impl_lifecycle_commands.md` (Phases A/B/C) status lines.

---

*Created 2026-07-09 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Comment-free code
blocks + shell-agnostic constructs per the test-plan-authoring lessons in
`notes/agent_feedback.md` (2026-05-18 zsh-tokenization entry).*
