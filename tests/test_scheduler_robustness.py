"""Scheduler must (a) fire a timed job within a window so a restart near the
target minute doesn't skip it, and (b) isolate each step so one failure can't
abort the rest of the tick."""
import asyncio
from datetime import date

from app import clock
from app.scheduler import jobs


def _at(hhmm):
    return clock.combine(date(2026, 11, 8), clock.parse_time(hhmm))


def test_due_once_fires_within_window(monkeypatch):
    monkeypatch.setattr(jobs.markers, "done", lambda k: False)
    assert jobs._due_once(_at("11:00"), "11:00", "k", 30) is True
    assert jobs._due_once(_at("11:20"), "11:00", "k", 30) is True   # restart recovery
    assert jobs._due_once(_at("10:59"), "11:00", "k", 30) is False  # before
    assert jobs._due_once(_at("11:40"), "11:00", "k", 30) is False  # window passed


def test_due_once_respects_marker(monkeypatch):
    monkeypatch.setattr(jobs.markers, "done", lambda k: True)
    assert jobs._due_once(_at("11:05"), "11:00", "k", 30) is False  # already fired


def test_safe_swallows_step_errors():
    async def boom():
        raise RuntimeError("kaboom")
    # Must NOT raise — a failing step can't abort the tick.
    asyncio.run(jobs._safe("boom", boom()))
