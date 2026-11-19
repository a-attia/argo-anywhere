# argo-proxy's SQLite database on a shared `$HOME`: per-node, per-launch data dir

**Status**: implemented on `main` (2026-11-19), unreleased.
**Live-verified 2026-11-19** on `compute-386-01` + `compute-386-02`
concurrently (argo-proxy 3.3.3). `scripts/live_test_data_dir.sh --rotate`
reported ALL CHECKS PASSED: each process had its own `DATA_DIR`, each held
its own `gateway.db` open, integrity `ok` on both, no lock/malformed errors,
and rotation kept exactly one previous generation. Would earn **D-037**.
**Trigger**: field report 2026-11-19 (`error_report.txt`). On compute-01
argo-proxy logged `Failed to flush metrics: database is locked`; on
compute-02 it logged `Failed to flush metrics: database disk image is
malformed`. Connecting through the proxy became unreliable.

## TL;DR

- Since 3.3.0, argo-proxy keeps an SQLite database (`gateway.db`) for its
  admin dashboard. By default it sits next to the config file, at
  `~/.config/argoproxy/data/gateway.db`.
- On CELS, `$HOME` is one NFS mount shared by every compute node. Two
  nodes running argo-proxy therefore open **the same SQLite file**, in WAL
  mode. WAL needs shared memory between the processes, which cannot work
  across machines. SQLite documents WAL as unsupported on network
  filesystems. The two errors are the expected failures: the lock can't be
  coordinated ("locked"), and the file ends up corrupt ("malformed").
- This is the same shared-`$HOME` assumption as Q10 (the shared `port:`
  line in `config.yaml`, see `impl_shared_node_transport.md`), showing up
  in a second file.
- **Fix**: each launch gives argo-proxy a database directory of its own
  node (`~/.config/argoproxy/data-<host>`). The previous session's
  directory is kept as `data-<host>.prev`, and the one before that is
  deleted. The request-log caps are also lowered. Nothing accumulates, and
  a corrupt file is never reopened.

## 1. Mechanism (read from source, argo-proxy 3.3.3 / llm-rosetta 0.13.0)

| What | Where |
|:-----|:------|
| Background flush every 30s; logs the reported warning on any exception | `llm_rosetta/gateway/app.py` `_periodic_flush` |
| WAL journal mode, `synchronous=NORMAL` | `llm_rosetta/observability/persistence.py` `PersistenceManager.__init__` |
| Default directory `dirname(config_path)/data` when no `data_dir` | `llm_rosetta/gateway/admin/__init__.py` `_init_persistence` |
| argo-proxy always passes its config path, so persistence is **always on** (no off switch) | `argoproxy/app.py` `setup_admin(...)` |
| Override: `--data-dir` flag or `DATA_DIR` env (the flag just sets the env) | `argoproxy/cli/handlers.py`, `argoproxy/config/io.py` |

**Why it is more than a log warning.** The flush is wrapped in
`try/except`. The per-request write, `request_log.add` called from
`_record_telemetry`, is not guarded at that level. A locked or corrupt
database can therefore affect live requests, and a badly corrupt file can
stop the proxy at startup, because `PersistenceManager.__init__` runs
`CREATE TABLE`.

**Version history** (checked against the PyPI wheels):

| argo-proxy | Has `gateway.db` | Can relocate it |
|:-----------|:----------------:|:---------------:|
| ≤ 3.2.3 | no | n/a |
| 3.3.0, 3.3.1 | **yes** | **no** |
| ≥ 3.3.2 | yes | yes (`--data-dir` / `DATA_DIR`) |

3.3.0 and 3.3.1 cannot be fixed from our side, so the engine warns and
points the user at `update argoproxy`.

## 2. How big can the database get?

Asked by the maintainer before choosing a location, because node-local
disk is small and shared by every user.

| Part | Cap | Configurable | Size at cap |
|:-----|:----|:-------------|:------------|
| Request log | 50,000 OK + 10,000 error rows | yes: `REQUEST_LOG_SUCCESS_MAX` / `REQUEST_LOG_ERROR_MAX` | **~28 MB** (measured locally, real schema, synthetic rows) |
| Error dumps | 10,000 (`DEFAULT_DUMP_MAX`, hard-coded) | **no** | **~0.4–4 GB** worst case (estimate) |

The dump estimate works like this. Each failed request stores its
compressed request body, and usually the converted body as well. A
coding agent resends the whole conversation on every turn, which is
~100 KB–1 MB of JSON and ~20–200 KB compressed. Two further properties
make it worse:

- the file **never shrinks**: pruning deletes rows, but `VACUUM` runs only
  from the manual `cleanup` CLI;
- age-based cleanup is also manual only.

So the file stays at the largest size it ever reached, and it grows
fastest when requests are failing.

## 3. Decision

| Choice | Picked | Why |
|:-------|:-------|:----|
| Location | `~/.config/argoproxy/data-<short-hostname>` | Per node, so no two machines ever share a file. Stays in `$HOME` (user quota) rather than scarce node-local disk. |
| Lifetime | Rotated **every launch**: current → `.prev`, old `.prev` deleted, fresh current | The size bound becomes "one session" and the never-shrinks problem disappears. A corrupt file is never reopened, so no integrity check is needed: rotation replaces the "repair on launch" option. |
| Keep `.prev`? | **yes, one generation** | People usually relaunch *because* the last session failed. Plain deletion would destroy that session's error dumps at exactly the moment they are wanted. The cost is at most one extra session of disk. |
| Request-log caps | `REQUEST_LOG_SUCCESS_MAX=1000`, `REQUEST_LOG_ERROR_MAX=500` | ~28 MB → < 1 MB. A value already set in the environment wins. |
| Transport of the setting | env vars on the launch line (`env DATA_DIR=… …`) | An argo-proxy that predates the flag ignores an unknown env var instead of dying on an unknown flag. Passed **explicitly** on each launch line, because a pre-existing tmux server would otherwise supply its own environment, not ours. |
| 3.3.0 / 3.3.1 | warn, do not auto-upgrade | Upgrades stay an explicit `update argoproxy` (D-022). UP-11 is the reminder that upstream releases can break. |
| Legacy shared `~/.config/argoproxy/data` | not touched by launch; logged as reclaimable; removed by `clean` | Another node may still be running an older proxy on it. Deleting a file that another NFS client has open breaks that process (ESTALE). `clean` is an explicit action, and it already removes the shared venv. |

**What remains unprotected.**

- **Error dumps within one session are still unbounded by any setting we
  can reach.** A session that loops on failures can write tens to hundreds
  of MB. Rotation reclaims the space on the next launch, not during the
  session.
- **SQLite WAL on NFS is still officially unsupported, even with one
  host.** All processes on a given file are now on the same machine, which
  is the case WAL's shared memory is designed for, so it should hold in
  practice. If it does not, the next launch rotates the bad file away.

## 4. Implementation

- `_argoproxy_prepare_data_dir` (engine, just before `mode_server`) sets
  the global `_ARGOPROXY_DATA_DIR`. It is **never `$()`-captured** (D-005),
  and it **never fails the launch**: every step degrades to a `warn`.
  Hostname: short form, sanitized to `[A-Za-z0-9._-]`, falling back to
  `unknown-host`.
- `mode_server` calls it once, after the session-cleanup checks and before
  the launcher `case`. It builds `_ap_env` (`DATA_DIR` + the two caps) and
  passes it via `env` on all three launch lines.
- A feature probe (`serve --help` mentions `--data-dir`) decides the
  3.3.0 / 3.3.1 warning. The help text is captured, then matched with
  `case`, because `| grep -q` under `pipefail` gives a false negative on
  SIGPIPE.
- The remote `clean` script removes `data`, `data-*` and `data-*.prev`.
- Pinned by `tests/test_engine_proxy_data_dir.py`. The existing launcher
  harnesses in `tests/test_engine_no_interactive_prompt.py` substitute
  `_ap_env`, the same way they substitute the binary and log paths.

**Why rotation can't hit a live process.** We reach the launch only when
nothing of ours serves `PROXY_PORT`. If an old proxy of ours on this node
is still holding the directory, renaming it is harmless: Linux file
descriptors follow the inode, so that process writes into `.prev`.
Deleting a `.prev` still held open leaves NFS `.nfsXXXX` files and `rm`
fails. That case is reported with a `warn`, and the launch continues.

## 4a. Follow-up: the argo-proxy log had the same defect

`~/argoproxy.out` was a third shared-`$HOME` file. Every node teed into it,
and each launch truncated it, so starting node B erased node A's
diagnostics, and from then on the file mixed both nodes' output. It is now
`~/argoproxy-<host>.out`. Its name and the data dir both come from one
helper, `_argoproxy_node_tag`, so the two can never disagree about which
node they belong to. `clean` removes the legacy name too.

## 5. Live verification

Automated by `scripts/live_test_data_dir.sh NODE_A:PORT_A NODE_B:PORT_B
[--rotate]`. The script assumes both channels are already up, and it rides
their SSH masters, so it never triggers Duo. It checks each database **on
its own node**, because reading another host's WAL database over NFS is
the pattern under test. Manual equivalent, run on two nodes at once with
both proxies up:

1. `ls ~/.config/argoproxy/` shows `data-<nodeA>` and `data-<nodeB>`, each
   with its own `gateway.db`.
2. Each node's `~/argoproxy-<host>.out` contains no `Failed to flush metrics`
   after several minutes of traffic.
3. Relaunching on node A produces `data-<nodeA>.prev`, holding the old
   database, and a fresh `data-<nodeA>`.
4. On a node with argo-proxy 3.3.0 or 3.3.1, the upgrade warning is printed.
