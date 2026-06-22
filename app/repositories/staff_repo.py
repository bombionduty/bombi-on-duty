"""Staff repository (spec sections 31 & 40 'Staff' tab)."""
from __future__ import annotations

from app import clock, constants
from app.repositories.base import as_bool, gen_id, now_iso
from app.sheets import client, schema


def _t():
    return client.table(schema.STAFF)


def all_staff() -> list[dict]:
    return _t().all()


def active_staff() -> list[dict]:
    return [s for s in all_staff() if as_bool(s.get("Active"))]


def get_by_staff_id(staff_id: str) -> dict | None:
    return _t().find("Staff ID", staff_id)


def get_by_telegram_id(tg_id: int | str) -> dict | None:
    return _t().find("Telegram User ID", str(tg_id))


def find_active_by_name(name: str) -> dict | None:
    name = name.strip().lower()
    for s in active_staff():
        if str(s.get("Staff Name", "")).strip().lower() == name:
            return s
    return None


def is_admin(tg_id: int) -> bool:
    from app.config import get_settings

    return int(tg_id) == get_settings().admin_telegram_user_id


def role_of(tg_id: int) -> str:
    """Resolve the effective role for a Telegram user id."""
    if is_admin(tg_id):
        return constants.ROLE_ADMIN
    s = get_by_telegram_id(tg_id)
    if s and as_bool(s.get("Active")):
        return str(s.get("Role") or constants.ROLE_STAFF)
    return ""  # unknown / not allowed


def current_oic() -> dict | None:
    for s in active_staff():
        if str(s.get("Role")) == constants.ROLE_OIC:
            return s
    return None


def add_staff(
    name: str,
    telegram_user_id: int | str,
    role: str = constants.ROLE_STAFF,
    username: str = "",
    notes: str = "",
) -> dict:
    row = {
        "Staff ID": gen_id("STAFF"),
        "Staff Name": name,
        "Telegram User ID": str(telegram_user_id),
        "Telegram Username": username.lstrip("@"),
        "Role": role,
        "Active": True,
        "Private Bot Started": False,
        "Date Added": now_iso(),
        "Date Deactivated": "",
        "Notes": notes,
    }
    return _t().append(row)


def update_staff(staff_id: str, changes: dict) -> bool:
    return _t().update("Staff ID", staff_id, changes)


def deactivate(staff_id: str) -> bool:
    return update_staff(
        staff_id, {"Active": False, "Date Deactivated": now_iso()}
    )


def set_role(staff_id: str, role: str) -> bool:
    return update_staff(staff_id, {"Role": role})


def assign_oic(staff_id: str) -> bool:
    """Make staff_id the single Store OIC; demote any previous OIC to Staff."""
    for s in all_staff():
        if str(s.get("Role")) == constants.ROLE_OIC and s.get("Staff ID") != staff_id:
            update_staff(str(s["Staff ID"]), {"Role": constants.ROLE_STAFF})
    return set_role(staff_id, constants.ROLE_OIC)


def mark_private_started(tg_id: int | str) -> None:
    s = get_by_telegram_id(tg_id)
    if s:
        update_staff(str(s["Staff ID"]), {"Private Bot Started": True})


def duplicate_active_telegram_ids() -> list[str]:
    """Production safety check (spec section 31)."""
    seen: dict[str, int] = {}
    for s in active_staff():
        tid = str(s.get("Telegram User ID"))
        seen[tid] = seen.get(tid, 0) + 1
    return [tid for tid, n in seen.items() if n > 1 and tid]
