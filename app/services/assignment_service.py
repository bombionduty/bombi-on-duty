"""Staff Assignments — ad-hoc tasks the admin gives specific staff, posted to the
staff group with a Mark Done button, reminded every 2 hours while open, and
optionally recurring (reuses the Owner Mode recurrence engine).
"""
from __future__ import annotations

import html as _html
import logging
from datetime import date, datetime, timedelta

from app import clock
from app.config import get_settings
from app.owner import recurrence
from app.repositories import assignment_repo as repo
from app.repositories import staff_repo
from app.telegram import keyboards, messages, notify

log = logging.getLogger(__name__)

# Periodic nudges fire on even hours within these bounds (Asia/Manila).
NUDGE_HOURS = range(8, 21, 2)   # 08,10,12,14,16,18,20


def _mention(a: dict) -> str:
    sid = str(a.get("Assigned Staff ID") or "")
    s = staff_repo.get_by_staff_id(sid) if sid else None
    uname = str((s or {}).get("Telegram Username") or "").lstrip("@")
    name = a.get("Assigned Staff Name") or "staff"
    tgid = a.get("Assigned Telegram User ID")
    if uname:
        return f"@{uname}"
    if tgid:
        return f'<a href="tg://user?id={tgid}">{_html.escape(str(name))}</a>'
    return _html.escape(str(name))


def _due_line(a: dict) -> str:
    d = str(a.get("Due Date") or "")
    if not d:
        return ""
    try:
        label = clock.parse_date(d).strftime("%b %d, %A")
    except Exception:
        label = d
    t = str(a.get("Due Time") or "")
    if t:
        label += f" · {t}"
    return f"\n📅 Due: {messages.esc(label)}"


def card(a: dict, header: str = "📌 <b>NEW TASK ASSIGNED</b>") -> str:
    rule = str(a.get("Recurrence Rule") or "")
    rep = f"\n🔁 Repeats: {messages.esc(recurrence.describe(rule))}" if rule else ""
    return (f"{header}\n\n<b>{messages.esc(a.get('Title'))}</b>\n\n"
            f"👤 {_mention(a)}{_due_line(a)}{rep}")


async def _post_card(a: dict, header: str = "📌 <b>NEW TASK ASSIGNED</b>") -> None:
    sent = await notify.send_message(
        get_settings().staff_group_chat_id, card(a, header),
        reply_markup=keyboards.assignment_done_button(a["Assignment ID"]))
    if sent:
        repo.update(a["Assignment ID"], {"Group Message ID": str(sent.message_id)})


async def create(*, title: str, staff: dict, due_date: str = "", due_time: str = "",
                 recurrence_rule: str = "", created_by: str = "") -> dict:
    a = repo.add(title=title, staff=staff, due_date=due_date, due_time=due_time,
                 recurrence_rule=recurrence_rule, created_by=created_by)
    await _post_card(a)
    return a


def _generate_next_row(a: dict) -> dict | None:
    """Create the next occurrence of a recurring assignment (restart-safe: only
    if no open occurrence already exists in the series)."""
    rule = str(a.get("Recurrence Rule") or "")
    if not rule:
        return None
    series = str(a.get("Series ID") or "")
    if repo.open_in_series(series):
        return None  # one already open -> no duplicate
    base = clock.today()
    if a.get("Due Date"):
        try:
            base = clock.parse_date(str(a["Due Date"]))
        except Exception:
            base = clock.today()
    nd = recurrence.next_due(rule, base)
    if not nd:
        return None
    staff = {"Staff ID": a.get("Assigned Staff ID"), "Staff Name": a.get("Assigned Staff Name"),
             "Telegram User ID": a.get("Assigned Telegram User ID")}
    return repo.add(title=str(a.get("Title")), staff=staff, due_date=nd.isoformat(),
                    due_time=str(a.get("Due Time") or ""), recurrence_rule=rule,
                    series_id=series, created_by=str(a.get("Created By") or ""))


async def mark_done(assignment_id: str, by_tg_id: int) -> tuple[bool, str]:
    """Staff/admin marks an assignment done. Returns (ok, message)."""
    a = repo.get(assignment_id)
    if not a:
        return False, "This task no longer exists."
    if str(a.get("Status")) != repo.ST_OPEN:
        return False, f"Already {str(a.get('Status')).lower()}."
    is_admin = staff_repo.is_admin(by_tg_id)
    if not is_admin and str(a.get("Assigned Telegram User ID")) != str(by_tg_id):
        return False, "This task is assigned to someone else."

    repo.update(assignment_id, {"Status": repo.ST_DONE, "Completed At": repo._now()})

    # Edit the group card to a small completed state (no button).
    gid = a.get("Group Message ID")
    if gid:
        try:
            await notify.edit_message(
                get_settings().staff_group_chat_id, int(gid),
                f"✅ <b>Done — {messages.esc(a.get('Title'))}</b>\n👤 {_mention(a)}",
                reply_markup=None)
        except Exception:
            pass

    # Recurring -> spin up the next occurrence and post it.
    nxt = _generate_next_row(a)
    if nxt:
        await _post_card(nxt, header="🔁 <b>NEXT TASK</b>")
    return True, "Marked done ✅"


# ----------------------------------------------------------------- reminders
def _in_window(now: datetime, target: datetime, mins: int = 2) -> bool:
    return target <= now < target + timedelta(minutes=mins)


def reminders_due(now: datetime) -> list[dict]:
    """Which assignment reminders should fire at `now`. Restart-safe keys embed
    the assignment id + slot so each fires at most once."""
    out: list[dict] = []
    today = now.date()
    for a in repo.open_rows():
        aid = str(a.get("Assignment ID"))
        d = str(a.get("Due Date") or "")
        dd = None
        if d:
            try:
                dd = clock.parse_date(d)
            except Exception:
                dd = None
        # Skip future-dated tasks entirely (don't nudge before the due day).
        if dd and dd > today:
            continue

        # At-due reminder (timed tasks).
        tm = str(a.get("Due Time") or "")
        if dd == today and tm:
            try:
                target = clock.combine(dd, clock.parse_time(tm))
            except Exception:
                target = None
            if target and _in_window(now, target):
                out.append({"a": a, "kind": "due", "key": f"asgn_due::{aid}::{d}T{tm}"})

        # Periodic nudge every 2 hours while open (due today or overdue).
        if (dd is None or dd <= today) and now.minute == 0 and now.hour in NUDGE_HOURS:
            out.append({"a": a, "kind": "nudge",
                        "key": f"asgn_nudge::{aid}::{today.isoformat()}H{now.hour}"})
    return out
