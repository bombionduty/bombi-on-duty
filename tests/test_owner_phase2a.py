"""Phase 2A tests: recurrence engine + date display + card actions."""
from datetime import date

from app import clock
from app.owner import constants as oc
from app.owner import keyboards, messages, recurrence, repo, service


# --------------------------------------------------------- date display
def test_fmt_due_shared_helper(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 6, 24))  # Wednesday
    assert messages.fmt_due("2026-06-24") == "June 24, Wednesday · Today"
    assert messages.fmt_due("2026-06-26") == "June 26, Friday"
    assert messages.fmt_due("2026-06-24", "11:00") == "June 24, Wednesday · 11:00 AM"
    assert messages.fmt_due("2027-01-04") == "January 4, 2027, Monday"


def test_dashboard_and_card_use_same_format(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 6, 24))
    t = {"Title": "Launch milkshakes", "Due Date": "2026-06-26", "Status": "Open"}
    assert "June 26, Friday" in messages.task_card(t)
    db = messages.dashboard_text({oc.B_UPCOMING: [t], oc.B_OVERDUE: [],
                                  oc.B_DUE_TODAY: [], oc.B_WAITING: [], oc.B_COMPLETED: []})
    assert "June 26, Friday" in db


# --------------------------------------------------- recurring-safe cards
def _flat(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_main_card_is_compact_with_more():
    flat = _flat(keyboards.task_card_kb("OT1", False))
    assert flat == ["own:dn:OT1", "own:rs:OT1", "own:more:OT1"]


def test_recurring_more_menu_has_skip_not_cancel():
    flat = _flat(keyboards.task_more_kb("OT1", True))
    assert "own:sk:OT1" in flat and "own:hide:OT1" in flat
    assert not any("own:cxt" in c for c in flat)


def test_oneoff_more_menu_has_cancel_not_skip():
    flat = _flat(keyboards.task_more_kb("OT1", False))
    assert "own:cxt:OT1" in flat and "own:hide:OT1" in flat
    assert not any("own:sk" in c for c in flat)


def test_draft_meta_tracks_message_ids():
    from app.owner import draft
    bid = draft.create([{"title": "A"}], capture_chat=123, capture_msg=99)
    draft.set_confirm_msg(bid, 100)
    m = draft.meta(bid)
    assert m["capture_chat"] == 123 and m["capture_msg"] == 99 and m["confirm_msg"] == 100
    draft.pop(bid)
    assert draft.meta(bid) == {}  # meta cleared on pop


def test_cancelled_not_on_dashboard():
    assert service.bucket_for({"Status": oc.ST_CANCELLED, "Due Date": "2026-06-24"}) is None


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


def test_parse_monthly_of_the_month(monkeypatch):
    from app.owner import parser
    monkeypatch.setattr(clock, "today", lambda: date(2026, 6, 29))
    t = parser.parse("Pay rent every 15th of the month")[0]
    assert t["recurrence"] == "monthly:15" and t["due"] == "2026-07-15"
    assert t["title"] == "Pay rent"  # recurrence phrase stripped from title


def test_parse_monthly_end_of_month(monkeypatch):
    from app.owner import parser
    monkeypatch.setattr(clock, "today", lambda: date(2026, 6, 29))
    t = parser.parse("Staff payroll every end of the month")[0]
    assert t["recurrence"] == "monthly:31" and t["due"] == "2026-06-30"


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


# ------------------------------------------------------- card actions
def test_complete_is_idempotent(monkeypatch):
    state = {"status": "Open"}
    monkeypatch.setattr(repo, "get_task",
                        lambda tid: {"Task ID": tid, "Status": state["status"], "Recurrence ID": ""})
    monkeypatch.setattr(repo, "update_task",
                        lambda tid, ch: state.update(status=ch.get("Status", state["status"])) or True)
    monkeypatch.setattr(repo, "log_history", lambda *a, **k: None)
    assert service.complete("OT1") is not None   # first completes
    assert service.complete("OT1") is None        # second: already done -> no-op


def test_reschedule_does_not_touch_recurrence(monkeypatch):
    captured = {}
    monkeypatch.setattr(repo, "get_task",
                        lambda tid: {"Task ID": tid, "Recurrence ID": "R1", "Due Date": "2026-06-24"})
    monkeypatch.setattr(repo, "update_task", lambda tid, ch: captured.update(ch) or True)
    monkeypatch.setattr(repo, "log_history", lambda *a, **k: None)
    service.reschedule("OT1", date(2026, 6, 26))
    assert captured.get("Due Date") == "2026-06-26"
    assert "Recurrence ID" not in captured  # the recurring rule is untouched


def test_safe_delete_never_crashes_without_permission():
    import asyncio
    from app.owner import handlers

    class _Bot:
        def __init__(self, fail):
            self.fail = fail
            self.calls = 0

        async def delete_message(self, chat_id, message_id):
            self.calls += 1
            if self.fail:
                raise Exception("not enough rights to delete")

    class _Ctx:
        pass

    ok = _Ctx(); ok.bot = _Bot(False)
    assert asyncio.run(handlers._safe_delete(ok, 1, 2)) is True
    bad = _Ctx(); bad.bot = _Bot(True)
    assert asyncio.run(handlers._safe_delete(bad, 1, 2)) is False     # missing perm -> no crash
    assert asyncio.run(handlers._safe_delete(ok, 1, None)) is False   # no id -> no-op


def test_cancel_sets_status_and_logs_history(monkeypatch):
    calls = {"upd": {}, "hist": []}
    monkeypatch.setattr(repo, "get_task", lambda tid: {"Task ID": tid, "Status": "Open", "Title": "X"})
    monkeypatch.setattr(repo, "update_task", lambda tid, ch: calls["upd"].update(ch) or True)
    monkeypatch.setattr(repo, "log_history", lambda tid, a, d="": calls["hist"].append(a))
    service.cancel("OT1")
    assert calls["upd"]["Status"] == oc.ST_CANCELLED and "cancelled" in calls["hist"]
