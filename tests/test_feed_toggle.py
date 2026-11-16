"""Per-date Feed on/off toggle: the admin can turn any single notification OFF
for one day, and the scheduler honours it before firing."""
from datetime import date, timedelta

import pytest

from app import clock, constants
from app.repositories import timing_repo
from app.services import timeline_service as tl
from app.services import task_service as ts
from app.services import weekly_service as ws

D = date(2026, 11, 16)


def _eff():
    return {"status": "", "shift_mode": "A", "duty_start": "",
            "opener_id": "S1", "opener_name": "Miles", "opener_src": "official",
            "closer_id": "S2", "closer_name": "Angel", "closer_src": "official",
            "peak_id": "", "peak_name": "", "peak_src": "none",
            "explicit_closer_id": "", "explicit_peak_id": ""}


def _at(hhmm):
    return clock.combine(D, clock.parse_time(hhmm))


def test_feed_marks_skipped_and_toggleable(monkeypatch):
    monkeypatch.setattr(tl.schedule_repo, "resolve", lambda d: _eff())
    monkeypatch.setattr(tl.task_repo, "for_date", lambda d: [])
    monkeypatch.setattr(tl.timing_repo, "get_timing", lambda ct, d:
        timing_repo.TaskTiming(_at("08:00"), [], _at("08:00"), _at("09:00"))
        if ct == constants.CHECK_OPENING else None)
    monkeypatch.setattr(tl.weekly_repo, "instances_for_date", lambda iso: [])
    monkeypatch.setattr(tl.shift_reminder_repo, "active_rows", lambda: [])
    monkeypatch.setattr(tl.settings_store, "get",
                        lambda k: "11:00" if k == constants.SETTING_GOOD_MORNING_TIME else "")
    monkeypatch.setattr(tl.markers, "done", lambda key: False)
    # Only the opening checklist is toggled OFF.
    monkeypatch.setattr("app.repositories.skip_repo.is_skipped",
                        lambda d, kind, ref: kind == "checklist")

    events = tl.build(D)
    opening = next(e for e in events if e["kind"] == "checklist")
    gm = next(e for e in events if e["kind"] == "goodmorning")
    assert opening["skipped"] is True and opening["can_toggle"] is True
    assert gm["skipped"] is False and gm["can_toggle"] is True


@pytest.mark.asyncio
async def test_release_skips_toggled_off_checklist(monkeypatch):
    monkeypatch.setattr(ts.schedule_repo, "resolve", lambda d: _eff())
    monkeypatch.setattr(ts.task_repo, "get_by_key", lambda d, ct: None)
    past = clock.now() - timedelta(hours=1)
    monkeypatch.setattr(ts.timing_repo, "get_timing",
                        lambda ct, d: timing_repo.TaskTiming(past, [], past, past))
    monkeypatch.setattr("app.repositories.skip_repo.is_skipped",
                        lambda d, kind, ref: ref == constants.CHECK_OPENING)
    created = []

    async def fake(d, ct, timing, eff):
        created.append(ct)
        return {"Task ID": ct}

    monkeypatch.setattr(ts, "_create_and_post", fake)
    await ts.release_due_tasks(D)
    assert constants.CHECK_OPENING not in created      # toggled off
    assert constants.CHECK_CLOSING in created          # others still fire


def test_weekly_manual_skip(monkeypatch):
    monkeypatch.setattr("app.repositories.schedule_repo.is_shift_b", lambda d: False)
    monkeypatch.setattr("app.repositories.skip_repo.is_skipped",
                        lambda d, kind, ref: True)
    assert ws._suppressed({"Date": "2026-11-16", "Instance ID": "W1"}) is True
    # A non-skipped instance on a normal day runs.
    monkeypatch.setattr("app.repositories.skip_repo.is_skipped",
                        lambda d, kind, ref: False)
    assert ws._suppressed({"Date": "2026-11-16", "Instance ID": "W1"}) is False
