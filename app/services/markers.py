"""
Idempotency ledger for scheduled actions (spec sections 22, 42, 43).

Each one-shot action (a specific reminder, an escalation, a cutoff, a summary)
gets a unique key. We record sent keys in the Audit Log so the action never
fires twice — even across restarts. An in-memory cache avoids re-scanning the
sheet every minute.
"""
from __future__ import annotations

from app.repositories.misc_repo import audit

_ACTION = "scheduler_marker"
_cache: set[str] | None = None


def _load() -> set[str]:
    global _cache
    if _cache is None:
        _cache = {
            str(r.get("Entity ID"))
            for r in audit._t().all()  # noqa: SLF001 (internal ledger read)
            if r.get("Action") == _ACTION
        }
    return _cache


def done(key: str) -> bool:
    return key in _load()


def mark(key: str) -> None:
    if done(key):
        return
    _load().add(key)
    audit.log("system", "Scheduler", "System", _ACTION, "Marker", key)
