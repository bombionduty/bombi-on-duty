"""Phase 2A tests: recurrence engine (next_due + generation, no duplicates)."""
from datetime import date

from app import clock
from app.owner import recurrence, repo, service


def test_next_due_weekly():
    # Sunday 2026-06-28; "every Sunday" -> next Sunday 07-05
    assert recurrence.next_due("weekly:6", date(2026, 6, 28)) == date(2026, 7, 5)
    # Wed 06-24; every Friday -> 06-26
    assert recurrence.next_due("weekly:4", date(2026, 6, 24)) == date(2026, 6, 26)


def test_next_due_days_and_monthly():
    assert recurrence.next_due("days:4", date(2026, 6, 24)) == date(2026, 6, 28)
    # monthly:31 from Jan -> clamped to Feb 28 (2026 not a leap year)
    assert recurrence.next_due("monthly:31", date(2026, 1, 15)) == date(2026, 2, 28)
    assert recurrence.next_due("monthly:15", date(2026, 6, 15)) == date(2026, 7, 15)


def test_describe():
    assert "Sun" in recurrence.describe("weekly:6")
    assert recurrence.describe("days:4") == "every 4 days"


def _mock_recurrence(monkeypatch, rule, open_list):
    store = {"added": [], "updated": []}
    rec = {"Recurrence ID": "R1", "Title": "Weekly OR", "Category": "or",
           "Rule": rule, "Active": "TRUE", "Time": "", "Responsible": ""}
    monkeypatch.setattr(repo, "get_recurring", lambda rid: rec)
    monkeypatch.setattr(repo, "open_occurrences", lambda rid: open_list)
    monkeypatch.setattr(repo, "add_task", lambda *a, **k: store["added"].append(k) or {"Task ID": "new"})
    monkeypatch.setattr(repo, "update_recurring", lambda rid, ch: store["updated"].append(ch))
    return store


def test_complete_generates_exactly_one_next(monkeypatch):
    store = _mock_recurrence(monkeypatch, "weekly:6", open_list=[])
    service._generate_next({"Recurrence ID": "R1", "Due Date": "2026-06-28"})
    assert len(store["added"]) == 1
    assert store["added"][0]["due_date"] == "2026-07-05"  # next Sunday
    assert store["updated"][0]["Last Generated"] == "2026-07-05"


def test_no_duplicate_when_open_occurrence_exists(monkeypatch):
    store = _mock_recurrence(monkeypatch, "weekly:6", open_list=[{"Task ID": "x"}])
    service._generate_next({"Recurrence ID": "R1", "Due Date": "2026-06-28"})
    assert store["added"] == []  # restart-safe: no duplicate


def test_non_recurring_task_generates_nothing(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(repo, "get_recurring", lambda rid: called.update(n=called["n"] + 1))
    service._generate_next({"Recurrence ID": "", "Due Date": "2026-06-28"})
    assert called["n"] == 0  # never even looked up
