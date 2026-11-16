"""Regression: checklists must keep firing every week from the OFFICIAL weekday
template, without needing a dated schedule row per day.

Bug: release_due_tasks + precheck gated on schedule_repo.get(d) (a dated row),
so once a week rolled past its dated rows, no checklist cards posted at all.
"""
from datetime import date, timedelta

import pytest

from app import clock, constants
from app.repositories import timing_repo
from app.services import schedule_service as ss
from app.services import task_service as ts


def _past_timing():
    past = clock.now() - timedelta(hours=1)
    return timing_repo.TaskTiming(past, [], past, past)


def _official_effective():
    """What resolve() returns for a day with NO dated row but a filled template."""
    return {
        "status": "",  # empty => follows official, not CLOSED
        "opener_id": "S1", "opener_name": "Miles", "opener_src": "official",
        "closer_id": "S2", "closer_name": "Angel", "closer_src": "official",
        "peak_id": "", "peak_name": "", "peak_src": "none",
    }


@pytest.mark.asyncio
async def test_release_fires_from_official_without_dated_row(monkeypatch):
    monkeypatch.setattr(ts.schedule_repo, "resolve", lambda d: _official_effective())
    monkeypatch.setattr(ts.schedule_repo, "get", lambda d: None)  # NO dated row
    monkeypatch.setattr(ts.task_repo, "get_by_key", lambda d, ct: None)
    monkeypatch.setattr(ts.timing_repo, "get_timing", lambda ct, d: _past_timing())

    created = []

    async def fake_create(d, ct, timing, eff):
        created.append(ct)
        return {"Task ID": f"T-{ct}"}

    monkeypatch.setattr(ts, "_create_and_post", fake_create)

    out = await ts.release_due_tasks(date(2026, 11, 16))
    # All three checkpoints released purely from the official template.
    assert created == constants.CHECKLIST_TYPES
    assert len(out) == 3


@pytest.mark.asyncio
async def test_release_still_skips_closed_day(monkeypatch):
    eff = {**_official_effective(), "status": constants.DAY_CLOSED}
    monkeypatch.setattr(ts.schedule_repo, "resolve", lambda d: eff)
    ensured = {"n": 0}
    monkeypatch.setattr(ts, "_ensure_closed_tasks", lambda d: ensured.__setitem__("n", 1))
    out = await ts.release_due_tasks(date(2026, 11, 16))
    assert out == [] and ensured["n"] == 1


def test_precheck_ok_when_following_official(monkeypatch):
    monkeypatch.setattr(ss.schedule_repo, "resolve", lambda d: _official_effective())
    monkeypatch.setattr(ss.schedule_repo, "get", lambda d: None)  # no dated row
    monkeypatch.setattr(ss.schedule_repo, "assigned_staff_id",
                        lambda d, role: "S1" if role == "opener" else "S2")
    monkeypatch.setattr(ss.staff_repo, "get_by_staff_id",
                        lambda sid: {"Active": True, "Telegram User ID": 100})
    monkeypatch.setattr(ss.staff_repo, "current_oic", lambda: {"Staff ID": "S2"})
    monkeypatch.setattr(ss.timing_repo, "get_timing", lambda ct, d: _past_timing())
    # No "No schedule row exists" problem anymore.
    assert ss.precheck_problems(date(2026, 11, 16)) == []
