"""Staff Assignments: reminder cadence (due + every-2h), recurrence (next
occurrence, no duplicates), and done authorization."""
import asyncio
from datetime import date, datetime

from app import clock
from app.repositories import assignment_repo as repo
from app.services import assignment_service as svc

MANILA = clock.tz()


def _dt(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=MANILA)


def _rows(monkeypatch, rows):
    monkeypatch.setattr(repo, "all_rows", lambda: rows)


OPEN_TIMED = {"Assignment ID": "ASG1", "Series ID": "S1", "Title": "Restock Biscoff",
              "Assigned Staff ID": "ST1", "Assigned Staff Name": "Allyssa",
              "Assigned Telegram User ID": "222", "Due Date": "2026-06-24",
              "Due Time": "15:00", "Status": "Open", "Recurrence Rule": ""}


def _kinds(now):
    return [(e["kind"], e["key"]) for e in svc.reminders_due(now)]


# ----------------------------------------------------------- reminder cadence
def test_due_time_reminder_fires(monkeypatch):
    _rows(monkeypatch, [OPEN_TIMED])
    kinds = [k for k, _ in _kinds(_dt(2026, 6, 24, 15, 0))]
    assert "due" in kinds


def test_every_2h_nudge_on_even_hours(monkeypatch):
    _rows(monkeypatch, [OPEN_TIMED])
    assert "nudge" in [k for k, _ in _kinds(_dt(2026, 6, 24, 14, 0))]   # 14:00 even hour
    assert "nudge" not in [k for k, _ in _kinds(_dt(2026, 6, 24, 15, 0))]  # 15:00 odd -> no nudge
    assert "nudge" not in [k for k, _ in _kinds(_dt(2026, 6, 24, 14, 30))]  # not top of hour


def test_future_task_is_not_nudged(monkeypatch):
    future = {**OPEN_TIMED, "Due Date": "2026-06-30"}
    _rows(monkeypatch, [future])
    assert _kinds(_dt(2026, 6, 24, 14, 0)) == []  # don't nag before the due day


def test_done_task_gets_no_reminders(monkeypatch):
    _rows(monkeypatch, [{**OPEN_TIMED, "Status": "Done"}])
    assert _kinds(_dt(2026, 6, 24, 14, 0)) == []
    assert _kinds(_dt(2026, 6, 24, 15, 0)) == []


def test_reminder_keys_are_unique_per_slot(monkeypatch):
    _rows(monkeypatch, [OPEN_TIMED])
    k1 = {key for _, key in _kinds(_dt(2026, 6, 24, 14, 0))}
    k2 = {key for _, key in _kinds(_dt(2026, 6, 24, 16, 0))}
    assert k1 and k2 and k1.isdisjoint(k2)  # different hours -> different keys (no dup)


# ------------------------------------------------------------- recurrence
def test_recurring_generates_one_next(monkeypatch):
    added = []
    monkeypatch.setattr(repo, "open_in_series", lambda s: [])
    monkeypatch.setattr(repo, "add", lambda **kw: added.append(kw) or {**kw, "Assignment ID": "new"})
    a = {**OPEN_TIMED, "Recurrence Rule": "days:1", "Due Date": "2026-06-24"}
    nxt = svc._generate_next_row(a)
    assert nxt is not None and len(added) == 1
    assert added[0]["due_date"] == "2026-06-25"  # next day


def test_recurring_no_duplicate_if_open_exists(monkeypatch):
    added = []
    monkeypatch.setattr(repo, "open_in_series", lambda s: [{"Assignment ID": "x"}])
    monkeypatch.setattr(repo, "add", lambda **kw: added.append(kw))
    a = {**OPEN_TIMED, "Recurrence Rule": "days:1"}
    assert svc._generate_next_row(a) is None and added == []  # restart-safe


def test_oneoff_generates_nothing(monkeypatch):
    monkeypatch.setattr(repo, "add", lambda **kw: (_ for _ in ()).throw(AssertionError("should not add")))
    assert svc._generate_next_row(OPEN_TIMED) is None  # no rule -> nothing


# ------------------------------------------------------------- done auth
def test_only_assignee_or_admin_can_mark_done(monkeypatch):
    monkeypatch.setattr(repo, "get", lambda i: dict(OPEN_TIMED))
    monkeypatch.setattr(repo, "update", lambda i, c: True)
    monkeypatch.setattr(svc.staff_repo, "is_admin", lambda uid: False)

    async def _noedit(*a, **k):
        pass
    monkeypatch.setattr(svc.notify, "edit_message", _noedit)
    monkeypatch.setattr(svc, "_generate_next_row", lambda a: None)

    ok_wrong, _ = asyncio.run(svc.mark_done("ASG1", 999))   # not the assignee
    assert ok_wrong is False
    ok_right, _ = asyncio.run(svc.mark_done("ASG1", 222))   # the assignee (tg id 222)
    assert ok_right is True


# ------------------------------------------------------------- photo proof
def test_photo_proof_records_file_and_via(monkeypatch):
    saved = {}
    monkeypatch.setattr(repo, "get", lambda i: dict(OPEN_TIMED))
    monkeypatch.setattr(repo, "update", lambda i, c: saved.update(c) or True)
    monkeypatch.setattr(svc.staff_repo, "is_admin", lambda uid: False)
    monkeypatch.setattr(svc, "_generate_next_row", lambda a: None)

    async def _noedit(*a, **k):
        pass
    monkeypatch.setattr(svc.notify, "edit_message", _noedit)

    ok, msg = asyncio.run(svc.mark_done("ASG1", 222, proof_file_id="FILE123"))
    assert ok and saved["Proof File ID"] == "FILE123" and saved["Completed Via"] == "photo"


def test_find_by_group_message_matches_open(monkeypatch):
    a = {**OPEN_TIMED, "Group Message ID": "777"}
    _rows(monkeypatch, [a])
    assert svc.find_by_group_message(777)["Assignment ID"] == "ASG1"
    assert svc.find_by_group_message(111) is None


def test_open_for_staff_filters_by_tg_id(monkeypatch):
    a1 = {**OPEN_TIMED, "Assignment ID": "A1", "Assigned Telegram User ID": "222"}
    a2 = {**OPEN_TIMED, "Assignment ID": "A2", "Assigned Telegram User ID": "333"}
    _rows(monkeypatch, [a1, a2])
    mine = svc.open_for_staff(222)
    assert len(mine) == 1 and mine[0]["Assignment ID"] == "A1"
