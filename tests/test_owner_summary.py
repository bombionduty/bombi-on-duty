"""Live morning summary: sorted unfinished list + recurring overview."""
from datetime import date

from app import clock
from app.owner import constants as oc
from app.owner import messages, recurrence, repo, service


def _fix_today(monkeypatch, d):
    monkeypatch.setattr(clock, "today", lambda: d)


def test_today_summary_lists_unfinished_by_section(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 29))
    buckets = {
        oc.B_OVERDUE: [{"Title": "Audit chocolates", "Due Date": "2026-06-26", "Status": "Open"}],
        oc.B_DUE_TODAY: [{"Title": "Write invoices", "Due Date": "2026-06-29", "Status": "Open"}],
        oc.B_UPCOMING: [{"Title": "Prep payroll", "Due Date": "2026-07-01", "Status": "Open"}],
        oc.B_WAITING: [], oc.B_COMPLETED: [{"Title": "done1"}, {"Title": "done2"}],
    }
    recurring = [{"title": "Submit weekly OR", "rule": "every Sun", "next": "Jul 5"}]
    text = messages.today_summary("Lesha", buckets, recurring)
    assert "GOOD MORNING, Lesha" in text
    # Concise: overdue is a count (not a list), due-today + next-up are listed.
    assert "1 overdue" in text and "Audit chocolates" not in text
    assert "Write invoices" in text          # due today
    assert "Prep payroll" in text            # next upcoming day
    assert "ON REPEAT" in text and "Submit weekly OR" in text and "Jul 5" in text
    assert "2 done this week" in text


def test_today_summary_all_clear(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 29))
    empty = {b: [] for b in (oc.B_OVERDUE, oc.B_DUE_TODAY, oc.B_UPCOMING,
                             oc.B_WAITING, oc.B_COMPLETED)}
    text = messages.today_summary("Lesha", empty, [])
    assert "caught up" in text.lower()


def test_recurring_overview_uses_rule_and_next(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 29))  # Monday
    monkeypatch.setattr(repo, "active_recurring", lambda: [
        {"Title": "Submit OR", "Rule": "weekly:6", "Last Generated": "2026-06-28"},
        {"Title": "Pay rent", "Rule": "monthly:5", "Last Generated": ""},
    ])
    ov = service.recurring_overview()
    titles = {r["title"]: r for r in ov}
    assert "Submit OR" in titles and "Pay rent" in titles
    assert "Sun" in titles["Submit OR"]["rule"]
    assert titles["Submit OR"]["next"]  # a concrete next date is shown
