"""Good Morning recap (previous day's checklists + tasks) and reminder cleanup."""
import asyncio
from datetime import date

from app import constants
from app.services import ops_service, summary_service


def test_checklist_status_labels():
    f = summary_service._gm_checklist_status
    assert f(None) == "🔴 Not Submitted"
    assert f({"Original Submission Status": constants.SUB_ON_TIME}) == "✅ Submitted On Time"
    assert f({"Original Submission Status": constants.SUB_LATE}) == "🟠 Submitted Late"
    assert f({"Original Submission Status": constants.SUB_NOT_SUBMITTED}) == "🔴 Not Submitted"
    assert f({"Resolution Status": constants.RES_RECOVERED_OIC}) == "🟢 Recovered by OIC"


def test_assignment_status_labels():
    assert summary_service._gm_assignment_status({"Status": "Done", "Completed Via": "photo"}) == "✅ Done 📷"
    assert summary_service._gm_assignment_status({"Status": "Open"}) == "🔴 Not Done"


def test_good_morning_text_lists_checklists_and_tasks(monkeypatch):
    d = date(2026, 6, 28)
    monkeypatch.setattr(summary_service.schedule_repo, "get",
                        lambda dd: {"Status": "OPEN", "Opener Name": "Allyssa", "Closer Name": "Angel"})
    monkeypatch.setattr(summary_service.task_repo, "for_date", lambda dd: [
        {"Checklist Type": constants.CHECK_OPENING, "Original Submission Status": constants.SUB_NOT_SUBMITTED},
        {"Checklist Type": constants.CHECK_HANDOVER, "Original Submission Status": constants.SUB_LATE},
        {"Checklist Type": constants.CHECK_CLOSING, "Original Submission Status": constants.SUB_ON_TIME},
    ])
    from app.repositories import assignment_repo
    monkeypatch.setattr(assignment_repo, "all_rows", lambda: [
        {"Title": "Clean & Arrange Toppings Bar", "Assigned Staff Name": "Allyssa",
         "Due Date": "2026-06-28", "Status": "Open"},
    ])
    text = summary_service.good_morning_text(d)
    assert "Good morning" in text
    assert "Opening Check</b>: Allyssa — 🔴 Not Submitted" in text
    assert "Opener Handover</b>: Allyssa — 🟠 Submitted Late" in text
    assert "Closing Check</b>: Angel — ✅ Submitted On Time" in text
    assert "Clean &amp; Arrange Toppings Bar — Allyssa: 🔴 Not Done" in text


def test_good_morning_closed_day(monkeypatch):
    monkeypatch.setattr(summary_service.schedule_repo, "get",
                        lambda dd: {"Status": constants.DAY_CLOSED})
    monkeypatch.setattr(summary_service.task_repo, "for_date", lambda dd: [])
    from app.repositories import assignment_repo
    monkeypatch.setattr(assignment_repo, "all_rows", lambda: [])
    text = summary_service.good_morning_text(date(2026, 6, 28))
    assert "CLOSED" in text


# ----------------------------------------------------- reminder cleanup
def test_clear_reminders_deletes_and_marks(monkeypatch):
    from app.repositories import reminder_repo
    deleted, marked = [], []
    monkeypatch.setattr(reminder_repo, "pending_for", lambda tid: [
        {"Chat ID": "-100", "Message ID": "11"}, {"Chat ID": "-100", "Message ID": "12"}])
    monkeypatch.setattr(reminder_repo, "mark_deleted", lambda mid: marked.append(mid))

    async def _del(chat, mid):
        deleted.append(mid)
        return True
    monkeypatch.setattr(ops_service.notify, "delete_message", _del)

    asyncio.run(ops_service.clear_reminders("TASK-1"))
    assert deleted == ["11", "12"] and marked == ["11", "12"]


def test_clear_reminders_keeps_record_if_delete_fails(monkeypatch):
    from app.repositories import reminder_repo
    marked = []
    monkeypatch.setattr(reminder_repo, "pending_for", lambda tid: [{"Chat ID": "-100", "Message ID": "11"}])
    monkeypatch.setattr(reminder_repo, "mark_deleted", lambda mid: marked.append(mid))

    async def _del(chat, mid):
        return False  # too old / no permission
    monkeypatch.setattr(ops_service.notify, "delete_message", _del)

    asyncio.run(ops_service.clear_reminders("TASK-1"))
    assert marked == []  # not marked deleted -> will retry next time
