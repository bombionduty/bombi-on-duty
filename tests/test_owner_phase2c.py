"""Phase 2C tests: proactive reminder engine (timed advance, at-due, bill,
overdue), restart/duplicate safety, reschedule invalidation, pause isolation."""
import asyncio
from datetime import datetime

from app import clock
from app.owner import constants as oc
from app.owner import repo, scheduler, service

MANILA = clock.tz()


def _dt(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=MANILA)


def _tasks(monkeypatch, rows):
    monkeypatch.setattr(repo, "all_tasks", lambda: rows)


def _kinds(now, **kw):
    kw.setdefault("daily_hhmm", "09:00")
    kw.setdefault("lead_days", 3)
    kw.setdefault("timed_lead_min", 60)
    return [e["kind"] for e in service.reminders_due(now, **kw)]


TIMED = {"Task ID": "OT1", "Title": "Edit the video", "Status": oc.ST_OPEN,
         "Due Date": "2026-06-26", "Due Time": "15:00", "Category": "content"}


# ----------------------------------------------------------- timed reminders
def test_one_hour_before_fires(monkeypatch):
    _tasks(monkeypatch, [TIMED])
    assert "soon" in _kinds(_dt(2026, 6, 26, 14, 0))      # exactly 1h before
    assert "soon" not in _kinds(_dt(2026, 6, 26, 13, 30))  # too early


def test_due_time_fires_only_at_due(monkeypatch):
    _tasks(monkeypatch, [TIMED])
    assert "due" in _kinds(_dt(2026, 6, 26, 15, 0))
    assert "due" not in _kinds(_dt(2026, 6, 26, 14, 0))   # 14:00 is the 'soon' slot


def test_custom_timed_lead(monkeypatch):
    _tasks(monkeypatch, [TIMED])
    # 30-min lead -> soon fires at 14:30, not 14:00
    assert "soon" in _kinds(_dt(2026, 6, 26, 14, 30), timed_lead_min=30)
    assert "soon" not in _kinds(_dt(2026, 6, 26, 14, 0), timed_lead_min=30)


# --------------------------------------------------------------- bill + overdue
def test_bill_advance_fires_at_daily_anchor(monkeypatch):
    bill = {"Task ID": "OB1", "Title": "Electricity", "Status": oc.ST_OPEN,
            "Due Date": "2026-06-28", "Due Time": "", "Category": "bills"}
    _tasks(monkeypatch, [bill])
    # 3 days before 06-28 = 06-25, at 09:00
    assert "bill" in _kinds(_dt(2026, 6, 25, 9, 0))
    assert "bill" not in _kinds(_dt(2026, 6, 25, 10, 0))  # wrong time
    assert "bill" not in _kinds(_dt(2026, 6, 24, 9, 0))   # wrong day


def test_overdue_checkin_once_per_day(monkeypatch):
    od = {"Task ID": "OT9", "Title": "Old task", "Status": oc.ST_OPEN,
          "Due Date": "2026-06-20", "Due Time": "", "Category": "general"}
    _tasks(monkeypatch, [od])
    assert "overdue" in _kinds(_dt(2026, 6, 24, 9, 0))    # at daily anchor
    assert "overdue" not in _kinds(_dt(2026, 6, 24, 12, 0))  # not the rest of the day


# ----------------------------------------------------- status / hidden / paused
def test_completed_task_gets_no_reminder(monkeypatch):
    done = {**TIMED, "Status": oc.ST_COMPLETED}
    _tasks(monkeypatch, [done])
    assert _kinds(_dt(2026, 6, 26, 14, 0)) == []
    assert _kinds(_dt(2026, 6, 26, 15, 0)) == []


def test_hidden_card_still_reminds(monkeypatch):
    # Hiding only clears Source Message ID; Status stays Open.
    hidden = {**TIMED, "Source Message ID": ""}
    _tasks(monkeypatch, [hidden])
    assert "soon" in _kinds(_dt(2026, 6, 26, 14, 0))


# ------------------------------------------------------ reschedule invalidation
def test_reschedule_invalidates_old_reminder(monkeypatch):
    # Task originally 06-26 15:00, now rescheduled to 06-27 16:00.
    moved = {**TIMED, "Due Date": "2026-06-27", "Due Time": "16:00"}
    _tasks(monkeypatch, [moved])
    # Old slot: nothing fires.
    assert _kinds(_dt(2026, 6, 26, 14, 0)) == []
    # New slot: soon fires 1h before the NEW time.
    assert "soon" in _kinds(_dt(2026, 6, 27, 15, 0))


def test_keys_embed_due_so_reschedule_changes_them(monkeypatch):
    _tasks(monkeypatch, [TIMED])
    k1 = service.reminders_due(_dt(2026, 6, 26, 14, 0), daily_hhmm="09:00",
                               lead_days=3, timed_lead_min=60)[0]["key"]
    moved = {**TIMED, "Due Date": "2026-06-27", "Due Time": "16:00"}
    _tasks(monkeypatch, [moved])
    k2 = service.reminders_due(_dt(2026, 6, 27, 15, 0), daily_hhmm="09:00",
                               lead_days=3, timed_lead_min=60)[0]["key"]
    assert k1 != k2  # old key never matches the new schedule


# ---------------------------------------------- restart / duplicate safety
def test_no_duplicate_reminder_across_restarts(monkeypatch):
    _tasks(monkeypatch, [TIMED])
    ledger = set()  # stands in for the persisted marker ledger (survives restart)
    sends = []
    monkeypatch.setattr(scheduler.markers, "done", lambda k: k in ledger)
    monkeypatch.setattr(scheduler.markers, "mark", lambda k: ledger.add(k))

    async def fake_send(gid, text, reply_markup=None):
        sends.append(text)
    monkeypatch.setattr(scheduler.notify, "send_message", fake_send)
    monkeypatch.setattr(scheduler.repo, "setting_or_default",
                        lambda k: oc.DEFAULTS.get(k, ""))

    now = _dt(2026, 6, 26, 14, 0)
    asyncio.run(scheduler._send_task_reminders(123, now))
    asyncio.run(scheduler._send_task_reminders(123, now))  # "after restart" — same minute
    assert len(sends) == 1  # marker ledger prevents the duplicate


# ----------------------------------------------------------- pause isolation
def test_paused_owner_sends_nothing(monkeypatch):
    sends = []

    async def fake_send(gid, *a, **k):
        sends.append(1)
    monkeypatch.setattr(scheduler.notify, "send_message", fake_send)
    monkeypatch.setattr(scheduler.repo, "get_owner_group_id", lambda: 123)

    def settings(k):
        return "true" if k == oc.SET_PAUSED else oc.DEFAULTS.get(k, "")
    monkeypatch.setattr(scheduler.repo, "setting_or_default", settings)

    asyncio.run(scheduler.owner_tick())
    assert sends == []  # paused -> owner tick is a no-op (staff scheduler untouched)
