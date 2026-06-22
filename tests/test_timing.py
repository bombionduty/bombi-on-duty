"""Timing resolution test, including the cross-midnight rule (spec section 21)."""
from datetime import date

from app import clock
from app.repositories import timing_repo


def test_cross_midnight_cutoff(monkeypatch):
    # Closing releases 23:15 and cuts off 23:55 (same day) — no crossing.
    row = {
        "Checklist Type": "Closing Check", "Day Type": "Default",
        "Release Time": "23:15", "Staff Reminder Times": "23:35",
        "OIC Escalation Time": "23:45", "Cutoff Time": "00:30", "Active": "TRUE",
    }
    monkeypatch.setattr(timing_repo, "_row_for", lambda ct, d: row)
    d = date(2026, 6, 22)
    timing = timing_repo.get_timing("Closing Check", d)
    # cutoff 00:30 < release 23:15 -> next day
    assert timing.cutoff_at.date() == date(2026, 6, 23)
    assert timing.release_at.date() == d


def test_reminders_sorted(monkeypatch):
    row = {
        "Checklist Type": "Opening Check", "Day Type": "Default",
        "Release Time": "12:00", "Staff Reminder Times": "12:45, 12:30",
        "OIC Escalation Time": "13:00", "Cutoff Time": "13:30", "Active": "TRUE",
    }
    monkeypatch.setattr(timing_repo, "_row_for", lambda ct, d: row)
    timing = timing_repo.get_timing("Opening Check", date(2026, 6, 22))
    assert [clock.fmt_time(t) for t in timing.reminders_at] == ["12:30 PM", "12:45 PM"]
