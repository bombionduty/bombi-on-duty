"""Phase 1 follow-up tests: shared dates, before/by/on, edit flow, security,
dashboard recovery, recurrence labeling."""
import asyncio
from datetime import date

import pytest
from telegram.error import BadRequest

from app import clock
from app.owner import constants as oc
from app.owner import dashboard, draft, messages, parser, routing


def _fix_today(monkeypatch, d):
    monkeypatch.setattr(clock, "today", lambda: d)


# ----------------------------------------------------------- shared dates
def test_shared_trailing_date_applies_to_all(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 24))  # Wednesday
    tasks = parser.parse("count the envelopes, write the ORs, and edit two videos this week")
    assert len(tasks) == 3
    assert all(t["due"] == "2026-06-28" for t in tasks)  # upcoming Sunday


def test_explicit_per_task_dates_win(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 24))
    tasks = parser.parse("pay electricity on the 28th and film a video tomorrow")
    by_title = {t["title"]: t["due"] for t in tasks}
    assert by_title["Pay electricity"] == "2026-06-28"
    assert by_title["Film a video"] == "2026-06-25"


def test_this_week_on_sunday_is_today(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 28))  # Sunday
    assert parser.parse("write the OR this week")[0]["due"] == "2026-06-28"


# -------------------------------------------------------- before/by/on
def test_before_by_on_thursday(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 24))  # Wed; Thursday = Jun 25
    assert parser.parse("finish this before thursday")[0]["due"] == "2026-06-24"
    assert parser.parse("finish this by thursday")[0]["due"] == "2026-06-25"
    assert parser.parse("finish this on thursday")[0]["due"] == "2026-06-25"


def test_before_monday_when_today_is_monday_asks(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 22))  # Monday; before Mon = Sun (past)
    assert parser.parse("finish this before monday")[0]["due"] == ""  # -> bot asks


def test_past_oneoff_date_is_dropped(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 24))  # Wed
    # "before wednesday" -> Tuesday (yesterday) -> past -> no date
    assert parser.parse("do it before wednesday")[0]["due"] == ""


# -------------------------------------------------------------- edit flow
def test_edit_one_task_does_not_affect_others():
    bid = draft.create([{"title": "A", "due": ""}, {"title": "B", "due": ""}])
    assert draft.edit_title(bid, 1, "Bee")
    d = draft.get(bid)
    assert d[0]["title"] == "A" and d[1]["title"] == "Bee"
    draft.discard(bid)


def test_cancel_discards_entire_draft():
    bid = draft.create([{"title": "A"}])
    draft.discard(bid)
    assert draft.get(bid) is None


def test_stale_edit_after_confirm_cannot_modify():
    bid = draft.create([{"title": "A", "due": ""}])
    draft.pop(bid)  # simulates Confirm consuming the draft
    assert draft.edit_title(bid, 0, "X") is False
    assert draft.get(bid) is None


def test_draft_pop_accepts_default_arg():
    # Regression: handlers call draft.pop(batch, None) — must not TypeError.
    bid = draft.create([{"title": "A"}])
    assert draft.pop(bid, None) is not None
    assert draft.pop("missing", None) is None  # default returned, no error


def test_draft_never_persists_prematurely():
    import inspect
    src = inspect.getsource(draft)
    assert "repo" not in src and "add_task" not in src  # no save path in drafts


# --------------------------------------------------------------- security
def test_capture_allowed_requires_owner_chat_and_admin(monkeypatch):
    OWNER, ADMIN = -999, 555000111  # ADMIN matches conftest
    monkeypatch.setattr(routing, "owner_group_id", lambda: OWNER)
    base = dict(chat_id=OWNER, user_id=ADMIN, is_bot=False, has_text=True)
    assert routing.capture_allowed(**base) is True
    assert routing.capture_allowed(**{**base, "user_id": 111}) is False         # non-admin
    assert routing.capture_allowed(**{**base, "chat_id": -1001234567890}) is False  # staff group
    assert routing.capture_allowed(**{**base, "chat_id": -1}) is False          # other group
    assert routing.capture_allowed(**{**base, "is_bot": True}) is False         # bot message
    assert routing.capture_allowed(**{**base, "has_text": False}) is False      # service/channel/no text


# ------------------------------------------------------- dashboard recovery
class _FakeBot:
    def __init__(self, edit_exc=None):
        self.edit_exc = edit_exc
        self.edited = 0
        self.pinned = 0

    async def edit_message_text(self, **kwargs):
        self.edited += 1
        if self.edit_exc:
            raise self.edit_exc

    async def pin_chat_message(self, *a, **k):
        self.pinned += 1


class _FakeMsg:
    message_id = 999


def _wire_dashboard(monkeypatch, saved_id, edit_exc):
    state = {"saved": saved_id, "sent": 0}
    monkeypatch.setattr(dashboard.repo, "get_owner_group_id", lambda: 123)
    monkeypatch.setattr(dashboard.service, "build_buckets",
                        lambda: {b: [] for b in (oc.B_OVERDUE, oc.B_DUE_TODAY,
                                                 oc.B_UPCOMING, oc.B_WAITING, oc.B_COMPLETED)})
    monkeypatch.setattr(dashboard.repo, "get_setting", lambda k, d=None: state["saved"])
    monkeypatch.setattr(dashboard.repo, "set_setting",
                        lambda k, v, description="": state.update(saved=v))
    bot = _FakeBot(edit_exc)
    monkeypatch.setattr(dashboard.notify, "bot", lambda: bot)

    async def fake_send(chat, text, reply_markup=None):
        state["sent"] += 1
        return _FakeMsg()
    monkeypatch.setattr(dashboard.notify, "send_message", fake_send)
    return state, bot


def test_dashboard_edit_success_no_duplicate(monkeypatch):
    state, bot = _wire_dashboard(monkeypatch, "55", None)
    asyncio.run(dashboard.refresh())
    assert bot.edited == 1 and state["sent"] == 0 and state["saved"] == "55"


def test_dashboard_deleted_is_recreated_once(monkeypatch):
    state, bot = _wire_dashboard(monkeypatch, "55", BadRequest("Message to edit not found"))
    asyncio.run(dashboard.refresh())
    assert state["sent"] == 1 and state["saved"] == "999" and bot.pinned == 1


def test_dashboard_not_modified_no_duplicate(monkeypatch):
    state, bot = _wire_dashboard(monkeypatch, "55", BadRequest("Message is not modified"))
    asyncio.run(dashboard.refresh())
    assert state["sent"] == 0 and state["saved"] == "55"


def test_dashboard_no_saved_id_creates_and_saves(monkeypatch):
    state, bot = _wire_dashboard(monkeypatch, "", None)
    asyncio.run(dashboard.refresh())
    assert state["sent"] == 1 and state["saved"] == "999"


# --------------------------------------------------------- recurrence label
def test_recurrence_is_labeled_functional(monkeypatch):
    _fix_today(monkeypatch, date(2026, 6, 24))
    parsed = parser.parse("every sunday submit the weekly OR")
    assert parsed[0]["recurrence"].startswith("weekly")
    card = messages.confirm_card(parsed)
    # Phase 2A: recurrence works -> card shows it will repeat, not a "Phase 2" caveat.
    assert "auto-repeat" in card.lower() and "Phase 2" not in card
