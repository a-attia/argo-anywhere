# Implementation plan -- richer model metadata in `list-models`

**Status**: investigated; designing. No code committed, nothing
scheduled.
**Owner**: Ahmed Attia. **Last updated**: 2026-08-14.
**Target repo**: <https://github.com/a-attia/argo-anywhere>.
**Linked PLAN.md sections**: none. Overlaps Open Question 3
("`update-models` per-tool generalization"). If anything beyond docs
ships it earns the next free D-number; per PLAN.md's rule, a note that
has not shipped does not hold one, so this note reserves nothing.

## Purpose

Decide whether `list-models` can tell a user who does not already know
the model landscape *which model to pick* -- something like "Anthropic,
mid cost, strong at code" beside `claude-sonnet-4.6` -- and where such
information would have to come from.

## Motivation

From a user, 2026-08-14:

> Would it be possible (or is it already possible) for a query like the
> models query to argo to return more information about the models. For
> those who don't know opus from sonnet from haiku, for example, brief
> information such as "Anthropic model, modest token cost, good at
> programming" for the sonnet models. The argo web interface has a
> little info/categorization like this, so maybe the API already has it
> and can already provide it with a different query besides models?

The request is reasonable and the current output does not serve it. Our
`list-models` prints `internal_name`, `id`, `provider`, `modalities`,
`configured` -- five columns of which four are identity and one
(`modalities`) is a constant. A user staring at 51 rows containing
`argo:claude-opus-4.8`, `argo:claude-sonnet-4.6` and
`argo:claude-haiku-4.5` gets no help choosing between them.

The specific hypothesis in the question -- *the API probably already has
this under a different endpoint* -- is testable, and this note exists
mainly to record that it was tested and is false.

## Findings

Investigated 2026-08-14 against the live gateway from `compute-01`,
through the maintainer's already-open SSH master. All probes were
read-only `GET`s.

### F1. The gateway serves no such metadata, from any endpoint

The Argo gateway publishes an OpenAPI 3.1 document at
`https://apps.inside.anl.gov/argoapi/openapi.json` (title *"Argo Gateway
API"*). Its complete route table is twelve entries:

| Method | Path | Summary |
|:--|:--|:--|
| GET | `/argoapi/api/v1/models/` | Get Models (legacy shape) |
| GET | `/argoapi/v1/models` | Get Openai Models |
| GET | `/argoapi/api/v1/resource/` | Get Resource (a GET test stub) |
| GET | `/argoapi/api/v1/resource/health/` | Health Check |
| POST | `/argoapi/v1/chat/completions` | Openai Chat Completions |
| POST | `/argoapi/v1/embeddings` | Openai Embeddings |
| POST | `/argoapi/v1/messages` | Anthropic Messages |
| POST | `/argoapi/v1/messages/count_tokens` | Anthropic Count Tokens |
| POST | `/argoapi/api/v1/resource/chat/` | Post Resource Chat |
| POST | `/argoapi/api/v1/resource/streamchat/` | Post Resource Streamchat |
| POST | `/argoapi/api/v1/resource/embed/` | Post Resource Embedding |
| POST | `/argoapi/api/v1/resource/rerank/` | Post Resource Reranker |

Only the two `models` routes enumerate models, and they are the same
data in two shapes. There is no `/capabilities`, no `/pricing`, no
per-model detail route. **The "different query besides models" the user
hoped for does not exist.**

Reproduce:

```bash
curl -fsS https://apps.inside.anl.gov/argoapi/openapi.json \
  | python3 -c 'import json,sys; [print(m.upper(),p) for p,o in json.load(sys.stdin)["paths"].items() for m in o]'
```

### F2. The upstream model record has five fields, none descriptive

`GET /argoapi/api/v1/models/` returned 37 models. The union of keys
across all 37 is exactly `{id, internal_id, object, created, owned_by}`:

```json
{"id":"Claude Sonnet 4.6","object":"model","created":1786728978,
 "owned_by":"anthropic","internal_id":"claudesonnet46"}
```

No description, no cost tier, no context window, no capability tags, no
recommended-use text. Two fields look more informative than they are:

- **`created` is not a release date.** All 37 models carry an identical
  timestamp, and it changed between two calls minutes apart. It is
  generated at serialization time. Do not surface it as model age; it
  would be a confident lie.
- **`owned_by`** is genuine and correct (`openai` / `anthropic` /
  `google`), but it is vendor, not capability -- see F4 for the twist.

### F3. Upstream carries a human display name; argo-proxy discards it

The one piece of presentational information the gateway *does* supply is
the display name in its `id` field: `"Claude Sonnet 4.6"`,
`"GPT-5.6 Sol"`, `"Text Embedding 3 Large"`.

argo-proxy's `produce_argo_model_list`
(`argoproxy/models/upstream.py:57-99`) lowercases and hyphenates it into
an `argo:`-prefixed alias and keeps only the alias-to-`internal_id`
mapping. The pretty form never reaches our `/v1/models`. It is *nearly*
recoverable by title-casing the alias, but not exactly -- `"GPT-5.6
Sol"` does not round-trip from `argo:gpt-5.6-sol`.

This is small, but it is the only descriptive text that exists anywhere
in the chain, and today it is thrown away.

### F4. `owned_by` on our `/v1/models` is inference too, not passthrough

Worth stating precisely, because it changes how much option 1 below is
worth. argo-proxy does not forward the upstream `owned_by`. It
constructs each response record as `OpenAIModel(id=..., internal_name=...)`
(`argoproxy/models/registry.py:290-296`), leaving `owned_by` at its
default `"argo"`, and the constructor then overwrites it with
`classify_model_family(internal_name)`
(`registry.py:41-46`; classifier at `models/constants.py:137-153`).

So both argo-proxy's `owned_by` and our `provider` column are locally
derived. They agree with upstream on all 37 models today. The
difference that matters: argo-proxy classifies on `internal_name`
(`claudesonnet46`, `gemini25pro`) against a maintained pattern set,
whereas we regex the `argo:` alias
(`argo-anywhere.sh:9825-9831`) with a hand-rolled five-branch `if`. Ours
is the more fragile of two guesses, not a guess versus a fact.

### F5. Our proxy shows 51 rows for 37 models

`http://localhost:<port>/v1/models` returned 51 entries: 27 `openai`,
20 `anthropic`, 4 `google`. The inflation is alias expansion in
`produce_argo_model_list` -- `o3-mini` yields both `argo:gpt-o3-mini`
and `argo:o3-mini`; every Claude yields both `argo:claude-4.6-sonnet`
and `argo:claude-sonnet-4.6`. Our `list-models` already collapses these
with `unique_by(.internal_name)`, which is why the printed table is
shorter than the raw feed. Any metadata table must therefore be keyed on
`internal_name`, not on `id`.

### F6. The web UI's categorization is not API-sourced

`argo.anl.gov` sits behind OIDC (`301` to `login.anl.gov` for every
path, including `/openapi.json`), so its own API was not reachable
without a browser session. But since the gateway underneath it exposes
no descriptive metadata at all (F1, F2), whatever grouping the chat UI
displays is its own static configuration. It is not something we can
query.

## Options

Three, in increasing cost. They are independent; 1 is worth doing
whether or not 2 ever happens.

### Option 1 -- classify on `owned_by`, not on our own regex

Replace the `provider_of` regex in `mode_list_models`
(`argo-anywhere.sh:9825-9831`) with a read of `.owned_by`, keeping a
regex only for the `embedding` bucket (argo-proxy files embeddings under
`openai`, which is true but unhelpful in a picker).

- **Cost**: ~5 engine lines plus a test.
- **Value**: removes one of our guesses in favour of upstream's
  better-maintained one, and stops us mislabelling a future family the
  five-branch `if` has never seen (today everything unrecognised falls
  to `other`).
- **Does not** answer the user's question. It is hygiene.

### Option 2 -- ship a curated metadata table in argo-anywhere

A table keyed on `internal_name` -- family, tier, rough cost band, a
one-line "good at" -- rendered as extra `list-models` columns and in the
web-UI model panel. This is the only option that delivers what was
asked.

Four constraints if it is built:

1. **Key on `internal_name`** (F5), and treat an absent key as *no
   annotation*, never as a default. Blank beats wrong: a user who reads
   "modest token cost" beside a model that is not, and bills a project
   accordingly, is worse off than one who reads nothing. Same
   fail-closed discipline as the identity invariants -- state only what
   is established.
2. **It is editorial content we own and must maintain.** ANL moves:
   `claudeopus5`, `claudesonnet5` and three `GPT-5.6 *` variants are
   live on the gateway today and absent from argo-proxy's own
   `_DEFAULT_CHAT_MODELS`. Every gateway addition is a row we owe.
   Staleness here is not inert -- an outdated cost claim is an
   authoritative-looking wrong answer.
3. **Cost bands must be relative and unitless** ("low / mid / high"),
   not dollar figures. We have no pricing feed, ANL's internal
   accounting is not published on this API, and a number implies a
   precision we cannot back.
4. **Fold in F3** -- carry the display name in the same table, since we
   are hand-maintaining rows anyway and the gateway's own spelling is
   the right source for it.

Open question: does this belong in argo-anywhere at all, or is it a
`docs/` page? A static table in the engine has to ship a release to gain
a row. A doc page is cheaper to correct but is not in front of the user
at the moment of choosing. Leaning engine table *and* doc page generated
from it, but this is not decided.

### Option 3 -- ask ANL to serve the metadata

The only route to authoritative, self-maintaining data. Note it needs
**two** changes, not one:

1. the gateway adds fields to `/argoapi/api/v1/models/`; and
2. argo-proxy stops dropping them -- `OpenAIModel`
   (`argoproxy/models/registry.py:32-46`) reconstructs a fixed
   five-field record from `id` + `internal_name` and discards everything
   else, so new upstream fields would be invisible to every client
   behind the proxy even after ANL shipped them.

Worth raising with both projects regardless of whether we build option
2, because option 2's maintenance burden is exactly what option 3
retires.

## Recommendation

Option 1 whenever the engine is next open; it is nearly free. Option 2
only on a real second request -- one user asking establishes the need
exists, not that a permanently-maintained editorial table is the right
shape for it. Option 3 as a message to ANL / argo-proxy, cheap to send
and the only durable fix.

## Risks

- **Curated data going stale silently** (option 2). Mitigation: a test
  that fails when the live feed serves an `internal_name` the table does
  not cover, so the gap surfaces in CI rather than in a user's terminal.
  This mirrors the aider `STALE-COVERAGE INVARIANT` floor already in the
  engine.
- **Two more coupled surfaces.** Any new `list-models` column has to
  land in the engine, in `/api/models`
  (`src/argo_anywhere/web/app.py:483-502`) and in `_renderModelRow`
  (`src/argo_anywhere/web/static/index.html:1352-1380`) in the same
  commit, per the AGENTS.md engine-web coupling rules.

## Action items

1. Reply to the user: no such endpoint exists; the gateway serves five
   fields; the chat UI's grouping is its own -- **done** (2026-08-14).
2. Option 1: switch `provider_of` to `.owned_by` -- pending, unscheduled.
3. Option 3: raise with argo-proxy upstream (the passthrough half) and
   with ANL (the source half) -- pending, unscheduled.
4. Re-check `openapi.json` on the next upstream audit; if descriptive
   fields ever appear, this note's conclusion flips -- pending. Add as a
   WATCH row when the next `docs/AUDIT_*_argo-proxy-upstream.md` is
   written.

---

*Created 2026-08-14 by Ahmed Attia (with substantial AI assistance from
Claude per [`CONTRIBUTORS.md`](../CONTRIBUTORS.md)). Findings F1-F6 are
live observations against the ANL gateway on 2026-08-14 (argo-proxy
3.2.3, llm-rosetta 0.7.1, 37 upstream models / 51 proxy aliases); re-run
the probes before trusting them after any gateway change.*
