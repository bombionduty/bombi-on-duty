"""
Thin async wrappers around the Telegram Bot API used by services + scheduler.

We keep one global `Application` (created in bot.py) and expose small helpers so
business code never imports python-telegram-bot directly. All helpers swallow
and log errors with bounded retries so a Telegram hiccup never crashes a job.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut, NetworkError

log = logging.getLogger(__name__)

_application = None  # set by bot.build_application()


def set_application(app) -> None:
    global _application
    _application = app


def bot():
    if _application is None:
        raise RuntimeError("Telegram application not initialised yet")
    return _application.bot


async def _retry(coro_factory, attempts: int = 3):
    """Run an async Telegram call with limited backoff (spec section 46)."""
    delay = 1.0
    for i in range(attempts):
        try:
            return await coro_factory()
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except (TimedOut, NetworkError) as e:
            if i == attempts - 1:
                log.warning("Telegram call failed after retries: %s", e)
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None


async def send_message(chat_id: int | str, text: str,
                       reply_markup: InlineKeyboardMarkup | None = None):
    return await _retry(lambda: bot().send_message(
        chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
        reply_markup=reply_markup, disable_web_page_preview=True,
    ))


async def edit_message(chat_id: int | str, message_id: int, text: str,
                       reply_markup: InlineKeyboardMarkup | None = None):
    return await _retry(lambda: bot().edit_message_text(
        chat_id=chat_id, message_id=message_id, text=text,
        parse_mode=ParseMode.HTML, reply_markup=reply_markup,
        disable_web_page_preview=True,
    ))


async def send_photo(chat_id: int | str, photo_bytes: bytes, caption: str = ""):
    return await _retry(lambda: bot().send_photo(
        chat_id=chat_id, photo=photo_bytes, caption=caption,
        parse_mode=ParseMode.HTML,
    ))


async def send_media_group(chat_id: int | str, media: list):
    return await _retry(lambda: bot().send_media_group(chat_id=chat_id, media=media))


async def answer_callback(callback_query_id: str, text: str = "", alert: bool = False):
    return await _retry(lambda: bot().answer_callback_query(
        callback_query_id=callback_query_id, text=text, show_alert=alert,
    ))
