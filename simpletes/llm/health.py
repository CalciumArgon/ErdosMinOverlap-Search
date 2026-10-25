"""API-health classification and recording for LLM calls.

Every generation / reflection / probe call ends in exactly one class:

- ``ok``                      normal end with non-empty content
- ``api_no_start``            connection / auth / HTTP error, or no stream event
                              before ``first_chunk_timeout`` - the API is broken
- ``api_stalled``             events had started, then nothing for
                              ``stall_timeout`` seconds (or an error mid-stream)
- ``timeout_mid_generation``  events kept arriving but the total ``timeout``
                              was hit - budget too large / timeout too small
- ``truncated_length``        stop reason max_tokens / length
- ``empty_content``           normal end but no text content
- ``refusal``                 stop reason refusal

Only the two ``api_*`` classes mean "the API is broken"; the engine refunds
their budget and retries them. The other classes are "deep but did not
finish" and are counted against the budget as usual.

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
ALL_CLASSES = frozenset({
    "ok", "api_no_start", "api_stalled", "timeout_mid_generation",
    "truncated_length", "empty_content", "refusal",
})


def classify_exception(exc: BaseException, *, started: bool) -> str:
    """Map an exception raised during a call to an API class.

    ``started`` tells whether at least one stream event had been received.
    Any failure before the first event means the generation never began.
    """
    return "api_stalled" if started else "api_no_start"


def classify_finish(stop_reason: str | None, text: str) -> str:
    """Classify a call that ended without an exception."""
    reason = (stop_reason or "").lower()
    if reason in {"max_tokens", "length"}:
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
            if cls in API_CLASSES:
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
    if h.get("class") in API_CLASSES:
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
