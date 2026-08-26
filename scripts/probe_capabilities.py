"""Measure what the Argo gateway actually supports, per model and per API path.

Maintainers only. Answers, by measurement rather than by reading upstream
source, the question that keeps going stale in our docs: *which models accept
which extended-thinking request shape, and does thinking actually come back?*

Why this exists
---------------
Every hardcoded capability list this project has owned has drifted --
``_opencode_models_hardcoded`` still names Opus 4.7 as current; the aider
temperature floor missed five live models until 2026-08-12; the upstream shim's
own ``reasoning.model_overrides`` is three Opus generations behind. Opus
4.7 -> 4.8 -> 5 is one finding learned three times. A generated matrix answers
drift structurally; a hand-edited table just moves the staleness.

See ``notes/impl_thinking_support.md`` for the findings this automates and
``docs/LIMITATIONS.md`` "Extended thinking" for the user-facing summary.

What it does
------------
For each Anthropic model the proxy serves, it sends small probes:

* ``/v1/messages`` with ``thinking.type: enabled`` and with ``adaptive``
  -- the native path Claude Code uses. ``adaptive`` is the only value every
  current model accepts; ``enabled`` fails *silently* on the v5 models
  (HTTP 200, zero bytes), which is exactly why this needs measuring.
* ``/v1/chat/completions`` with ``reasoning.mode`` -- the OpenAI-compatible
  path aider and OpenCode use, which takes a different vocabulary and (as of
  2026-08-25) returns empty ``reasoning_content`` for every value.

Nothing here writes configuration or touches a config file. It reads.

Usage
-----
Needs a live channel (``argo-anywhere connect``). It talks to localhost; the
tunnel carries it to the node.

    python scripts/probe_capabilities.py                  # anthropic models, both paths
    python scripts/probe_capabilities.py --format json    # machine-readable
    python scripts/probe_capabilities.py --model claude-opus-5 --model claude-sonnet-5
    python scripts/probe_capabilities.py --all-providers  # include openai/google
    python scripts/probe_capabilities.py --port 64743     # override port discovery

**This spends gateway quota** -- two to four completions per model. It is
opt-in, never on the ``connect`` path, and deliberately not wired into the
engine. Probes run sequentially with a small delay; use ``--model`` while
iterating.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Mirrors the engine's STATE_DIR (argo-anywhere.sh) / status.STATE_DIR.
STATE_DIR = Path(os.path.expanduser("~/.config/argo_anywhere"))

#: A prompt that should induce visible reasoning on a thinking-capable model.
#: Deliberately a small logic puzzle: enough to trigger thinking, short enough
#: not to burn tokens. Used on BOTH paths -- a trivial prompt ("say ok") does
#: not induce thinking even where thinking works, so probing with one would
#: report a false negative for every model.
_REASON = "A rope burns unevenly in exactly 60 minutes. Using two such ropes, measure exactly 45 minutes."


def _read_cached_port() -> int | None:
    """The port cache is the source of truth for transport state (D-020)."""
    try:
        return int((STATE_DIR / "port").read_text().strip())
    except (OSError, ValueError):
        return None


def _post(url: str, payload: dict, user: str, timeout: float) -> tuple[int, bytes, str | None]:
    """POST JSON to a loopback URL. Returns (status, body, error). Never raises.

    A zero-byte 200 is a real, meaningful result here (it is how the gateway
    rejects an unsupported thinking shape on a streaming request), so the
    caller gets the raw body rather than anything normalised.
    """
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {user}")
    req.add_header("anthropic-version", "2023-06-01")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (loopback only)
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, b"", str(exc)


def _get_json(url: str, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (loopback only)
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


@dataclass
class ModelResult:
    """One row of the capability matrix."""

    internal_name: str
    ids: list[str] = field(default_factory=list)
    provider: str = "?"
    #: thinking.type value -> outcome on /v1/messages
    native: dict[str, str] = field(default_factory=dict)
    #: reasoning.mode value -> outcome on /v1/chat/completions
    openai: dict[str, str] = field(default_factory=dict)
    #: True if we saw an actual thinking/reasoning payload, not just a 200.
    thinking_observed: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _classify_native(status: int, body: bytes, err: str | None) -> tuple[str, bool]:
    """Map a /v1/messages streaming response to an outcome label.

    The important case is ``(200, b"")``: the gateway accepted the request,
    returned success, and sent nothing. That is how an unsupported
    ``thinking.type`` presents on the v5 models -- no error event, no body --
    and reading it as success is the mistake this script exists to prevent.
    """
    if err:
        return f"error ({err[:40]})", False
    if status == 200 and not body.strip():
        return "SILENT FAIL (200, 0 bytes)", False
    if status != 200:
        return f"HTTP {status}", False
    text = body.decode("utf-8", "replace")
    if '"type": "error"' in text or '"type":"error"' in text:
        return "error event", False
    saw_thinking = "thinking_delta" in text or '"thinking"' in text
    return ("ok (+thinking)" if saw_thinking else "ok (no thinking)"), saw_thinking


def _classify_openai(status: int, body: bytes, err: str | None) -> tuple[str, bool]:
    """Map a /v1/chat/completions response to an outcome label.

    ``reasoning_content`` present-but-empty is distinct from absent, and both
    are distinct from populated. Only the third means thinking is reachable.
    """
    if err:
        return f"error ({err[:40]})", False
    if status != 200:
        detail = ""
        try:
            j = json.loads(body)
            msg = (j.get("error") or {}).get("message") or j.get("message") or ""
            if "reasoning.mode" in msg:
                detail = " (rejected value)"
            elif "Failed to parse upstream" in msg:
                detail = " (upstream parse)"
        except (ValueError, AttributeError):
            pass
        return f"HTTP {status}{detail}", False
    try:
        msg = json.loads(body)["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        return "unparseable 200", False
    rc = msg.get("reasoning_content")
    if rc is None:
        return "ok (field absent)", False
    if not rc:
        return "ok (empty reasoning)", False
    return f"ok (+reasoning {len(rc)}c)", True


def probe_model(
    base: str,
    user: str,
    internal: str,
    probe_id: str,
    *,
    timeout: float,
    delay: float,
    paths: set[str],
) -> ModelResult:
    res = ModelResult(internal_name=internal)

    if "native" in paths:
        for shape in ("enabled", "adaptive"):
            thinking = {"type": shape}
            if shape == "enabled":
                thinking["budget_tokens"] = 1024
            # The reasoning prompt, not the ping: a trivial prompt does not
            # induce thinking even on a model that supports it, so probing
            # with one would report "no thinking" for every model and the
            # thinking_observed column would be meaningless. Both outcomes we
            # care about -- the silent 200/0-byte failure and a real
            # thinking_delta -- are still visible with the longer prompt.
            status, body, err = _post(
                f"{base}/v1/messages",
                {
                    "model": probe_id,
                    "max_tokens": 4096,
                    "stream": True,
                    "thinking": thinking,
                    "output_config": {"effort": "high"},
                    "messages": [{"role": "user", "content": _REASON}],
                },
                user,
                timeout,
            )
            label, saw = _classify_native(status, body, err)
            res.native[shape] = label
            res.thinking_observed |= saw
            time.sleep(delay)

    if "openai" in paths:
        # `adaptive` is deliberately absent: this path rejects it outright
        # ("Expected one of ('auto','enabled','disabled')"). Sending it would
        # burn a request to re-learn a known fact.
        for mode in ("enabled",):
            status, body, err = _post(
                f"{base}/v1/chat/completions",
                {
                    "model": f"argo:{probe_id}",
                    "max_tokens": 2048,
                    "reasoning": {"mode": mode, "effort": "high"},
                    "messages": [{"role": "user", "content": _REASON}],
                },
                user,
                timeout,
            )
            label, saw = _classify_openai(status, body, err)
            res.openai[mode] = label
            res.thinking_observed |= saw
            time.sleep(delay)

    return res


def _provider_of(name: str) -> str:
    low = name.lower()
    if "embedding" in low:
        return "embedding"
    for needle, prov in (("claude", "anthropic"), ("sonnet", "anthropic"), ("opus", "anthropic"),
                         ("haiku", "anthropic"), ("gemini", "google")):
        if needle in low:
            return prov
    return "openai"


def collect_models(base: str, timeout: float) -> dict[str, dict]:
    """Group the proxy's /v1/models by internal_name (ids alias many-to-one)."""
    doc = _get_json(f"{base}/v1/models", timeout)
    if not doc:
        return {}
    grouped: dict[str, dict] = {}
    for m in doc.get("data", []):
        internal = m.get("internal_name") or m.get("id", "")
        raw_id = m.get("id", "")
        if "embedding" in raw_id.lower():
            continue
        slot = grouped.setdefault(internal, {"ids": [], "provider": _provider_of(internal or raw_id)})
        slot["ids"].append(raw_id[len("argo:"):] if raw_id.startswith("argo:") else raw_id)
    return grouped


def render_text(results: list[ModelResult], paths: set[str]) -> str:
    if not results:
        return "No models probed.\n"
    w = max(len(r.internal_name) for r in results) + 2
    out: list[str] = []
    head = f"{'MODEL':<{w}}"
    if "native" in paths:
        head += f"{'messages:enabled':<30}{'messages:adaptive':<30}"
    if "openai" in paths:
        head += f"{'chat:reasoning.mode':<28}"
    out.append(head.rstrip())
    out.append("-" * len(head.rstrip()))
    for r in results:
        line = f"{r.internal_name:<{w}}"
        if "native" in paths:
            line += f"{r.native.get('enabled', '-'):<30}{r.native.get('adaptive', '-'):<30}"
        if "openai" in paths:
            line += f"{r.openai.get('enabled', '-'):<28}"
        out.append(line.rstrip())

    out.append("")
    reachable = [r.internal_name for r in results if r.thinking_observed]
    out.append(f"Thinking observed on {len(reachable)}/{len(results)} model(s).")

    # A silent failure is per-shape, not per-model: 4.1/4.5 break on
    # `adaptive` while 5.x breaks on `enabled`. Report which shape, or the
    # summary reproduces the "one rule for all models" error that made the
    # hand-written tables wrong.
    for shape in ("enabled", "adaptive"):
        bad = [r.internal_name for r in results if "SILENT FAIL" in r.native.get(shape, "")]
        if not bad:
            continue
        other = "adaptive" if shape == "enabled" else "enabled"
        out.append("")
        out.append(f"thinking.type={shape} fails SILENTLY (200, zero bytes) on:")
        for n in bad:
            out.append(f"  - {n}")
        out.append(f"  These need thinking.type={other}. A client sending the wrong shape")
        out.append("  gets an empty response with no error at all.")

    answered_never_thought = [
        r.internal_name
        for r in results
        if not r.thinking_observed and all("ok" in v for v in r.native.values())
    ]
    if answered_never_thought:
        out.append("")
        out.append("Answered on every shape but never emitted a thinking block:")
        for n in answered_never_thought:
            out.append(f"  - {n}")
        out.append("  Not a transport failure -- the model replies fine. Either it has no")
        out.append("  extended thinking, or the prompt did not trigger it. Worth a manual")
        out.append("  look before claiming support either way.")

    out.append("")
    out.append('See docs/LIMITATIONS.md "Extended thinking" for the user-facing summary')
    out.append("and notes/impl_thinking_support.md for why we write no thinking config.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure per-model extended-thinking support through a live channel.",
        epilog="Requires an up channel (argo-anywhere connect). Spends gateway quota.",
    )
    ap.add_argument("--port", type=int, default=None, help="proxy port (default: the port cache)")
    ap.add_argument("--user", default=None, help="ANL username / bearer token (default: the user cache)")
    ap.add_argument("--model", action="append", default=[], metavar="ID",
                    help="probe only this model (repeatable; matches id or internal_name)")
    ap.add_argument("--all-providers", action="store_true",
                    help="probe every provider, not just Anthropic")
    ap.add_argument("--path", choices=("native", "openai", "both"), default="both",
                    help="which API path(s) to probe (default: both)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--timeout", type=float, default=90.0, help="per-request timeout, seconds")
    ap.add_argument("--delay", type=float, default=0.5, help="pause between requests, seconds")
    args = ap.parse_args(argv)

    port = args.port or _read_cached_port()
    if not port:
        print("No port: pass --port, or connect once so the cache is written.", file=sys.stderr)
        return 2
    user = args.user or os.environ.get("ARGO_ANYWHERE_USER")
    if not user:
        try:
            user = (STATE_DIR / "user").read_text().strip()
        except OSError:
            user = ""
    if not user:
        print("No username: pass --user or set ARGO_ANYWHERE_USER.", file=sys.stderr)
        return 2

    base = f"http://127.0.0.1:{port}"
    if not _get_json(f"{base}/health", 5.0):
        print(f"No channel on :{port}. Run `argo-anywhere connect` first.", file=sys.stderr)
        return 1

    grouped = collect_models(base, 15.0)
    if not grouped:
        print(f"Could not read {base}/v1/models.", file=sys.stderr)
        return 1

    wanted = {m.lower() for m in args.model}
    targets: list[tuple[str, str]] = []
    for internal, meta in sorted(grouped.items()):
        if not args.all_providers and meta["provider"] != "anthropic":
            continue
        if wanted and not (
            internal.lower() in wanted or any(i.lower() in wanted for i in meta["ids"])
        ):
            continue
        targets.append((internal, meta["ids"][0]))

    if not targets:
        print("No models matched.", file=sys.stderr)
        return 1

    paths = {"native", "openai"} if args.path == "both" else {args.path}
    n_req = len(targets) * ((2 if "native" in paths else 0) + (1 if "openai" in paths else 0))
    print(f"Probing {len(targets)} model(s) on :{port} (~{n_req} requests)...", file=sys.stderr)

    results: list[ModelResult] = []
    for internal, probe_id in targets:
        print(f"  {internal} ...", end="", flush=True, file=sys.stderr)
        r = probe_model(base, user, internal, probe_id,
                        timeout=args.timeout, delay=args.delay, paths=paths)
        r.ids = grouped[internal]["ids"]
        r.provider = grouped[internal]["provider"]
        results.append(r)
        print(" done", file=sys.stderr)

    if args.format == "json":
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        print(render_text(results, paths), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
