"""
Time helpers. EVERYTHING in this system uses Asia/Manila.

Always call these helpers instead of datetime.now() so we never accidentally
mix server UTC time with Manila business time.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.config import get_settings

_TZ = ZoneInfo(get_settings().timezone)


def tz() -> ZoneInfo:
    return _TZ


def now() -> datetime:
    """Current time in Asia/Manila (timezone-aware)."""
    return datetime.now(_TZ)


def today() -> date:
    return now().date()


def parse_date(value: str) -> date:
    """Parse 'YYYY-MM-DD'."""
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def parse_time(value: str) -> time:
    """Parse 'HH:MM' (24h)."""
    return datetime.strptime(value.strip(), "%H:%M").time()


def combine(d: date, t: time) -> datetime:
    """Combine a date + time into an Asia/Manila aware datetime."""
    return datetime.combine(d, t, tzinfo=_TZ)


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt.astimezone(_TZ).strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")


def fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt.astimezone(_TZ).strftime("%I:%M %p").lstrip("0")


def fmt_date(d: date) -> str:
    return d.strftime("%B %d, %Y")


def iso(dt: datetime | None) -> str:
    """ISO string for storage. Empty string for None."""
    return dt.astimezone(_TZ).isoformat() if dt else ""


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt
