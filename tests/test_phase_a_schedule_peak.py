"""Phase A — official weekly schedule fallback (Feature 1) + closing peak
support dual access (Feature 2)."""
from datetime import date

import pytest

from app import constants
from app.repositories import schedule_repo
from app.services import submission_service as ss
from app.services.submission_service import AuthError

# A Monday.
MON = date(2026, 6, 22)
assert MON.strftime("%a").upper() == "MON"


# ------------------------------------------------- official schedule fallback
def _patch_resolve(monkeypatch, explicit, official):
    monkeypatch.setattr(schedule_repo, "get", lambda d: explicit)
    monkeypatch.setattr(schedule_repo, "get_official", lambda: official)
    # Name lookup is irrelevant to id resolution; echo the id.
    monkeypatch.setattr(schedule_repo, "_name", lambda sid: f"name:{sid}" if sid else "")


def test_resolve_uses_official_when_date_unassigned(monkeypatch):
    _patch_resolve(monkeypatch, explicit=None, official={
        "MON": {"Opener Staff ID": "S1", "Closer Staff ID": "S2",
                "Closing Peak Staff ID": "S3"}})
    r = schedule_repo.resolve(MON)
    assert (r["opener_id"], r["opener_src"]) == ("S1", "official")
    assert (r["closer_id"], r["closer_src"]) == ("S2", "official")
    assert (r["peak_id"], r["peak_src"]) == ("S3", "official")


def test_explicit_override_wins_over_official(monkeypatch):
    _patch_resolve(monkeypatch,
        explicit={"Opener Staff ID": "OVR", "Closer Staff ID": "",
                  "Closing Peak Staff ID": "", "Status": "OPEN"},
        official={"MON": {"Opener Staff ID": "S1", "Closer Staff ID": "S2",
                          "Closing Peak Staff ID": "S3"}})
    r = schedule_repo.resolve(MON)
    # Opener explicitly overridden...
    assert (r["opener_id"], r["opener_src"]) == ("OVR", "set")
    # ...closer + peak left blank for the date fall back to the template.
    assert (r["closer_id"], r["closer_src"]) == ("S2", "official")
    assert (r["peak_id"], r["peak_src"]) == ("S3", "official")


def test_resolve_none_when_neither(monkeypatch):
    _patch_resolve(monkeypatch, explicit=None, official={})
    r = schedule_repo.resolve(MON)
    assert r["opener_src"] == "none" and r["opener_id"] == ""
    assert r["peak_src"] == "none"


def test_assigned_and_peak_helpers_use_fallback(monkeypatch):
    _patch_resolve(monkeypatch, explicit=None, official={
        "MON": {"Opener Staff ID": "S1", "Closer Staff ID": "S2",
                "Closing Peak Staff ID": "S3"}})
    assert schedule_repo.assigned_staff_id(MON, "opener") == "S1"
    assert schedule_repo.assigned_staff_id(MON, "closer") == "S2"
    assert schedule_repo.peak_staff_id(MON) == "S3"


# ------------------------------------------------- peak dual access (Feature 2)
CLOSER = {"Staff Name": "Carol", "Active": True, "Telegram User ID": 100}
PEAK = {"Staff Name": "Pia", "Active": True, "Telegram User ID": 200}

TASK = {
    "Task ID": "TASK1", "Checklist Type": constants.CHECK_CLOSING,
    "Assigned Staff Name": "Carol", "Assigned Telegram User ID": "100",
    "Peak Staff Name": "Pia", "Peak Telegram User ID": "200",
}


def _patch_auth(monkeypatch, caller_staff):
    monkeypatch.setattr(ss.task_repo, "get", lambda tid: TASK)
    monkeypatch.setattr(ss.staff_repo, "is_admin", lambda tg: False)
    monkeypatch.setattr(ss.staff_repo, "get_by_telegram_id", lambda tg: caller_staff)


def test_peak_staffer_may_open_closing_checklist(monkeypatch):
    _patch_auth(monkeypatch, PEAK)
    assert ss.authorize_open(dict(TASK), 200) is not None  # peak allowed


def test_assigned_closer_may_open(monkeypatch):
    _patch_auth(monkeypatch, CLOSER)
    assert ss.authorize_open(dict(TASK), 100) is not None


def test_unrelated_staff_blocked(monkeypatch):
    other = {"Staff Name": "Nope", "Active": True, "Telegram User ID": 999}
    _patch_auth(monkeypatch, other)
    with pytest.raises(AuthError):
        ss.authorize_open(dict(TASK), 999)


def test_peak_allowed_via_schedule_when_task_field_missing(monkeypatch):
    # Task's stored Peak Telegram User ID is blank/garbled, but the schedule says
    # tg 200 (Miles) is the closing peak → she must still be allowed in.
    t = {**TASK, "Peak Telegram User ID": "", "Peak Staff Name": "", "Date": "2026-11-07"}
    monkeypatch.setattr(ss.task_repo, "get", lambda tid: t)
    monkeypatch.setattr(ss.staff_repo, "is_admin", lambda tg: False)
    monkeypatch.setattr(ss.staff_repo, "get_by_telegram_id",
                        lambda tg: {"Active": True, "Staff Name": "Miles"})
    monkeypatch.setattr(ss.schedule_repo, "peak_staff_id", lambda d: "PEAK")
    monkeypatch.setattr(ss.staff_repo, "get_by_staff_id",
                        lambda sid: {"Telegram User ID": 200})
    assert ss.authorize_open(dict(t), 200) is not None


def test_peak_blocked_after_submission(monkeypatch):
    submitted = {**TASK, "Submitted At": "2026-06-22T22:00:00"}
    monkeypatch.setattr(ss.task_repo, "get", lambda tid: submitted)
    monkeypatch.setattr(ss.staff_repo, "is_admin", lambda tg: False)
    monkeypatch.setattr(ss.staff_repo, "get_by_telegram_id", lambda tg: PEAK)
    with pytest.raises(AuthError):
        ss.authorize_open(dict(submitted), 200)  # already done — no re-entry
