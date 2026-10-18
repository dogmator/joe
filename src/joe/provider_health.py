from __future__ import annotations

import threading
import time
from typing import Any

from .models import ProviderResult
from .provider_registry import get_provider_spec

_COOLDOWN_SECONDS = {
    "quota": 10 * 60,
    "timeout": 5 * 60,
    "authentication": 5 * 60,
    "unavailable": 2 * 60,
}
_failures: dict[str, tuple[float | None, str]] = {}
_details: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def record_result(result: ProviderResult) -> None:
    with _lock:
        if result.ok:
            _failures.pop(result.provider, None)
            _details.pop(result.provider, None)
            return
        duration: float | None = _COOLDOWN_SECONDS.get(result.error_kind or "")
        indefinite = get_provider_spec(result.provider).quota_kind == "balance" and result.error_kind in {
            "authentication", "insufficient_balance", "rate_limit",
        }
        if indefinite:
            duration = result.retry_after_seconds if result.error_kind == "rate_limit" else None
        _details[result.provider] = {
            "error_kind": result.error_kind,
            "message": result.error_message or result.error_kind or "process failed",
            "http_status": result.http_status,
            "retry_at": (time.time() + duration if result.error_kind == "rate_limit" and duration is not None else None),
        }
        if duration is not None or indefinite:
            _failures[result.provider] = (
                time.monotonic() + duration if duration is not None else None,
                str(result.error_kind),
            )


def recent_failure(provider: str) -> tuple[str, int | None] | None:
    with _lock:
        failure = _failures.get(provider)
        if not failure:
            return None
        until, kind = failure
        if until is None:
            return kind, None
        remaining = int(max(0, until - time.monotonic()))
        if remaining <= 0:
            _failures.pop(provider, None)
            return None
        return kind, remaining


def failure_details(provider: str) -> dict[str, Any] | None:
    with _lock:
        detail = _details.get(provider)
        return dict(detail) if detail else None


def apply_cooldowns(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted = []
    for status in statuses:
        item = dict(status)
        failure = recent_failure(str(item.get("provider", "")))
        if failure:
            kind, remaining = failure
            detail = failure_details(str(item.get("provider", ""))) or {}
            item["available"] = False
            item["availability_state"] = {
                "quota": "quota_exhausted", "insufficient_balance": "balance_exhausted",
                "rate_limit": "rate_limited", "authentication": "authentication_required",
            }.get(kind, "temporarily_unavailable")
            item["cooldown_seconds"] = remaining
            item.update(error_kind=kind, http_status=detail.get("http_status"),
                        error_message=detail.get("message"), retry_at=detail.get("retry_at"))
            if get_provider_spec(str(item.get("provider", ""))).quota_kind == "balance":
                item["windows"] = []
            message = str(detail.get("message") or kind)
            item["message"] = (
                f"{message} · reprise inconnue, intervention ou nouvel essai manuel nécessaire"
                if remaining is None else
                f"{message} · pause temporaire, nouvel essai dans {max(1, (remaining + 59) // 60)} min"
            )
        adjusted.append(item)
    return adjusted


def clear_cooldowns() -> None:
    with _lock:
        _failures.clear()
        _details.clear()
