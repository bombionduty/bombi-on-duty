"""Admin completing a checklist on a staff member's behalf must post a clear,
explicit message to the STAFF GROUP: who did it, complete/incomplete, late/on
time, and exactly which items were not submitted."""
import asyncio

from app.services import submission_service as ss

TASK = {
    "Checklist Type": "Opener Handover", "Assigned Staff Name": "Carol",
    "Submitted By Name": "Admin", "Submitted At": "2026-11-07T23:44:00",
}


def _capture(monkeypatch):
    box = {}

    async def _send(chat, text, **k):
        box["chat"], box["text"] = chat, text
    monkeypatch.setattr(ss.notify, "send_message", _send)
    return box


def test_announcement_incomplete_lists_missing_items(monkeypatch):
    box = _capture(monkeypatch)
    asyncio.run(ss._announce_admin_completion(
        TASK, ["Photo of sales", "Mop water emptied"], late=True))
    t = box["text"]
    assert "Submitted (Incomplete)" in t
    assert "on behalf of Carol" in t
    assert "Admin" in t
    assert "LATE" in t
    assert "Photo of sales" in t and "Mop water emptied" in t
    assert "Not submitted (2)" in t


def test_announcement_complete_on_time(monkeypatch):
    box = _capture(monkeypatch)
    asyncio.run(ss._announce_admin_completion(TASK, [], late=False))
    t = box["text"]
    assert "Submitted (Complete)" in t
    assert "on time" in t
    assert "Not submitted" not in t
