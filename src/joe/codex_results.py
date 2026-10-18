"""Read terminal Codex JSON events before the final answer replaces JSONL."""
from __future__ import annotations

import json
import math
import re
from typing import Any


def _field(value: Any, names: tuple[str, ...]) -> Any:
    if not isinstance(value, dict):
        return None
    for name in names:
        if name in value:
            return value[name]
    for child in value.values():
        found = _field(child, names)
        if found is not None:
            return found
    return None


def codex_failure(output: str, provider: str) -> dict[str, Any]:
    error: Any = None
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and event.get("type") in {"error", "turn.failed"}:
            error = event.get("error") or event
    if error is None:
        return {}
    message = error if isinstance(error, str) else _field(error, ("message",))
    message = str(message or "Codex turn failed")[:2000]
    status = _field(error, ("http_status", "http_status_code", "status_code", "status"))
    if not isinstance(status, int):
        match = re.search(r"(?i)(?:status(?:\s+code)?[\s:=]+|HTTP\s+)([45]\d\d)\b", message)
        status = int(match[1]) if match else None
    result: dict[str, Any] = {"error_message": message, "http_status": status}
    if provider == "deepseek":
        kind = {401: "authentication", 402: "insufficient_balance", 429: "rate_limit", 503: "unavailable"}.get(status)
        lower = message.lower()
        if not kind:
            kind = next((value for marker, value in (
                ("insufficient balance", "insufficient_balance"),
                ("invalid api key", "authentication"), ("rate limit", "rate_limit"),
                ("error sending request", "unavailable"), ("connection", "unavailable"),
            ) if marker in lower), "process")
        result["error_kind"] = kind
        retry = _field(error, ("retry_after_seconds", "retry_after"))
        if status == 429 and isinstance(retry, (int, float)) and not isinstance(retry, bool) and math.isfinite(retry) and retry >= 0:
            result["retry_after_seconds"] = float(retry)
    return result
