"""
Inbound endpoint for the Zite inventory brief — isolated, token-protected.

Zite calls this (an OUTBOUND request from Zite, which works) after a closing
submission, pushing the Telegram-friendly report text. The bot then posts it to
the Bombi Inventory group (OWNER_TELEGRAM_CHAT_ID). The bot's Telegram token
never leaves the server; Zite only holds the shared INVENTORY_BRIEF_TOKEN.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.telegram import notify

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_TG_LIMIT = 4000  # Telegram hard limit is 4096; leave headroom


def _chunks(text: str, size: int = _TG_LIMIT) -> list[str]:
    """Split long text into <=size pieces, preferring line boundaries."""
    out: list[str] = []
    buf = ""
    for line in text.split("\n"):
        # A single very long line still has to be hard-split.
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(buf) + len(line) + 1 > size:
            if buf:
                out.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        out.append(buf)
    return out or [text]


@router.post("/inventory-brief")
async def inventory_brief(payload: dict):
    """Receive the inventory brief text from Zite and post it to the group."""
    s = get_settings()
    if not s.inventory_brief_token:
        raise HTTPException(503, "Inventory brief delivery not configured.")
    if str(payload.get("token", "")) != s.inventory_brief_token:
        raise HTTPException(403, "Bad token.")

    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Empty text.")

    chat = payload.get("chat_id") or s.owner_telegram_chat_id
    if not chat:
        raise HTTPException(400, "No destination chat set (OWNER_TELEGRAM_CHAT_ID).")

    # parse_mode is optional; default to plain text so arbitrary report text can
    # never fail Telegram's HTML/Markdown parser.
    parse_mode = payload.get("parse_mode") or None
    sent = 0
    for chunk in _chunks(text):
        try:
            await notify.bot().send_message(
                chat_id=int(chat), text=chunk, parse_mode=parse_mode,
                disable_web_page_preview=True)
            sent += 1
        except Exception as e:
            log.exception("inventory-brief send failed")
            raise HTTPException(502, f"Telegram send failed: {type(e).__name__}")
    return {"ok": True, "messages_sent": sent}
