"""
FastAPI auth dependencies.

Every Mini App request must carry the Telegram WebApp initData in the
`X-Telegram-Init-Data` header. We validate it server-side (spec section 7) and
attach the trusted Telegram user id + resolved role to the request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException

from app import constants
from app.repositories import staff_repo
from app.security import InitDataError, extract_user_id, validate_init_data


@dataclass
class Caller:
    tg_id: int
    role: str
    staff: Optional[dict]

    @property
    def is_admin(self) -> bool:
        return self.role == constants.ROLE_ADMIN

    @property
    def is_oic(self) -> bool:
        return self.role == constants.ROLE_OIC


async def current_caller(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> Caller:
    try:
        validated = validate_init_data(x_telegram_init_data)
        tg_id = extract_user_id(validated)
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"Auth failed: {e}")

    role = staff_repo.role_of(tg_id)
    if not role:
        raise HTTPException(status_code=403, detail="Not an authorised user.")
    staff = staff_repo.get_by_telegram_id(tg_id)

    # Passive auto-capture: the validated initData contains the real @username,
    # so keep the staff record's username fresh whenever they use the Mini App.
    try:
        username = (validated.get("user") or {}).get("username") or ""
        if staff and username and str(staff.get("Telegram Username") or "") != username:
            staff_repo.update_staff(str(staff["Staff ID"]), {"Telegram Username": username})
            staff["Telegram Username"] = username
    except Exception:
        pass  # never block a request over a username refresh

    return Caller(tg_id=tg_id, role=role, staff=staff)


async def require_admin(caller: Caller) -> Caller:
    if not caller.is_admin:
        raise HTTPException(status_code=403, detail="Admin only.")
    return caller
