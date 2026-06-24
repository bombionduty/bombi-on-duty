"""
Owner Mode scheduler hook.

Phase 0: intentionally a no-op. It exists so the wiring into the main minute
tick is in place and proven safe. Phase 1 will add owner reminders, daily/weekly
summaries, and recurring-task generation here.

IMPORTANT: the caller in app/scheduler/jobs.py wraps this in its own try/except,
so any future error here can never interrupt the staff scheduler.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


async def owner_tick() -> None:
    # Phase 0 — no behavior yet.
    return None
