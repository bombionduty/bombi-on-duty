"""Evidence repository (spec sections 13-15 & 'Evidence' tab)."""
from __future__ import annotations

from datetime import date

from app.repositories.base import as_bool, gen_id, now_iso
from app.sheets import client, schema
from app.repositories import task_repo


def _t():
    return client.table(schema.EVIDENCE)


def add(row: dict) -> dict:
    row.setdefault("Evidence ID", gen_id("EV"))
    row.setdefault("Uploaded At", now_iso())
    return _t().append(row)


def get(evidence_id: str) -> dict | None:
    return _t().find("Evidence ID", evidence_id)


def for_task(task_id: str) -> list[dict]:
    return _t().find_all("Task ID", task_id)


def for_task_item(task_item_id: str) -> list[dict]:
    return _t().find_all("Task Item ID", task_item_id)


def for_date(d: date) -> list[dict]:
    """All evidence whose task belongs to operating date `d`."""
    task_ids = {t["Task ID"] for t in task_repo.for_date(d)}
    return [e for e in _t().all() if e.get("Task ID") in task_ids]


def recent(limit_days: int = 14) -> list[dict]:
    """Recently uploaded evidence with a perceptual hash (for dup detection)."""
    rows = [e for e in _t().all() if e.get("Perceptual Hash")]
    return rows[-2000:] if len(rows) > 2000 else rows


def update(evidence_id: str, changes: dict) -> bool:
    return _t().update("Evidence ID", evidence_id, changes)
