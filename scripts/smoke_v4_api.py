#!/usr/bin/env python
"""v4 API calibration for the Anthropic-backend gateway (run on qz, never locally).

Reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL from the environment; never prints
the key. Each step prints one SMOKE line; health rows go to $SMOKE_DIR/api_health.jsonl.

Steps (select with argv, default: all except deep):
  ping      low-effort probe through AnthropicStreamClient (classifies ok)
  badkey    wrong key -> must classify api_no_start
  shorttime xhigh call with timeout=45 s -> must classify timeout_mid_generation
            (thinking deltas keep arriving) — verifies the "slow, not broken" class
  conc N    N parallel low-effort calls (default 8): concurrency / rate limits
  deep      one real-depth call (effort xhigh, max_tokens 128000) on the actual
            task instruction: first_event_s, max_gap_s, thinking/text chars,
            elapsed, output tokens -> calibrates --timeout / --stall-timeout
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from simpletes.llm import health  # noqa: E402
from simpletes.llm.anthropic_client import AnthropicStreamClient  # noqa: E402
from simpletes.llm.types import LLMCallError  # noqa: E402

MODEL = os.environ.get("SMOKE_MODEL", "claude-opus-5-5")
BASE = os.environ.get("ANTHROPIC_BASE_URL")
SMOKE_DIR = os.environ.get("SMOKE_DIR", "/tmp/smoke_v4")
health.install_recorder(os.path.join(SMOKE_DIR, "api_health.jsonl"))


def client(**kw) -> AnthropicStreamClient:
    args = dict(model=MODEL, max_tokens=128000, api_base=BASE, timeout=10800,
                effort="xhigh", first_event_timeout=600, stall_timeout=1200)
    args.update(kw)
    return AnthropicStreamClient(**args)


def show(step: str, h: dict, expect: str | None = None) -> bool:
    cls = h.get("class")
    ok = expect is None or cls == expect
    keys = ("elapsed_s", "first_event_s", "max_gap_s", "n_events", "thinking_chars",
            "text_chars", "stop_reason", "input_tokens", "output_tokens", "error_type")
    detail = " ".join(f"{k}={h.get(k)}" for k in keys if h.get(k) is not None)
    msg = str(h.get("error_message") or "")[:200].replace("\n", " ")
    print(f"SMOKE {step}: class={cls} {'PASS' if ok else 'FAIL (expected ' + str(expect) + ')'} {detail}"
          + (f" msg={msg!r}" if msg and not ok else ""), flush=True)
    return ok


async def call(c: AnthropicStreamClient, prompt: str, **kw) -> dict:
    try:
        _t, _r, _u, h = await c.stream_text(prompt, kind="smoke", **kw)
        return h
    except LLMCallError as e:
        return dict(getattr(e, "health", {}) or {"class": getattr(e, "health_class", "error")})


async def main(steps: list[str]) -> int:
    ok = True
    if "ping" in steps:
        h = await client().probe(timeout=300)
        ok &= show("ping", h, "ok")
    if "badkey" in steps:
        h = await client(api_key="sk-invalid-smoke-test").probe(timeout=120)
        ok &= show("badkey", h, "api_no_start")
    if "shorttime" in steps:
        h = await call(client(), "Prove carefully that there are infinitely many primes of the form 4k+3, "
                       "then discuss three different proofs in depth.",
                       effort="xhigh", timeout=45, first_event_timeout=40, stall_timeout=40)
        # If the gateway does not stream thinking deltas the class is api_stalled /
        # api_no_start instead: that means the liveness assumption is wrong.
        ok &= show("shorttime", h, "timeout_mid_generation")
    if "conc" in steps:
        n = int(steps[steps.index("conc") + 1]) if len(steps) > steps.index("conc") + 1 and steps[steps.index("conc") + 1].isdigit() else 8
        c = client()
        t0 = time.monotonic()
        hs = await asyncio.gather(*(call(c, f"Reply with the number {i} and nothing else.",
                                         effort="low", max_tokens=1024, timeout=600) for i in range(n)))
        classes = [h.get("class") for h in hs]
        n_ok = sum(1 for x in classes if x in {"ok", "truncated_length"})
        print(f"SMOKE conc{n}: ok={n_ok}/{n} classes={classes} wall={time.monotonic() - t0:.1f}s", flush=True)
        ok &= n_ok == n
    if "deep" in steps:
        instr = open(os.path.join(REPO_ROOT, "datasets/erdos/erdos_min_overlap/erdos_min_overlap.txt"),
                     encoding="utf-8").read()
        prompt = (f"Task: {instr}\n\nWrite construct_h() returning (h_values, n_points) for this task "
                  "as one python code block. Think as deeply as needed.")
        h = await call(client(), prompt)
        ok &= show("deep", h, "ok")
        out = h.get("output_tokens") or 0
        el = h.get("elapsed_s") or 0
        if out and el:
            print(f"SMOKE deep throughput: {out / el:.1f} output tok/s", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    steps = sys.argv[1:] or ["ping", "badkey", "shorttime", "conc", "8"]
    sys.exit(asyncio.run(main(steps)))
