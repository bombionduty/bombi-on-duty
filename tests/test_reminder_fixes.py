"""Closing-reminder fixes: a still-pending task is nudged even when nothing is
'missing' (filled but not submitted), and the admin can nudge the group manually."""
import asyncio

from app.services import ops_service
from app.telegram import messages

TASK = {"Checklist Type": "Closing Check", "Cutoff At": "2026-11-08T01:30:00",
        "Assigned Staff Name": "Allyssa", "Assigned Telegram User ID": "77"}


def test_reminder_text_prompts_submit_when_filled():
    t = {**TASK, "Started At": "2026-11-07T22:40:00"}
    msg = messages.staff_reminder(t, [])          # nothing missing, but started
    assert "Submit" in msg


def test_reminder_text_lists_missing():
    msg = messages.staff_reminder(TASK, ["Photo of store"])
    assert "Photo of store" in msg


def test_reminder_text_not_started():
    msg = messages.staff_reminder(TASK, [])       # nothing missing, never started
    assert "haven't started" in msg.lower()


def test_nudge_group_posts_for_pending(monkeypatch):
    box = {}
    monkeypatch.setattr(ops_service.task_repo, "get", lambda tid: TASK)
    monkeypatch.setattr(ops_service.task_service, "missing_items", lambda tid: ["Photo of store"])
    monkeypatch.setattr(ops_service.task_service, "with_mention",
                        lambda t: {**t, "_assignee_mention": "@ally"})
    monkeypatch.setattr(ops_service, "_peak_mention", lambda t: "")

    async def _send(chat, text, **k):
        box["text"] = text
        return None
    monkeypatch.setattr(ops_service.notify, "send_message", _send)
    ok, msg = asyncio.run(ops_service.nudge_group("TASK-1"))
    assert ok and "@ally" in box["text"] and "Photo of store" in box["text"]


def test_nudge_group_rejects_submitted(monkeypatch):
    monkeypatch.setattr(ops_service.task_repo, "get",
                        lambda tid: {**TASK, "Submitted At": "2026-11-07T23:00:00"})
    ok, msg = asyncio.run(ops_service.nudge_group("TASK-1"))
    assert ok is False and "already submitted" in msg.lower()
