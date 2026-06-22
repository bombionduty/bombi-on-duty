"""
Secure evidence image serving (spec section 27).

Browser <img> tags cannot send custom headers, so this route accepts the
Telegram initData as the `auth` query parameter and validates it server-side.
Evidence is NEVER public: the caller must be the admin, the current OIC, or the
staff member tied to the evidence.
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app import constants
from app.repositories import evidence_repo, staff_repo
from app.security import InitDataError, extract_user_id, validate_init_data
from app.services import drive_service

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evidence")


def _authorise(auth: str, evidence: dict) -> None:
    try:
        tg_id = extract_user_id(validate_init_data(auth))
    except InitDataError as e:
        raise HTTPException(401, f"Auth failed: {e}")

    if staff_repo.is_admin(tg_id):
        return
    oic = staff_repo.current_oic()
    if oic and str(oic.get("Telegram User ID")) == str(tg_id):
        return
    # The original assignee or actual uploader may view their own evidence.
    me = staff_repo.get_by_telegram_id(tg_id)
    if me and str(me.get("Staff ID")) in (
        str(evidence.get("Original Assigned Staff ID")),
        str(evidence.get("Submitted By Staff ID")),
    ):
        return
    raise HTTPException(403, "Not authorised to view this evidence.")


@router.get("/{evidence_id}/image")
async def evidence_image(evidence_id: str, auth: str = Query(...)):
    ev = evidence_repo.get(evidence_id)
    if not ev:
        raise HTTPException(404, "Evidence not found.")
    _authorise(auth, ev)
    file_id = ev.get("Drive File ID")
    if not file_id:
        raise HTTPException(404, "No stored file.")
    try:
        data = drive_service.download_bytes(file_id)
    except Exception as e:
        log.warning("Evidence download failed: %s", e)
        raise HTTPException(502, "Could not retrieve evidence from storage.")
    return StreamingResponse(io.BytesIO(data),
                             media_type=ev.get("MIME Type") or "image/jpeg")
