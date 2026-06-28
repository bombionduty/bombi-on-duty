"""Tests for shift reassignment: repost_checklist re-syncs the assignee
(including the Telegram User ID that authorization checks) and posts a fresh
group card. Guards the bug where reassignment didn't update Telegram User ID."""
import asyncio
from datetime import date

from app import constants
from app.services import task_service


def _wire(monkeypatch, task, new_staff, sent_id=999):
    store = {"updates": {}, "sent": [], "edited": []}
    ts = task_service

    monkeypatch.setattr(ts.task_repo, "get_by_key", lambda d, ct: task)
    monkeypatch.setattr(ts.task_repo, "get", lambda tid: {**task, **store["updates"]})

    def _update(tid, changes):
        store["updates"].update(changes)
        return True
    monkeypatch.setattr(ts.task_repo, "update", _update)
    monkeypatch.setattr(ts.schedule_repo, "assigned_staff_id", lambda d, resp: new_staff["Staff ID"])
    monkeypatch.setattr(ts.staff_repo, "get_by_staff_id", lambda sid: new_staff)
    monkeypatch.setattr(ts.audit, "log", lambda *a, **k: None)

    async def _send(chat, text, reply_markup=None):
        store["sent"].append({"text": text, "markup": reply_markup})

        class _M:
            message_id = sent_id
        return _M()

    async def _edit(chat, mid, text, reply_markup=None):
        store["edited"].append(mid)
    monkeypatch.setattr(ts.notify, "send_message", _send)
    monkeypatch.setattr(ts.notify, "edit_message", _edit)
    return store


ALLYSSA = {"Staff ID": "S2", "Staff Name": "Allyssa", "Telegram User ID": "222", "Active": "TRUE"}
TASK = {"Task ID": "TASK-1", "Checklist Type": constants.CHECK_OPENING,
        "Assigned Staff ID": "S1", "Assigned Staff Name": "Angel",
        "Assigned Telegram User ID": "111", "Staff Group Chat ID": "-100",
        "Initial Message ID": "500", "Submitted At": "", "Cutoff At": "",
        "Original Submission Status": constants.SUB_PENDING, "Started At": ""}


def test_repost_updates_telegram_user_id(monkeypatch):
    store = _wire(monkeypatch, TASK, ALLYSSA)
    asyncio.run(task_service.repost_checklist(date(2026, 6, 24), constants.CHECK_OPENING))
    # The field authorization actually checks must be updated to the new person.
    assert store["updates"]["Assigned Telegram User ID"] == "222"
    assert store["updates"]["Assigned Staff Name"] == "Allyssa"


def test_repost_retires_old_card_and_posts_new(monkeypatch):
    store = _wire(monkeypatch, TASK, ALLYSSA)
    asyncio.run(task_service.repost_checklist(date(2026, 6, 24), constants.CHECK_OPENING))
    assert 500 in store["edited"]           # old card retired
    assert len(store["sent"]) == 1          # one fresh card
    assert store["sent"][0]["markup"] is not None  # ...with the Open Checklist button
    assert store["updates"]["Initial Message ID"] == 999  # tracks the new card


def test_repost_skips_submitted_task(monkeypatch):
    store = _wire(monkeypatch, {**TASK, "Submitted At": "2026-06-24T08:00:00"}, ALLYSSA)
    res = asyncio.run(task_service.repost_checklist(date(2026, 6, 24), constants.CHECK_OPENING))
    assert res is None and store["sent"] == []  # don't disturb a completed checklist


def test_repost_skips_when_not_released(monkeypatch):
    store = _wire(monkeypatch, None, ALLYSSA)  # get_by_key -> None
    res = asyncio.run(task_service.repost_checklist(date(2026, 6, 24), constants.CHECK_OPENING))
    assert res is None and store["sent"] == []
