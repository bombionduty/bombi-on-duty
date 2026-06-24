"""Owner Mode message text builders (cute, concise, emoji-led). Pure functions."""
from __future__ import annotations

import html
from datetime import date

from app import clock
from app.owner import constants as oc


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def cat_emoji(task: dict) -> str:
    return oc.CATEGORY_EMOJI.get(str(task.get("Category") or oc.CAT_GENERAL), "🍓")


def _due_label(task: dict) -> str:
    d = task.get("Due Date")
    if not d:
        return "no deadline"
    try:
        dt = clock.parse_date(str(d))
    except Exception:
        return str(d)
    today = clock.today()
    if dt == today:
        return "today"
    if dt == today.fromordinal(today.toordinal() + 1):
        return "tomorrow"
    return dt.strftime("%b %d").replace(" 0", " ")


def task_line(task: dict, *, show_due: bool = True) -> str:
    who = task.get("Responsible")
    suffix = f" — {esc(_due_label(task))}" if show_due and task.get("Due Date") else ""
    if str(task.get("Status")) == oc.ST_WAITING and who:
        return f"• {esc(who)} — {esc(task.get('Title'))}"
    return f"• {esc(task.get('Title'))}{suffix}"


# ---------------------------------------------------------- capture confirm
def confirm_card(tasks: list[dict]) -> str:
    n = len(tasks)
    head = f"🍓 <b>I caught {n} task{'s' if n != 1 else ''}</b>\n"
    lines = []
    has_recur = False
    for t in tasks:
        emoji = oc.CATEGORY_EMOJI.get(t.get("category", oc.CAT_GENERAL), "🍓")
        due = t.get("due")
        try:
            due_str = _due_label({"Due Date": due}) if due else "no date yet"
        except Exception:
            due_str = "no date yet"
        who = f" · 👤 {esc(t['responsible'])}" if t.get("responsible") else ""
        recur = ""
        if t.get("recurrence"):
            from app.owner import recurrence as _rec
            has_recur = True
            recur = f"  🔁 {esc(_rec.describe(t['recurrence']))}"
        lines.append(f"\n{emoji} <b>{esc(t['title'])}</b>{recur}\nDue: {esc(due_str)}{who}")
    foot = "\n\nLook right? You can ✏️ Edit any task before saving."
    if has_recur:
        foot += "\n\n🔁 <i>Recurring tasks will auto-repeat on schedule.</i>"
    return head + "".join(lines) + foot


def nodate_question(count: int) -> str:
    return (f"🗓 <b>{count} task{'s' if count != 1 else ''} ha"
            f"{'ve' if count != 1 else 's'} no date.</b>\nWhen should I schedule "
            f"{'them' if count != 1 else 'it'}?")


# ---------------------------------------------------------------- dashboard
def dashboard_text(buckets: dict) -> str:
    out = ["🍓 <b>BOMBI ADMIN — THIS WEEK</b>"]
    order = [oc.B_OVERDUE, oc.B_DUE_TODAY, oc.B_UPCOMING, oc.B_WAITING]
    any_active = any(buckets.get(b) for b in order)
    for b in order:
        items = buckets.get(b, [])
        if not items:
            continue
        out.append(f"\n{oc.STATUS_EMOJI[b]} <b>{b}</b>")
        for t in items:
            out.append(task_line(t))
    done = buckets.get(oc.B_COMPLETED, [])
    if done:
        out.append(f"\n✅ <b>COMPLETED THIS WEEK</b> ({len(done)})")
        for t in done[:6]:
            out.append(f"• {esc(t.get('Title'))}")
    if not any_active:
        out.append("\n🌸 You're all clear — nothing active right now. ")
    return "\n".join(out)


# ----------------------------------------------------------------- summaries
def daily_summary(greeting: str, buckets: dict) -> str:
    o = len(buckets.get(oc.B_OVERDUE, []))
    d = len(buckets.get(oc.B_DUE_TODAY, []))
    u = len(buckets.get(oc.B_UPCOMING, []))
    w = len(buckets.get(oc.B_WAITING, []))
    if o == 0 and d == 0:
        nxt = ""
        up = buckets.get(oc.B_UPCOMING, [])
        if up:
            nxt = f"\n\nYour next task is <b>{esc(up[0].get('Title'))}</b> ({_due_label(up[0])})."
        return f"🌸 <b>YOU'RE CLEAR TODAY, {esc(greeting)}!</b>\n\nNothing overdue or due today.{nxt}"
    lines = [f"🍓 <b>GOOD MORNING, {esc(greeting)}!</b>\n", "Here's what needs you today:\n"]
    lines.append(f"🔴 <b>{o} overdue</b>")
    lines.append(f"🟠 <b>{d} due today</b>")
    lines.append(f"🟡 <b>{u} coming up</b>")
    lines.append(f"🔵 <b>{w} waiting on someone</b>")
    top = (buckets.get(oc.B_OVERDUE, []) + buckets.get(oc.B_DUE_TODAY, []))[:3]
    if top:
        lines.append("\n<b>Top priorities</b>")
        for i, t in enumerate(top, 1):
            lines.append(f"{i}. {esc(t.get('Title'))}")
    return "\n".join(lines)


def weekly_summary(stats: dict, upcoming: list[dict]) -> str:
    lines = [
        "🍓 <b>YOUR WEEKLY ADMIN RESET</b>\n",
        f"✅ <b>Completed:</b> {stats.get('completed', 0)}",
        f"🟠 <b>Still pending:</b> {stats.get('pending', 0)}",
        f"🔴 <b>Overdue:</b> {stats.get('overdue', 0)}",
        f"🔵 <b>Waiting on others:</b> {stats.get('waiting', 0)}",
    ]
    if upcoming:
        lines.append("\n<b>Next week's key dates</b>")
        for t in upcoming[:6]:
            lines.append(f"• {esc(t.get('Title'))} — {_due_label(t)}")
    return "\n".join(lines)


def settings_text(s: dict) -> str:
    paused = "ON ⏸" if str(s.get(oc.SET_PAUSED)) == "true" else "off"
    return (
        "⚙️ <b>Owner Settings</b>\n\n"
        f"🌅 Daily summary: <b>{esc(s.get(oc.SET_DAILY_SUMMARY))}</b>\n"
        f"🗓 Weekly summary: <b>{esc(s.get(oc.SET_WEEKLY_SUMMARY))}</b>\n"
        f"⏰ Bill advance reminder: <b>{esc(s.get(oc.SET_LEAD_DAYS))} day(s)</b>\n"
        f"🍓 Greeting name: <b>{esc(s.get(oc.SET_GREETING_NAME))}</b>\n"
        f"🔕 Reminders paused: <b>{paused}</b>\n\n"
        "Tap a setting to change it."
    )


def nudge(task: dict) -> str:
    return (f"🍓 <b>Quick check-in</b>\n\n{oc.STATUS_EMOJI[oc.B_OVERDUE]} "
            f"<b>{esc(task.get('Title'))}</b> is still pending.\n\n"
            "Finish it today, or give it a realistic new date so it stops hanging over you.")
