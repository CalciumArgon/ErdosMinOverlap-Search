"""OpenAI-compatible chat-completions backend with streaming and API-health classification.

Used for reasoning models behind OpenAI-compatible gateways, e.g. qwen3.8-max
on apicz.boyuerichdata.com (``--llm-backend openai_stream``). It is the
counterpart of ``anthropic_client.AnthropicStreamClient``:

- Always streams (``stream: true`` + ``stream_options.include_usage``); the
  gateway sends ``reasoning_content`` deltas during thinking (first event ~1 s,
  gaps ~1 s measured), so a slow-but-alive call is told apart from a dead one.
  The old litellm path was one synchronous call and could only time out.
- Depth is ``reasoning_effort`` (gateway accepts none|minimal|low|medium|high|
  xhigh|max); extra gateway knobs (e.g. ``thinking_budget``) come from
  ``SIMPLETES_EXTRA_BODY`` (JSON) as before.
- Every call is classified (``simpletes.llm.health``) and recorded. Failures
  raise ``LLMCallError`` with ``health_class`` set, so the engine refunds and
  retries API-class failures instead of burning budget on them.

Runs in-process on the event loop with httpx (already a dependency).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from typing import Any

import httpx

from simpletes.llm import health
from simpletes.llm.types import LLMCallError, LLMResult

_DEFAULT_FIRST_EVENT_TIMEOUT = 600.0
_DEFAULT_STALL_TIMEOUT = 1200.0


def _strip_provider_prefix(model: str) -> str:
    # Accept litellm-style "openai/qwen3.8-max" names as well.
    return model.split("/", 1)[1] if model.startswith("openai/") else model


def _extra_body() -> dict[str, Any]:
    raw = os.environ.get("SIMPLETES_EXTRA_BODY")
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


class OpenAIStreamClient:
    """Streaming chat-completions client exposing the generator's LLMBackend interface."""

    def __init__(
        self,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float | None = None,
        effort: str | None = None,
        temperature: float | None = None,
        first_event_timeout: float | None = None,
        stall_timeout: float | None = None,
    ) -> None:
        self.model = _strip_provider_prefix(model)
        self.max_tokens = int(max_tokens)
        self.api_base = (api_base or os.environ.get("OPENAI_API_BASE") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        self.timeout = float(timeout) if timeout else 3600.0
        self.effort = effort
        self.temperature = temperature
        self.first_event_timeout = float(first_event_timeout or _DEFAULT_FIRST_EVENT_TIMEOUT)
        self.stall_timeout = float(stall_timeout or _DEFAULT_STALL_TIMEOUT)

    # ------------------------------------------------------------------
    # Core streaming call
    # ------------------------------------------------------------------

    def _request_body(
        self, prompt: str, max_tokens: int, effort: str | None, extra_override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if effort:
            body["reasoning_effort"] = effort
        # extra_override replaces SIMPLETES_EXTRA_BODY (reflection must not
        # inherit the deep generation budget); explicit fields above win.
        extra = _extra_body() if extra_override is None else dict(extra_override)
        for k, v in extra.items():
            body.setdefault(k, v)
        # qwen gateway: "'reasoning_effort' and 'thinking_budget' cannot be set
        # simultaneously" (HTTP 400). An explicit thinking_budget is the more
        # specific knob, so it wins.
        if "thinking_budget" in body:
            body.pop("reasoning_effort", None)
        return body

    async def stream_text(
        self,
        prompt: str,
        *,
        kind: str = "generation",
        max_tokens: int | None = None,
        effort: str | None = None,
        timeout: float | None = None,
        first_event_timeout: float | None = None,
        stall_timeout: float | None = None,
        extra_override: dict[str, Any] | None = None,
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
        """Run one streamed call. Returns (text, raw_output, usage, health).

        Raises LLMCallError (with ``health_class``) for every non-ok class.
        """
        total = float(timeout or self.timeout)
        first_limit = float(first_event_timeout or self.first_event_timeout)
        gap_limit = float(stall_timeout or self.stall_timeout)
        body = self._request_body(
            prompt, int(max_tokens or self.max_tokens),
            effort if effort is not None else self.effort, extra_override,
        )

        t0 = time.monotonic()
        deadline = t0 + total
        first_event_s: float | None = None
        last_event = t0
        max_gap = 0.0
        n_events = 0
        thinking_parts: list[str] = []
        text_parts: list[str] = []
        stop_reason: str | None = None
        usage: dict[str, Any] = {}
        h: dict[str, Any] = {"model": self.model, "effort": body.get("reasoning_effort"),
                             "thinking_budget": body.get("thinking_budget")}

        def _finish(cls: str, **extra: Any) -> dict[str, Any]:
            now = time.monotonic()
            h.update({
                "class": cls,
                "elapsed_s": round(now - t0, 1),
                "first_event_s": None if first_event_s is None else round(first_event_s, 1),
                "max_gap_s": round(max(max_gap, now - last_event if first_event_s is not None else 0.0), 1),
                "n_events": n_events,
                "thinking_chars": sum(len(p) for p in thinking_parts),
                "text_chars": sum(len(p) for p in text_parts),
                "stop_reason": stop_reason,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "reasoning_tokens": usage.get("reasoning_tokens"),
                **extra,
            })
            return h

        def _fail(cls: str, exc: BaseException | None, msg: str) -> LLMCallError:
            etype = type(exc).__name__ if exc is not None else cls
            emsg = (str(exc) if exc is not None else msg)[:2000]
            health.record(kind, _finish(cls, error_type=etype, error_message=emsg))
            err = LLMCallError(
                model=self.model, api_base=self.api_base, error_type=etype,
                message=f"[{cls}] {emsg}",
                traceback_str=traceback.format_exc() if exc is not None else "",
            )
            err.health_class = cls  # type: ignore[attr-defined]
            err.health = dict(h)  # type: ignore[attr-defined]
            return err

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.api_base}/chat/completions"
        client = httpx.AsyncClient(timeout=httpx.Timeout(total + 60.0, connect=min(first_limit, 60.0)))
        resp: httpx.Response | None = None
        saw_done = False
        try:
            # 1) open the stream (HTTP response headers)
            try:
                resp = await asyncio.wait_for(
                    client.send(client.build_request("POST", url, headers=headers, json=body), stream=True),
                    timeout=min(first_limit, total),
                )
            except asyncio.TimeoutError as exc:
                raise _fail("api_no_start", exc, f"no response within {min(first_limit, total):.0f}s") from None
            except Exception as exc:  # connection / DNS / TLS
                raise _fail("api_no_start", exc, "") from None
            if resp.status_code != 200:
                detail = (await resp.aread())[:2000].decode("utf-8", "replace")
                raise _fail("api_no_start", None, f"HTTP {resp.status_code}: {detail}")

            # 2) consume SSE lines with first-event, stall and total deadlines
            it = resp.aiter_lines().__aiter__()
            while True:
                now = time.monotonic()
                remaining = deadline - now
                if remaining <= 0:
                    raise _fail("timeout_mid_generation", None,
                                f"total timeout {total:.0f}s reached while events were still arriving")
                if first_event_s is None:
                    limit = min(first_limit - (now - t0), remaining)
                else:
                    limit = min(gap_limit - (now - last_event), remaining)
                try:
                    line = await asyncio.wait_for(it.__anext__(), timeout=max(limit, 0.001))
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    if first_event_s is None:
                        raise _fail("api_no_start", None,
                                    f"no stream event within {first_limit:.0f}s") from None
                    if time.monotonic() >= deadline - 0.5:
                        raise _fail("timeout_mid_generation", None,
                                    f"total timeout {total:.0f}s reached while events were still arriving") from None
                    raise _fail("api_stalled", None,
                                f"no stream event for {gap_limit:.0f}s after {n_events} events") from None

                # SSE comments (": keep-alive") and blank lines do not prove the
                # model is producing anything; only data lines count as events.
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                now = time.monotonic()
                if first_event_s is None:
                    first_event_s = now - t0
                else:
                    max_gap = max(max_gap, now - last_event)
                last_event = now
                n_events += 1
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if isinstance(chunk, dict) and chunk.get("error"):
                    cls = "api_stalled" if n_events > 1 else "api_no_start"
                    raise _fail(cls, None, f"stream error event: {str(chunk['error'])[:1500]}")
                u = chunk.get("usage") if isinstance(chunk, dict) else None
                if u:
                    usage["input_tokens"] = u.get("prompt_tokens")
                    usage["output_tokens"] = u.get("completion_tokens")
                    det = u.get("completion_tokens_details") or {}
                    usage["reasoning_tokens"] = det.get("reasoning_tokens")
                for ch in (chunk.get("choices") or []) if isinstance(chunk, dict) else []:
                    delta = ch.get("delta") or {}
                    rc = delta.get("reasoning_content") or delta.get("reasoning")
                    if rc:
                        thinking_parts.append(rc)
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                    if ch.get("finish_reason"):
                        stop_reason = str(ch["finish_reason"])
        except LLMCallError:
            raise
        except Exception as exc:  # transport error mid-stream
            cls = "api_stalled" if first_event_s is not None else "api_no_start"
            raise _fail(cls, exc, "") from None
        finally:
            if resp is not None:
                try:
                    await resp.aclose()
                except Exception:
                    pass
            try:
                await client.aclose()
            except Exception:
                pass

        text = "".join(text_parts)
        thinking = "".join(thinking_parts)
        if stop_reason is None and not saw_done:
            # The connection closed without a finish_reason or [DONE]: the
            # gateway ended the stream itself, not the model.
            raise _fail("api_stream_cut", None,
                        f"stream closed without finish_reason after {n_events} events, text_chars={len(text)}")
        if (stop_reason or "").lower() == "content_filter":
            cls = "refusal"
        else:
            cls = health.classify_finish(
                stop_reason, text,
                output_tokens=usage.get("output_tokens"),
                requested_max_tokens=body.get("max_tokens"),
            )
        raw_output = (f"<reasoning>\n{thinking}\n</reasoning>\n" if thinking else "") + text
        usage_out = {k: v for k, v in usage.items() if v is not None} or None
        if cls == "ok":
            health.record(kind, _finish(cls))
            return text, raw_output, usage_out, dict(h)
        raise _fail(cls, None, f"finish_reason={stop_reason!r}, text_chars={len(text)}")

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    async def generate(self, prompt: str, instance_id: str = "", track_io: bool = False) -> LLMResult:
        text, raw_output, usage, _h = await self.stream_text(prompt, kind="generation")
        return LLMResult(
            text=text,
            prompt=prompt if track_io else None,
            raw_output=raw_output if track_io else None,
            token_usage=usage if track_io else None,
        )

    async def generate_batch(
        self, prompt: str, n: int, instance_id: str = "", track_io: bool = False,
    ) -> list[LLMResult]:
        if n <= 1:
            return [await self.generate(prompt, instance_id, track_io)]
        # The engine dispatches k=1 tasks (stream_k_candidates); this path is
        # only a fallback. Any failure fails the batch, like the litellm client.
        return list(await asyncio.gather(*(self.generate(prompt, instance_id, track_io) for _ in range(n))))

    async def probe(self, *, timeout: float = 120.0) -> dict[str, Any]:
        """Cheap liveness probe (no deep thinking budget). Returns the health dict; never raises."""
        try:
            _t, _r, _u, h = await self.stream_text(
                "Reply with the single word: pong", kind="probe", max_tokens=512,
                effort="low", timeout=timeout, first_event_timeout=timeout, stall_timeout=timeout,
                extra_override={},
            )
            return h
        except LLMCallError as e:
            h = dict(getattr(e, "health", {}) or {})
            # A probe that got any answer proves the API is up.
            if getattr(e, "health_class", "") in {"truncated_length", "empty_content"}:
                h["class"] = "ok"
            return h

    def preflight(self, *, timeout: float = 120.0) -> None:
        """Synchronous preflight for main.py: raise LLMCallError if the API is down."""
        h = asyncio.run(self.probe(timeout=timeout))
        if h.get("class") != "ok":
            err = LLMCallError(
                model=self.model, api_base=self.api_base,
                error_type=str(h.get("error_type") or h.get("class")),
                message=str(h.get("error_message") or h),
            )
            err.health_class = h.get("class")  # type: ignore[attr-defined]
            raise err

    def close(self) -> None:
        return None
