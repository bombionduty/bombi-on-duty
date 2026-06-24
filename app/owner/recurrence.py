"""
Recurrence rules for Owner Mode (Phase 2A).

A rule string is one of:
  * "days:N"      — every N days
  * "weekly:<wd>" — every <weekday> (0=Mon .. 6=Sun)
  * "weekly"      — weekly on the same weekday
  * "monthly"     — same day-of-month each month
  * "monthly:<d>" — the <d>th of each month (clamped to short months)

next_due() returns the NEXT occurrence strictly after `after`.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta


def next_due(rule: str, after: date) -> date | None:
    if not rule:
        return None
    if rule.startswith("days:"):
        try:
            n = int(rule.split(":", 1)[1])
        except ValueError:
            return None
        return after + timedelta(days=max(1, n))
    if rule.startswith("weekly"):
        parts = rule.split(":")
        wd = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else after.weekday()
        delta = (wd - after.weekday()) % 7
        delta = delta or 7  # strictly after -> next week if same weekday
        return after + timedelta(days=delta)
    if rule.startswith("monthly"):
        parts = rule.split(":")
        dom = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else after.day
        y, m = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
        last = calendar.monthrange(y, m)[1]
        return date(y, m, min(dom, last))
    return None


def describe(rule: str) -> str:
    """Human label for the confirm card / dashboard."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if not rule:
        return ""
    if rule.startswith("days:"):
        return f"every {rule.split(':')[1]} days"
    if rule.startswith("weekly:"):
        return f"every {days[int(rule.split(':')[1])]}"
    if rule == "weekly":
        return "weekly"
    if rule.startswith("monthly"):
        p = rule.split(":")
        return f"the {p[1]}th monthly" if len(p) > 1 and p[1] else "monthly"
    return rule
