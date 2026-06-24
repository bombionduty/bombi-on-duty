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
from app.owner import dashboard, messages, repo, service
from app.services import markers
from app.telegram import notify

log = logging.getLogger(__name__)


async def owner_tick() -> None:
    gid = repo.get_owner_group_id()
    if not gid:
        return  # Owner Mode not set up yet
    if repo.setting_or_default(oc.SET_PAUSED) == "true":
        return  # reminders paused

    now = clock.now()
    hhmm = now.strftime("%H:%M")

    # Daily summary
    if hhmm == repo.setting_or_default(oc.SET_DAILY_SUMMARY):
        key = f"own_daily::{now.date().isoformat()}"
        if not markers.done(key):
            buckets = service.build_buckets()
            greeting = repo.setting_or_default(oc.SET_GREETING_NAME)
            await notify.send_message(gid, messages.daily_summary(greeting, buckets))
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
