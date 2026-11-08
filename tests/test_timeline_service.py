"""Unified 'Feed' timeline — one ordered list of every group notification for a
day, each tagged sent/upcoming, with on-demand re-announce."""
from datetime import date, datetime

import pytest

from app import constants
from app.services import timeline_service as tl
from app.repositories import timing_repo


# A Sunday, matching the project's current operating day.
D = date(2026, 11, 8)
assert D.strftime("%a").upper() == "SUN"


def _timing(hhmm):
    h, m = map(int, hhmm.split(":"))
    dt = datetime(D.year, D.month, D.day, h, m)
    return timing_repo.TaskTiming(dt, [], dt, dt)


def _base(monkeypatch, *, tasks=None, instances=None, reminders=None,
          markers_done=None):
    monkeypatch.setattr(tl.task_repo, "for_date", lambda d: tasks or [])
    monkeypatch.setattr(tl.weekly_repo, "instances_for_date",
                        lambda iso: instances or [])
    monkeypatch.setattr(tl.shift_reminder_repo, "active_rows",
                        lambda: reminders or [])
    monkeypatch.setattr(tl.schedule_repo, "resolve", lambda d: {
        "status": "OPEN",
        "opener_id": "S1", "opener_name": "Miles",
        "closer_id": "S2", "closer_name": "Angel",
        "peak_id": "S3", "peak_name": "Carol"})
    # Only Opening + Closing have timing configured (Handover not set).
    timings = {constants.CHECK_OPENING: _timing("08:00"),
               constants.CHECK_CLOSING: _timing("22:30")}
    monkeypatch.setattr(tl.timing_repo, "get_timing",
                        lambda ct, d: timings.get(ct))
    monkeypatch.setattr(tl.settings_store, "get", lambda k: {
        constants.SETTING_GOOD_MORNING_TIME: "11:00",
        constants.SETTING_WEEKLY_SCHEDULE_REMINDER: "SUN 18:00",
        constants.SETTING_WEEKLY_REPORT_DAY: "MON 09:00"}.get(k, ""))
    done = set(markers_done or [])
    monkeypatch.setattr(tl.markers, "done", lambda key: key in done)


def test_build_lists_checklists_with_scheduled_assignee(monkeypatch):
    _base(monkeypatch)
    events = tl.build(D)
    opening = next(e for e in events if e["label"] == constants.CHECK_OPENING)
    closing = next(e for e in events if e["label"] == constants.CHECK_CLOSING)
    assert opening["who"] == "Miles" and opening["at"] == "8:00 AM"
    assert closing["who"] == "Angel" and closing["at"] == "10:30 PM"
    # No task row released yet → "upcoming", and re-announce stays hidden.
    assert opening["sent"] is False and opening["can_announce"] is False


def test_released_checklist_shows_sent_and_can_reannounce(monkeypatch):
    _base(monkeypatch, tasks=[{
        "Checklist Type": constants.CHECK_OPENING,
        "Assigned Staff Name": "Miles", "Task ID": "T1"}])
    opening = next(e for e in tl.build(D) if e["label"] == constants.CHECK_OPENING)
    assert opening["sent"] is True and opening["can_announce"] is True
    assert opening["kind"] == "checklist" and opening["ref"] == constants.CHECK_OPENING


def test_events_are_time_ordered_and_include_recaps(monkeypatch):
    _base(monkeypatch)
    events = tl.build(D)
    times = [e["time"] for e in events]
    assert times == sorted(times)
    kinds = {e["kind"] for e in events}
    # Good Morning always present; Sunday also carries the schedule reminder.
    assert "goodmorning" in kinds and "weekly_sched" in kinds
    # It's Sunday, not Monday, so the weekly report must NOT appear.
    assert "weekly_report" not in kinds


def test_shift_reminder_resolves_role_names_and_sent_marker(monkeypatch):
    rem = {"Reminder ID": "R9", "Title": "Prep station", "Days": "SUN",
           "Slots": "15:00=both"}
    monkeypatch.setattr("app.repositories.shift_reminder_repo.parse_days",
                        lambda s: ["SUN"])
    monkeypatch.setattr("app.repositories.shift_reminder_repo.parse_slots",
                        lambda s: [{"time": "15:00", "role": "both"}])
    _base(monkeypatch, reminders=[rem],
          markers_done=["shiftrem::R9::2026-11-08::15:00::both"])
    ev = next(e for e in tl.build(D) if e["kind"] == "shift")
    assert ev["who"] == "Miles, Angel"          # both = opener + closer
    assert ev["sent"] is True
    assert ev["ref"] == "R9|15:00|both"


@pytest.mark.asyncio
async def test_announce_checklist_reposts(monkeypatch):
    called = {}

    async def fake_repost(d, ct):
        called["args"] = (d, ct)
        return {"Task ID": "T1"}

    monkeypatch.setattr("app.services.task_service.repost_checklist", fake_repost)
    ok, _ = await tl.announce("checklist", constants.CHECK_CLOSING, D)
    assert ok and called["args"] == (D, constants.CHECK_CLOSING)


@pytest.mark.asyncio
async def test_announce_shift_parses_ref(monkeypatch):
    fired = {}

    async def fake_fire(r, slot, d):
        fired["slot"] = slot

    monkeypatch.setattr("app.repositories.shift_reminder_repo.get",
                        lambda rid: {"Reminder ID": rid, "Title": "x"})
    monkeypatch.setattr("app.services.shift_reminder_service.fire", fake_fire)
    ok, _ = await tl.announce("shift", "R9|15:00|both", D)
    assert ok and fired["slot"] == {"time": "15:00", "role": "both"}
