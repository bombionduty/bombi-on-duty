"""Shift reminders — slot parsing, due-time matching, on-shift targeting, and
closed-day skip."""
import asyncio
from datetime import datetime

from app import clock
from app.repositories import shift_reminder_repo as repo
from app.services import shift_reminder_service as svc


# ---------------------------------------------------------------- encoding
def test_slots_roundtrip():
    slots = [{"time": "15:00", "role": "opener"}, {"time": "21:00", "role": "closer"}]
    enc = repo.encode_slots(slots)
    assert enc == "15:00=opener;21:00=closer"
    assert repo.parse_slots(enc) == slots


def test_parse_slots_defaults_bad_role_to_both():
    assert repo.parse_slots("09:00=wat") == [{"time": "09:00", "role": "both"}]


def test_parse_days():
    assert repo.parse_days("MON, wed ,FRI") == ["MON", "WED", "FRI"]


# --------------------------------------------------------------- due()
REMINDER = {"Reminder ID": "REM-1", "Title": "Shop", "Message": "do it",
            "Days": "", "Slots": "15:00=opener;17:00=closer", "Active": True}


def test_due_matches_time_and_role(monkeypatch):
    monkeypatch.setattr(svc.repo, "active_rows", lambda: [REMINDER])
    now = clock.combine(clock.today(), clock.parse_time("15:00"))
    due = svc.due(now)
    assert len(due) == 1 and due[0]["slot"] == {"time": "15:00", "role": "opener"}


def test_due_empty_off_time(monkeypatch):
    monkeypatch.setattr(svc.repo, "active_rows", lambda: [REMINDER])
    now = clock.combine(clock.today(), clock.parse_time("16:00"))
    assert svc.due(now) == []


def test_due_respects_weekday(monkeypatch):
    # Wed-only reminder, evaluated on a Monday → no fire.
    wed_only = {**REMINDER, "Days": "WED"}
    monkeypatch.setattr(svc.repo, "active_rows", lambda: [wed_only])
    monday = clock.combine(__import__("datetime").date(2026, 6, 22),  # a Monday
                           clock.parse_time("15:00"))
    assert svc.due(monday) == []


# --------------------------------------------------------------- fire()
def _wire(monkeypatch, status="OPEN"):
    box = {}
    monkeypatch.setattr(svc.schedule_repo, "resolve", lambda d: {
        "status": status, "opener_id": "S1", "opener_name": "Carol",
        "closer_id": "S2", "closer_name": "Allyssa", "peak_id": "", "peak_name": ""})
    monkeypatch.setattr(svc.staff_repo, "get_by_staff_id", lambda sid: {
        "Telegram Username": "carol" if sid == "S1" else "ally", "Telegram User ID": 1})

    async def _send(chat, text, **k):
        box["text"] = text
    monkeypatch.setattr(svc.notify, "send_message", _send)
    return box


def test_fire_tags_opener(monkeypatch):
    box = _wire(monkeypatch)
    asyncio.run(svc.fire(REMINDER, {"time": "15:00", "role": "opener"}, clock.today()))
    assert "@carol" in box["text"] and "Shop" in box["text"]
    assert "@ally" not in box["text"]


def test_fire_group_role_no_tag(monkeypatch):
    box = _wire(monkeypatch)
    asyncio.run(svc.fire(REMINDER, {"time": "15:00", "role": "group"}, clock.today()))
    assert "@carol" not in box["text"] and "@ally" not in box["text"]


def test_fire_skips_closed_day(monkeypatch):
    box = _wire(monkeypatch, status="CLOSED")
    asyncio.run(svc.fire(REMINDER, {"time": "15:00", "role": "opener"}, clock.today()))
    assert box == {}  # nothing posted
