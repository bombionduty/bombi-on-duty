"""
Daily Owner Brief (Zite Inventory) integration — a SELF-CONTAINED module.

The bot acts only as the scheduler/trigger: it POSTs to Zite's already-built
endpoint, which generates the report and emails it. This module never touches
Berry Bomb staff/owner data — it only makes an outbound HTTP call and, on
failure, alerts the owner in Telegram.

Config (all from env, see .env.example):
  ZITE_OWNER_BRIEF_URL, ZITE_OWNER_BRIEF_TOKEN, OWNER_EMAILS,
  OWNER_TELEGRAM_CHAT_ID, OWNER_BRIEF_TIME
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app import clock
from app.config import get_settings
from app.telegram import notify

log = logging.getLogger(__name__)

_TIMEOUT = 60.0  # the report can take a while to generate


@dataclass
class BriefResult:
    ok: bool
    status: int | None
    duration_s: float
    text: str = ""          # Telegram-friendly body, if the endpoint returns one
    error: str = ""


def _extract_telegram_text(resp: httpx.Response) -> str:
    """Pull the Telegram-friendly text out of the response, tolerant of shape."""
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "").strip()
    if isinstance(data, dict):
        for key in ("telegram", "telegramText", "telegram_text", "text",
                    "message", "body"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


async def _post_once(send_email: bool, day: str | None) -> httpx.Response:
    s = get_settings()
    payload: dict = {"token": s.zite_owner_brief_token, "sendEmail": send_email,
                     "recipients": s.owner_email_list}
    if day:
        payload["day"] = day  # forward-compatible; Zite may ignore if unsupported
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.post(str(s.zite_owner_brief_url), json=payload)


async def run_brief(*, send_email: bool = True, deliver_telegram: bool = False,
                    day: str | None = None, alert_on_failure: bool = True) -> BriefResult:
    """Call the Zite endpoint with one retry. Logs start/status/duration/email.
    On final failure, optionally alerts the owner in Telegram."""
    s = get_settings()
    if not s.owner_brief_configured:
        log.warning("Owner Brief not configured (ZITE_OWNER_BRIEF_URL/TOKEN unset).")
        return BriefResult(ok=False, status=None, duration_s=0.0,
                           error="Owner Brief not configured.")

    started = time.monotonic()
    log.info("Owner Brief: start (send_email=%s, day=%s) at %s",
             send_email, day or "today", clock.iso(clock.now()))

    last_err = ""
    last_status: int | None = None
    for attempt in (1, 2):  # one retry
        try:
            resp = await _post_once(send_email, day)
            last_status = resp.status_code
            if resp.is_success:
                dur = time.monotonic() - started
                text = _extract_telegram_text(resp)
                log.info("Owner Brief: OK %s in %.1fs (attempt %d, email=%s)",
                         resp.status_code, dur, attempt, send_email)
                if deliver_telegram and text:
                    await _deliver(text)
                return BriefResult(ok=True, status=resp.status_code,
                                   duration_s=dur, text=text)
            last_err = f"{resp.status_code} {resp.reason_phrase}"
            log.warning("Owner Brief: attempt %d failed — %s", attempt, last_err)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            log.warning("Owner Brief: attempt %d error — %s", attempt, last_err)

    dur = time.monotonic() - started
    log.error("Owner Brief: FAILED after retry in %.1fs — %s", dur, last_err)
    if alert_on_failure:
        await _alert_failure(last_err)
    return BriefResult(ok=False, status=last_status, duration_s=dur, error=last_err)


def _alert_chat_id() -> int | None:
    s = get_settings()
    return s.owner_telegram_chat_id or s.admin_telegram_user_id


async def _deliver(text: str) -> None:
    """Send the Telegram-friendly report to the inventory owner chat (future use)."""
    chat = _alert_chat_id()
    if chat:
        await notify.send_message(chat, text)


async def _alert_failure(reason: str) -> None:
    chat = _alert_chat_id()
    if not chat:
        return
    await notify.send_message(
        chat, f"⚠️ <b>Daily Owner Brief failed.</b>\n\nReason:\n{reason}\n\n"
        "(Already retried once.) I'll try again at the next scheduled run.")
