"""A weekly task that runs past midnight (e.g. General Cleaning Sat 23:00 →
cutoff Sun 01:30) must post its card anytime inside the window, even after
midnight — not be blocked by the calendar date flipping to Sunday."""
from datetime import date

from app import clock
from app.services import weekly_service as ws

CUTOFF = clock.iso(clock.combine(date(2026, 11, 8), clock.parse_time("01:30")))
INST = {"Instance ID": "I1", "Status": ws.repo.ST_PENDING, "Group Message ID": "",
        "Date": "2026-11-07", "Time": "23:00", "Cutoff At": CUTOFF}


def _at(d, hhmm):
    return clock.combine(d, clock.parse_time(hhmm))


def test_posts_after_midnight_within_window(monkeypatch):
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [INST])
    assert [i["Instance ID"] for i in ws.due_to_post(_at(date(2026, 11, 8), "00:48"))] == ["I1"]


def test_posts_at_start(monkeypatch):
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [INST])
    assert [i["Instance ID"] for i in ws.due_to_post(_at(date(2026, 11, 7), "23:00"))] == ["I1"]


def test_no_post_after_cutoff(monkeypatch):
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [INST])
    assert ws.due_to_post(_at(date(2026, 11, 8), "02:00")) == []


def test_no_post_before_start(monkeypatch):
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [INST])
    assert ws.due_to_post(_at(date(2026, 11, 7), "22:00")) == []


def test_no_post_once_already_posted(monkeypatch):
    posted = {**INST, "Group Message ID": "123"}
    monkeypatch.setattr(ws.repo, "open_instances", lambda: [posted])
    assert ws.due_to_post(_at(date(2026, 11, 8), "00:48")) == []
