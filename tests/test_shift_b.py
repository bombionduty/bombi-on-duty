"""Shift B — the optional half-day / holiday shift.

On a Shift B day: the Opening check posts at a per-day duty-start time (default
4 PM), there is NO Opener Handover (the opener also closes), weekly checklists
(general cleaning) are suppressed, and reminder slots before duty-start are muted.
"""
from datetime import date, time

from app import constants
from app.repositories import timing_repo, schedule_repo
from app.services import weekly_service
from app.services import timeline_service as tl


D = date(2026, 11, 16)


# --------------------------------------------------------------- timing
def test_shift_b_suppresses_handover_and_moves_opening(monkeypatch):
    row = {"Release Time": "11:00", "Staff Reminder Times": "13:00,15:00",
           "OIC Escalation Time": "16:00", "Cutoff Time": "17:00"}
    monkeypatch.setattr(timing_repo, "_row_for", lambda ct, dd: row)
    monkeypatch.setattr(schedule_repo, "is_shift_b", lambda dd: True)
    monkeypatch.setattr(schedule_repo, "duty_start_time", lambda dd: time(16, 0))

    assert timing_repo.get_timing(constants.CHECK_HANDOVER, D) is None  # no handover

    t = timing_repo.get_timing(constants.CHECK_OPENING, D)
    assert t.release_at.strftime("%H:%M") == "16:00"                    # opens 4 PM
    # Whole window shifts +5h so spacing is preserved.
    assert [r.strftime("%H:%M") for r in t.reminders_at] == ["18:00", "20:00"]
    assert t.cutoff_at.strftime("%H:%M") == "22:00"


def test_shift_b_uses_configured_cutoff_when_set(monkeypatch):
    # Admin configured a 'Shift B' timing row → its absolute cutoff is used; only
    # the opening RELEASE is moved to the per-day duty start (not the cutoff).
    row = {"Release Time": "16:00", "Staff Reminder Times": "",
           "OIC Escalation Time": "17:30", "Cutoff Time": "18:00"}
    monkeypatch.setattr(timing_repo, "_row_for", lambda ct, dd: row)
    monkeypatch.setattr(timing_repo, "_shift_b_row", lambda ct: row)  # configured
    monkeypatch.setattr(schedule_repo, "is_shift_b", lambda dd: True)
    monkeypatch.setattr(schedule_repo, "duty_start_time", lambda dd: time(15, 0))

    t = timing_repo.get_timing(constants.CHECK_OPENING, D)
    assert t.release_at.strftime("%H:%M") == "15:00"   # duty start wins for release
    assert t.cutoff_at.strftime("%H:%M") == "18:00"    # configured cutoff, NOT shifted
    assert [r.strftime("%H:%M") for r in t.reminders_at] == []


def test_shift_b_closing_uses_configured_times(monkeypatch):
    row = {"Release Time": "22:00", "Staff Reminder Times": "23:00",
           "OIC Escalation Time": "23:45", "Cutoff Time": "00:30"}
    monkeypatch.setattr(timing_repo, "_row_for", lambda ct, dd: row)
    monkeypatch.setattr(timing_repo, "_shift_b_row", lambda ct: row)
    monkeypatch.setattr(schedule_repo, "is_shift_b", lambda dd: True)
    monkeypatch.setattr(schedule_repo, "duty_start_time", lambda dd: time(16, 0))

    t = timing_repo.get_timing(constants.CHECK_CLOSING, D)
    assert t.release_at.strftime("%H:%M") == "22:00"   # closing not moved by duty start
    assert t.cutoff_at.strftime("%H:%M") == "00:30"    # rolls past midnight


def test_normal_day_unchanged(monkeypatch):
    row = {"Release Time": "11:00", "Staff Reminder Times": "13:00",
           "OIC Escalation Time": "16:00", "Cutoff Time": "17:00"}
    monkeypatch.setattr(timing_repo, "_row_for", lambda ct, dd: row)
    monkeypatch.setattr(schedule_repo, "is_shift_b", lambda dd: False)
    assert timing_repo.get_timing(constants.CHECK_HANDOVER, D) is not None
    assert timing_repo.get_timing(constants.CHECK_OPENING, D).release_at.strftime("%H:%M") == "11:00"


# --------------------------------------------------------------- weekly
def test_weekly_suppressed_on_shift_b(monkeypatch):
    monkeypatch.setattr(schedule_repo, "is_shift_b", lambda d: True)
    assert weekly_service._suppressed("2026-11-16") is True
    monkeypatch.setattr(schedule_repo, "is_shift_b", lambda d: False)
    assert weekly_service._suppressed("2026-11-16") is False


# --------------------------------------------------------------- feed
def _shift_b_eff():
    return {
        "status": "", "shift_mode": constants.SHIFT_B, "duty_start": "16:00",
        "opener_id": "S1", "opener_name": "Miles", "opener_src": "set",
        "closer_id": "S2", "closer_name": "Angel", "closer_src": "official",
        "peak_id": "", "peak_name": "", "peak_src": "none",
        "explicit_closer_id": "", "explicit_peak_id": "",
    }


def test_feed_reflects_shift_b(monkeypatch):
    monkeypatch.setattr(tl.schedule_repo, "resolve", lambda d: _shift_b_eff())
    monkeypatch.setattr(tl.task_repo, "for_date", lambda d: [])
    # Handover suppressed (None); Opening at 16:00; Closing at 22:30.
    timings = {
        constants.CHECK_OPENING: timing_repo.TaskTiming(
            tl.clock.combine(D, time(16, 0)), [], tl.clock.combine(D, time(16, 0)),
            tl.clock.combine(D, time(22, 0))),
        constants.CHECK_CLOSING: timing_repo.TaskTiming(
            tl.clock.combine(D, time(22, 30)), [], tl.clock.combine(D, time(22, 30)),
            tl.clock.combine(D, time(23, 59))),
    }
    monkeypatch.setattr(tl.timing_repo, "get_timing", lambda ct, d: timings.get(ct))
    # A weekly instance exists but must NOT appear on a Shift B day.
    monkeypatch.setattr(tl.weekly_repo, "instances_for_date", lambda iso: [
        {"Instance ID": "W1", "Title": "General Cleaning", "Time": "23:00",
         "Doer Name": "Angel", "Doer Staff ID": "S2", "Group Message ID": ""}])
    # One reminder at 15:00 (before duty) + one at 17:00 (after).
    monkeypatch.setattr(tl.shift_reminder_repo, "active_rows", lambda: [
        {"Reminder ID": "R1", "Title": "Shop check", "Days": "", "Slots": "x"}])
    monkeypatch.setattr(tl.shift_reminder_repo, "parse_days", lambda s: [])
    monkeypatch.setattr(tl.shift_reminder_repo, "parse_slots", lambda s: [
        {"time": "15:00", "role": "both"}, {"time": "17:00", "role": "both"}])
    monkeypatch.setattr(tl.settings_store, "get", lambda k: {
        constants.SETTING_GOOD_MORNING_TIME: "11:00"}.get(k, ""))
    monkeypatch.setattr(tl.markers, "done", lambda key: False)

    events = tl.build(D)
    labels = [e["label"] for e in events]

    assert constants.CHECK_HANDOVER not in labels          # no handover
    assert "General Cleaning" not in labels                # weekly suppressed
    opening = next(e for e in events if e["label"] == constants.CHECK_OPENING)
    closing = next(e for e in events if e["label"] == constants.CHECK_CLOSING)
    assert opening["at"] == "4:00 PM"
    assert closing["who"] == "Miles"                       # opener closes
    shift_times = [e["time"] for e in events if e["kind"] == "shift"]
    assert "15:00" not in shift_times and "17:00" in shift_times  # pre-duty dropped
