"""
Owner Mode storage access (AdminSettings tab for now).

All reads are defensive: if the AdminSettings tab doesn't exist yet (e.g. before
setup_sheet has been run), every getter returns a safe default instead of
raising — so routing and the scheduler can never crash on a missing tab.
"""
from __future__ import annotations

import logging

from app import clock
from app.sheets import client, schema

log = logging.getLogger(__name__)

KEY_OWNER_GROUP = "owner_group_chat_id"


def _settings():
    return client.table(schema.ADMIN_SETTINGS)


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        row = _settings().find("Setting Key", key)
        if row and str(row.get("Setting Value")) != "":
            return str(row.get("Setting Value"))
    except Exception as e:  # tab missing / sheet unreachable -> safe default
        log.debug("owner get_setting(%s) fell back to default: %s", key, e)
    return default


def set_setting(key: str, value: str, description: str = "") -> None:
    t = _settings()
    now = clock.iso(clock.now())
    if t.find("Setting Key", key):
        t.update("Setting Key", key, {"Setting Value": value, "Updated At": now})
    else:
        t.append({"Setting Key": key, "Setting Value": value,
                  "Description": description, "Updated At": now})


def get_owner_group_id() -> int | None:
    v = get_setting(KEY_OWNER_GROUP)
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


def set_owner_group_id(chat_id) -> None:
    set_setting(KEY_OWNER_GROUP, str(chat_id), "Registered Owner Mode group chat")


def clear_owner_group_id() -> None:
    set_setting(KEY_OWNER_GROUP, "", "Owner Mode group unregistered")
