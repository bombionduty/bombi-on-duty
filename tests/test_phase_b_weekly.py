"""Phase B — weekly accountability checklists (Feature 3):
occurrence date math, cross-midnight cutoff, and the two-step doer→checker
photo flow (accountability requires two different people)."""
import asyncio
from datetime import date

import pytest

from app.repositories import weekly_repo as repo
from app.services import weekly_service as ws


# ------------------------------------------------- date / cutoff math
def test_this_week_occurrence_each_weekday():
    # Wed 2026-06-24 → that week's Monday is 2026-06-22.
    ref = date(2026, 6, 24)
    assert ws._this_week_occurrence("MON", ref) == date(2026, 6, 22)
    assert ws._this_week_occurrence("WED", ref) == date(2026, 6, 24)
    assert ws._this_week_occurrence("SAT", ref) == date(2026, 6, 27)
    assert ws._this_week_occurrence("SUN", ref) == date(2026, 6, 28)


def test_cutoff_crosses_midnight():
    occ = date(2026, 6, 27)  # Saturday
    # 23:00 task with a 01:00 cutoff → cutoff is Sunday 01:00.
    iso = ws._cutoff_at(occ, "23:00", "01:00")
    assert iso.startswith("2026-06-28T01:00")


def test_cutoff_same_day():
    occ = date(2026, 6, 22)
    iso = ws._cutoff_at(occ, "11:00", "13:00")
    assert iso.startswith("2026-06-22T13:00")


# ------------------------------------------------- two-step photo flow
DOER = {"Staff ID": "D", "Staff Name": "Dina", "Telegram User ID": 11}
CHECKER = {"Staff ID": "C", "Staff Name": "Cara", "Telegram User ID": 22}

BASE = {
    "Instance ID": "WKI1", "Weekly ID": "WK1", "Title": "General Cleaning",
    "Date": "2026-06-22", "Doer Staff ID": "D", "Doer Name": "Dina",
    "Doer Telegram User ID": "11", "Status": repo.ST_PENDING,
    "Group Message ID": "500",
}


def _wire(monkeypatch, start_status=repo.ST_PENDING):
    store = {"inst": {**BASE, "Status": start_status}}
    monkeypatch.setattr(ws.repo, "get_instance", lambda iid: store["inst"])

    def _upd(iid, changes):
        store["inst"] = {**store["inst"], **changes}
        return True
    monkeypatch.setattr(ws.repo, "update_instance", _upd)
    monkeypatch.setattr(ws.staff_repo, "is_admin", lambda tg: False)
    monkeypatch.setattr(ws.staff_repo, "get_by_telegram_id",
                        lambda tg: DOER if str(tg) == "11" else (CHECKER if str(tg) == "22" else None))
    monkeypatch.setattr(ws.staff_repo, "get_by_staff_id", lambda sid: None)

    async def _noop_edit(*a, **k):
        return None
    monkeypatch.setattr(ws.notify, "edit_message", _noop_edit)
    return store


def test_doer_photo_advances_to_doer_done(monkeypatch):
    store = _wire(monkeypatch, repo.ST_PENDING)
    ok, note = asyncio.run(ws.attach_photo("WKI1", 11, "file_doer"))
    assert ok and store["inst"]["Status"] == repo.ST_DOER_DONE
    assert store["inst"]["Doer Photo File ID"] == "file_doer"


def test_non_doer_cannot_do_step_one(monkeypatch):
    store = _wire(monkeypatch, repo.ST_PENDING)
    ok, note = asyncio.run(ws.attach_photo("WKI1", 22, "file_x"))
    # Not handled — leaves it for a correct match / stays pending.
    assert ok is False and store["inst"]["Status"] == repo.ST_PENDING


def test_checker_verifies(monkeypatch):
    store = _wire(monkeypatch, repo.ST_DOER_DONE)
    ok, note = asyncio.run(ws.attach_photo("WKI1", 22, "file_check"))
    assert ok and store["inst"]["Status"] == repo.ST_VERIFIED
    assert store["inst"]["Checker Name"] == "Cara"
    assert store["inst"]["Checker Photo File ID"] == "file_check"


def test_doer_cannot_verify_own(monkeypatch):
    store = _wire(monkeypatch, repo.ST_DOER_DONE)
    ok, note = asyncio.run(ws.attach_photo("WKI1", 11, "file_self"))
    # Handled (we reply) but NOT verified — accountability needs a second person.
    assert ok is True and store["inst"]["Status"] == repo.ST_DOER_DONE
    assert "someone else" in note.lower()


def test_pending_for_staff_roles(monkeypatch):
    pending = {**BASE, "Status": repo.ST_PENDING}
    doerdone = {**BASE, "Instance ID": "WKI2", "Status": repo.ST_DOER_DONE}
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [pending, doerdone])
    # Doer (11): sees the pending one (to do), not the doer-done one (can't verify own).
    ids = [i["Instance ID"] for i in ws.pending_for_staff(11)]
    assert ids == ["WKI1"]
    # Someone else (22): can verify the doer-done one, but not do the doer's pending.
    ids2 = [i["Instance ID"] for i in ws.pending_for_staff(22)]
    assert ids2 == ["WKI2"]
