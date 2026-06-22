"""
Shared helpers for the repository layer.

The repositories wrap the Google Sheets tables (spec section 40) so that the
rest of the app never talks to gspread directly. This is the seam that lets us
swap Sheets for a real database later without touching business logic.
"""
from __future__ import annotations

import uuid

from app import clock


def gen_id(prefix: str) -> str:
    """Short unique id, e.g. 'TASK-3f9a1c2b'."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def as_bool(value) -> bool:
    """Interpret a sheet cell as a boolean. Sheets store TRUE/FALSE strings."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "y"}


def now_iso() -> str:
    return clock.iso(clock.now())
