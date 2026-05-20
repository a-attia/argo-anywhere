# Resolved feedback entry: setdefault for security-defaulted keys

| Field | Value |
|:------|:------|
| Date logged | 2026-05-14 |
| Date resolved | 2026-05-17 |
| F-ID(s) | F-04 |
| Resolution | Codified upstream as rule 12.2 in `skills/research-software-engineering/references/12-shell-and-cross-language-interop.md` |
| Upstream commit | `686b3a1` (Session A, scicomp-research-skills repo) |
| Original location | `notes/agent_feedback.md` lines 271-344 (pre-cleanup) |

---

## 2026-05-14 -- `setdefault` for security-defaulted keys preserves the wrong default on upgraders

**Project context**: Phase 2b live test #1, second finding (after
the H5 yaml_scalar regression). The P2 fix changed
`write_argoproxy_config` to default `verbose: false` (privacy-
relevant; controls whether argo-proxy logs prompts to disk on the
compute node). The implementation used `data.setdefault('verbose',
verbose_default)` in the PyYAML merge path so that a user who had
explicitly chosen `verbose: true` would have their choice preserved.

**Trigger**: external-failure (user dumped the config file after a
successful H5 amendment verification and pasted contents; the file
showed `verbose: true` despite the script having been re-run
multiple times since the P2 fix landed).

**Skill(s) involved**: `research-software-engineering` (the rule
this would belong under is "API design / defaults that change
meaning between versions").

**Observation**: `setdefault` is the right primitive for keys
where the file's existing value reflects a real user choice
(e.g. `argo_base_url`: a user pointing at a dev Argo endpoint
should not have that overwritten on every config rewrite). It is
the WRONG primitive for keys where the prior value was set
automatically by an older version of the same script -- in that
case, "preserving" the old value silently keeps the upgrader on
the OLD default, defeating the entire purpose of changing the
default. From the file alone you cannot tell "user explicitly
chose X" from "old script defaulted to X". For security-relevant
defaults this means `setdefault` is unsafe; the explicit-opt-in
channel must live elsewhere (CLI flag / env var) so the file
content can be authoritatively overwritten on every write.

**Proposed action**: Add a rule (or extend the existing one) to
`research-software-engineering` covering "changing security-
relevant defaults across versions." Concrete shape:

> **Defaults that change meaning between versions**: when a new
> version of a script flips a security-relevant default (e.g.
> verbose-logging off, debug mode off, telemetry off), do NOT
> use `setdefault` / "preserve existing value" merge logic in
> the config writer for that key. From the file alone you cannot
> distinguish "user explicitly opted in" from "previous version
> defaulted in." For security defaults the answer is to:
> (a) overwrite the key with the script's chosen default on every
>     write,
> (b) provide an explicit opt-in channel (CLI flag / env var) for
>     users who really want the non-default behavior, and
> (c) document the upgrade-path implication: pre-existing files
>     will have the new default applied on the first write after
>     upgrade, regardless of their prior contents.
>
> `setdefault` IS appropriate for keys that genuinely vary by
> deployment (e.g. alternate API endpoints, custom timeouts) --
> values the user picked deliberately and that have nothing to
> do with the script's security posture.

This rule pairs naturally with the bash/PyYAML interop rule above:
both are "writer's view of the file" disciplines that come up when
a shell script + Python heredoc cooperate to manage a YAML config.

**Evidence / minimal repro**: Phase 2b live test #1 transcript;
user pasted `~/.config/argoproxy/config.yaml` contents showing
`verbose: true` (last line of file) after the P2 fix had been
shipped + the script re-run multiple times. The config also showed
`argo_base_url` appended at the bottom in non-alphabetical
position, evidence that the `setdefault('argo_base_url', ...)` in
the same merge block had run on a config that already had every
other key -- the appendix-positioning is PyYAML's `safe_dump
sort_keys=False` insertion-order signature for a key that was
absent originally and got added during the merge.

**Status**: resolved upstream 2026-05-17 (commit `686b3a1`) as
rule 12.2.
