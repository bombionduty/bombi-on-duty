"""
Owner Mode scheduler hook (called once per minute from the main tick, wrapped in
the caller's try/except so it can never affect staff jobs).

Sends the daily summary and weekly reset at the configured Asia/Manila times,
each guarded by the shared marker ledger so it fires exactly once (restart-safe).
"""
from __future__ import annotations

import logging

from app import clock
from app.owner import constants as oc
from app.owner import dashboard, keyboards, messages, repo, service, summary
from app.services import markers
from app.telegram import notify

log = logging.getLogger(__name__)


def _int_setting(key: str, fallback: int) -> int:
    try:
        return int(repo.setting_or_default(key))
    except (TypeError, ValueError):
        return fallback


async def _send_task_reminders(gid, now) -> None:
    """Per-task proactive reminders (timed advance + at-due, bill advance,
    overdue check-in). Restart-safe + duplicate-safe via the marker ledger."""
    daily = repo.setting_or_default(oc.SET_DAILY_SUMMARY)
    lead_days = _int_setting(oc.SET_LEAD_DAYS, 3)
    timed_lead = _int_setting(oc.SET_TIMED_LEAD_MIN, 60)
    for ev in service.reminders_due(now, daily_hhmm=daily, lead_days=lead_days,
                                    timed_lead_min=timed_lead):
        if markers.done(ev["key"]):
            continue  # already sent (survives restarts)
        task, kind = ev["task"], ev["kind"]
        tid = str(task.get("Task ID"))
        if kind in ("soon", "due"):
            text, kb = messages.reminder_card(task, kind, timed_lead), keyboards.reminder_kb(tid)
        elif kind == "bill":
            text, kb = messages.bill_due_soon(task), keyboards.bill_kb(tid)
        else:  # overdue
            text, kb = messages.nudge(task), keyboards.nudge_kb(tid)
        await notify.send_message(gid, text, reply_markup=kb)
        markers.mark(ev["key"])


async def owner_tick() -> None:
    gid = repo.get_owner_group_id()
    if not gid:
        return  # Owner Mode not set up yet
    if repo.setting_or_default(oc.SET_PAUSED) == "true":
        return  # reminders paused (Owner Mode only — the staff scheduler is separate)

    now = clock.now()
    hhmm = now.strftime("%H:%M")

    await _send_task_reminders(gid, now)

    # Daily summary — a live message that edits itself as the day's tasks change.
    if hhmm == repo.setting_or_default(oc.SET_DAILY_SUMMARY):
        key = f"own_daily::{now.date().isoformat()}"
        if not markers.done(key):
            service.generate_due_recurrences()  # keep recurring tasks seeded
            await summary.post()
            await dashboard.refresh()
            markers.mark(key)

    # Weekly reset (e.g. "SUN 19:00")
    spec = repo.setting_or_default(oc.SET_WEEKLY_SUMMARY)
    try:
        day, wt = spec.split()
    except (ValueError, AttributeError):
        return
    if now.strftime("%a").upper() == day.upper() and hhmm == wt:
        key = f"own_weekly::{now.date().isoformat()}"
        if not markers.done(key):
            buckets = service.build_buckets()
            await notify.send_message(
                gid, messages.weekly_summary(service.weekly_stats(buckets),
                                             buckets.get(oc.B_UPCOMING, [])))
            markers.mark(key)
