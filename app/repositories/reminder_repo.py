"""Tracks the group reminder messages sent for a checklist task, so they can be
deleted once the staff submits (keeps the group chat clean). Defensive reads."""
from __future__ import annotations

import logging

from app import clock
from app.repositories.base import as_bool
from app.sheets import client, schema

log = logging.getLogger(__name__)


def _t():
    return client.table(schema.TASK_REMINDERS)


def log_reminder(task_id: str, chat_id, message_id) -> None:
    try:
        _t().append({
            "Task ID": str(task_id), "Chat ID": str(chat_id),
            "Message ID": str(message_id), "Deleted": "",
            "Created At": clock.iso(clock.now()),
        })
    except Exception as e:  # never let tracking break a reminder send
        log.debug("reminder log failed: %s", e)


def pending_for(task_id: str) -> list[dict]:
    try:
        return [r for r in _t().all()
                if str(r.get("Task ID")) == str(task_id) and not as_bool(r.get("Deleted"))]
    except Exception as e:
        log.debug("reminder pending_for failed: %s", e)
        return []


def task_for_message(message_id) -> str | None:
    """Reverse lookup: which task/assignment a tracked message belongs to."""
    try:
        for r in _t().all():
            if str(r.get("Message ID")) == str(message_id):
                return str(r.get("Task ID"))
    except Exception as e:
        log.debug("reminder task_for_message failed: %s", e)
    return None


def mark_deleted(message_id) -> None:
    try:
        _t().update("Message ID", str(message_id), {"Deleted": "TRUE"})
    except Exception as e:
        log.debug("reminder mark_deleted failed: %s", e)
