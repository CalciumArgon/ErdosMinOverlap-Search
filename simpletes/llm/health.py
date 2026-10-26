"""API-health classification and recording for LLM calls.

Every generation / reflection / probe call ends in exactly one class:

- ``ok``                      normal end with non-empty content
- ``api_no_start``            connection / auth / HTTP error, or no stream event
                              before ``first_chunk_timeout`` - the API is broken
- ``api_stalled``             events had started, then nothing for
                              ``stall_timeout`` seconds (or an error mid-stream)
- ``timeout_mid_generation``  events kept arriving but the total ``timeout``
                              was hit - budget too large / timeout too small
- ``api_stream_cut``          stop reason max_tokens but output_tokens differs
                              from the requested max_tokens - the gateway cut
                              the stream (time limit), not a real token limit
- ``truncated_length``        stop reason max_tokens / length
- ``empty_content``           normal end but no text content
- ``refusal``                 stop reason refusal

``api_no_start`` / ``api_stalled`` mean "the API is broken"; the engine
refunds their budget and retries them. ``api_stream_cut`` is not retried (the
same request would be cut again) and counts against the budget, but it feeds
the consecutive-error alert. The other classes are "deep but did not finish"
and are counted against the budget as usual.

The recorder is a process-wide singleton installed by the engine; it appends
one JSON line per call to ``<instance>/api_health.jsonl`` and prints an
``[API-HEALTH]`` line to stdout so that cluster logs can be grepped.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

API_CLASSES = frozenset({"api_no_start", "api_stalled"})
# api_stream_cut: the gateway ended the stream itself and reported it as
# max_tokens although output_tokens != the requested max_tokens (observed on
# zl.yyapi.cloud: every stream is cut at ~640 s / ~28K tokens). Retrying the
# same request would be cut again, so it is not retried, but it counts toward
# the consecutive-error alert like the other API classes.
ALERT_CLASSES = API_CLASSES | {"api_stream_cut"}
ALL_CLASSES = frozenset({
    "ok", "api_no_start", "api_stalled", "api_stream_cut", "timeout_mid_generation",
    "truncated_length", "empty_content", "refusal",
})


def classify_exception(exc: BaseException, *, started: bool) -> str:
    """Map an exception raised during a call to an API class.

    ``started`` tells whether at least one stream event had been received.
    Any failure before the first event means the generation never began.
    """
    return "api_stalled" if started else "api_no_start"


def classify_finish(
    stop_reason: str | None,
    text: str,
    *,
    output_tokens: int | None = None,
    requested_max_tokens: int | None = None,
) -> str:
    """Classify a call that ended without an exception.

    A genuine max_tokens stop has output_tokens == requested max_tokens; a
    max_tokens stop with any other count was cut by the gateway.
    """
    reason = (stop_reason or "").lower()
    if reason in {"max_tokens", "length"}:
        if output_tokens and requested_max_tokens:
            if abs(output_tokens - requested_max_tokens) > max(64, 0.02 * requested_max_tokens):
                return "api_stream_cut"
        return "truncated_length"
    if reason == "refusal":
        return "refusal"
    if not (text or "").strip():
        return "empty_content"
    return "ok"


class HealthRecorder:
    """Thread-safe JSONL writer plus consecutive-API-error tracking."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.consecutive_api_errors = 0
        self.counts: dict[str, int] = {c: 0 for c in ALL_CLASSES}
        self.last_ok_monotonic: float = time.monotonic()

    def record(self, kind: str, health: dict[str, Any]) -> None:
        cls = str(health.get("class", "unknown"))
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, **health}
        with self._lock:
            self.counts[cls] = self.counts.get(cls, 0) + 1
            if cls in ALERT_CLASSES:
                self.consecutive_api_errors += 1
            else:
                self.consecutive_api_errors = 0
                self.last_ok_monotonic = time.monotonic()
            if self.path:
                try:
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                except OSError:
                    pass
            consecutive = self.consecutive_api_errors
        print(_format_line(kind, health, consecutive), flush=True)


def _format_line(kind: str, h: dict[str, Any], consecutive: int) -> str:
    parts = [f"[API-HEALTH] {h.get('class', 'unknown')}", f"kind={kind}"]
    for key in ("elapsed_s", "first_event_s", "max_gap_s", "thinking_chars", "text_chars",
                "stop_reason", "output_tokens", "error_type"):
        val = h.get(key)
        if val is not None:
            parts.append(f"{key}={val}")
    if h.get("class") in ALERT_CLASSES:
        parts.append(f"consecutive_api_errors={consecutive}")
        msg = str(h.get("error_message") or "")[:300].replace("\n", " ")
        if msg:
            parts.append(f"msg={msg!r}")
    return " ".join(parts)


_RECORDER: HealthRecorder | None = None


def install_recorder(path: str | None) -> HealthRecorder:
    global _RECORDER
    _RECORDER = HealthRecorder(path)
    return _RECORDER


def get_recorder() -> HealthRecorder:
    global _RECORDER
    if _RECORDER is None:
        _RECORDER = HealthRecorder(None)
    return _RECORDER


def record(kind: str, health: dict[str, Any]) -> None:
    get_recorder().record(kind, health)
