"""
APScheduler setup. One job: run jobs.tick() every minute in Asia/Manila.

We use a single AsyncIOScheduler bound to the FastAPI event loop. coalesce +
max_instances=1 guarantee we never stack overlapping ticks (spec section 42/43).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import clock
from app.scheduler import jobs

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler:
        return _scheduler
    _scheduler = AsyncIOScheduler(timezone=clock.tz())
    _scheduler.add_job(
        jobs.tick,
        trigger="cron",
        second=0,                 # top of every minute
        id="ops_tick",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=55,
    )
    _scheduler.start()
    log.info("Scheduler started (1-minute tick, %s)", clock.tz())
    return _scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
