"""Anthropic Messages API backend with streaming and API-health classification.

Used for Claude models (``--llm-backend anthropic``). Differences from the
LiteLLM backend:

- Always streams (``messages.create(stream=True)``): large ``max_tokens``
  requires it, and stream events are how a slow-but-alive call is told
  apart from a dead one.
- Sends no sampling parameters (temperature / top_p / top_k are rejected by
  current Claude models). Depth is controlled with ``output_config.effort``;
  thinking is adaptive, with ``display: "summarized"`` so that thinking
  deltas arrive during the thinking phase (liveness signal).
- Every call is classified (see ``simpletes.llm.health``) and recorded.
  Failures raise ``LLMCallError`` with ``health_class`` set, so the engine can
  refund and retry API-class failures instead of burning budget on them.

The client runs in-process on the event loop: streaming is I/O bound, so no
process pool is needed.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from typing import Any

from simpletes.llm import health
from simpletes.llm.types import LLMCallError, LLMResult

_DEFAULT_FIRST_EVENT_TIMEOUT = 600.0
_DEFAULT_STALL_TIMEOUT = 1200.0


def _strip_provider_prefix(model: str) -> str:
    # Accept litellm-style "anthropic/claude-..." names as well.
    return model.split("/", 1)[1] if model.startswith("anthropic/") else model


def _thinking_param() -> dict[str, Any] | None:
    """Thinking config from SIMPLETES_ANTHROPIC_THINKING_DISPLAY.

    summarized (default) -> {"type": "adaptive", "display": "summarized"}
    omitted              -> {"type": "adaptive"}
    none                 -> do not send the field (model default)
    """
    display = os.environ.get("SIMPLETES_ANTHROPIC_THINKING_DISPLAY", "summarized").strip().lower()
    if display == "none":
        return None
    if display == "omitted":
        return {"type": "adaptive"}
    return {"type": "adaptive", "display": "summarized"}


def _extra_body() -> dict[str, Any]:
    raw = os.environ.get("SIMPLETES_ANTHROPIC_EXTRA_BODY")
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


class AnthropicStreamClient:
    """Streaming Claude client exposing the generator's LLMBackend interface."""

    def __init__(
        self,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float | None = None,
        effort: str | None = "high",
        first_event_timeout: float | None = None,
        stall_timeout: float | None = None,
    ) -> None:
        import anthropic  # imported lazily: only needed for this backend

        self.model = _strip_provider_prefix(model)
        self.max_tokens = int(max_tokens)
        self.api_base = api_base
        self.timeout = float(timeout) if timeout else 3600.0
        self.effort = effort
        self.first_event_timeout = float(first_event_timeout or _DEFAULT_FIRST_EVENT_TIMEOUT)
        self.stall_timeout = float(stall_timeout or _DEFAULT_STALL_TIMEOUT)
        client_kwargs: dict[str, Any] = {
            # Retries are owned by the engine (it needs to see every failure).
            "max_retries": 0,
            # Per-request deadlines are enforced below; give the transport a
            # bound slightly above the total so it never cuts in first.
            "timeout": self.timeout + 60.0,
        }
        if api_key:
            client_kwargs["api_key"] = api_key
        if api_base:
            client_kwargs["base_url"] = api_base
        self._client = anthropic.AsyncAnthropic(**client_kwargs)

    # ------------------------------------------------------------------
    # Core streaming call
    # ------------------------------------------------------------------

    def _request_kwargs(self, prompt: str, max_tokens: int, effort: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        extra: dict[str, Any] = dict(_extra_body())
        thinking = _thinking_param()
        if thinking is not None:
            extra.setdefault("thinking", thinking)
        if effort:
            extra.setdefault("output_config", {"effort": effort})
        if extra:
            # Sent through extra_body so the call works regardless of whether
            # the installed SDK version has typed params for these fields.
            kwargs["extra_body"] = extra
        return kwargs

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
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
        """Run one streamed call. Returns (text, raw_output, usage, health).

        Raises LLMCallError (with ``health_class``) for every non-ok class.
        """
        total = float(timeout or self.timeout)
        first_limit = float(first_event_timeout or self.first_event_timeout)
        gap_limit = float(stall_timeout or self.stall_timeout)
        kwargs = self._request_kwargs(
            prompt, int(max_tokens or self.max_tokens), effort if effort is not None else self.effort,
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
        h: dict[str, Any] = {"model": self.model, "effort": kwargs.get("extra_body", {}).get("output_config", {}).get("effort")}

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

        # 1) open the stream (HTTP response headers)
        try:
            stream = await asyncio.wait_for(
                self._client.messages.create(**kwargs),
                timeout=min(first_limit, total),
            )
        except asyncio.TimeoutError as exc:
            raise _fail("api_no_start", exc, f"no response within {min(first_limit, total):.0f}s") from None
        except Exception as exc:  # connection / auth / 4xx / 5xx
            raise _fail("api_no_start", exc, "") from None

        # 2) consume events with first-event, stall and total deadlines
        it = stream.__aiter__()
        try:
            while True:
                now = time.monotonic()
                remaining = deadline - now
                if remaining <= 0:
                    raise _fail("timeout_mid_generation", None,
                                f"total timeout {total:.0f}s reached while events were still arriving")
                if first_event_s is None:
                    limit = min(first_limit - (now - t0), remaining)
                else:
                    limit = min(gap_limit, remaining)
                try:
                    event = await asyncio.wait_for(it.__anext__(), timeout=max(limit, 0.001))
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

                now = time.monotonic()
                if first_event_s is None:
                    first_event_s = now - t0
                else:
                    max_gap = max(max_gap, now - last_event)
                last_event = now
                n_events += 1

                etype = getattr(event, "type", None)
                if etype == "message_start":
                    u = getattr(getattr(event, "message", None), "usage", None)
                    if u is not None and getattr(u, "input_tokens", None) is not None:
                        usage["input_tokens"] = int(u.input_tokens)
                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", None)
                    if dtype == "text_delta":
                        text_parts.append(getattr(delta, "text", "") or "")
                    elif dtype == "thinking_delta":
                        thinking_parts.append(getattr(delta, "thinking", "") or "")
                elif etype == "message_delta":
                    d = getattr(event, "delta", None)
                    sr = getattr(d, "stop_reason", None)
                    if sr:
                        stop_reason = str(sr)
                    u = getattr(event, "usage", None)
                    if u is not None and getattr(u, "output_tokens", None) is not None:
                        usage["output_tokens"] = int(u.output_tokens)
                elif etype == "error":
                    err_obj = getattr(event, "error", None)
                    raise _fail("api_stalled", None, f"stream error event: {err_obj}")
        except LLMCallError:
            await _close_quietly(stream)
            raise
        except Exception as exc:  # transport error mid-stream
            await _close_quietly(stream)
            cls = "api_stalled" if first_event_s is not None else "api_no_start"
            raise _fail(cls, exc, "") from None

        text = "".join(text_parts)
        thinking = "".join(thinking_parts)
        cls = health.classify_finish(
            stop_reason, text,
            output_tokens=usage.get("output_tokens"),
            requested_max_tokens=kwargs.get("max_tokens"),
        )
        raw_output = (f"<thinking>\n{thinking}\n</thinking>\n" if thinking else "") + text
        usage_out = {k: v for k, v in usage.items() if v is not None} or None
        if cls == "ok":
            health.record(kind, _finish(cls))
            return text, raw_output, usage_out, dict(h)
        raise _fail(cls, None, f"stop_reason={stop_reason!r}, text_chars={len(text)}")

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
        """Cheap liveness probe. Returns the health dict; never raises."""
        try:
            _t, _r, _u, h = await self.stream_text(
                "Reply with the single word: pong", kind="probe", max_tokens=512,
                effort="low", timeout=timeout, first_event_timeout=timeout, stall_timeout=timeout,
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


async def _close_quietly(stream: Any) -> None:
    try:
        close = getattr(stream, "close", None)
        if close is not None:
            res = close()
            if asyncio.iscoroutine(res):
                await res
    except Exception:
        pass
