"""
Builds the python-telegram-bot Application and wires handlers.

We run PTB in two possible modes (spec section 49):
  * webhook  — production: Telegram POSTs updates to /telegram/webhook.
  * polling  — quick local testing without a public URL.
The FastAPI lifespan (main.py) drives initialise/start/stop.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import ChatMigrated
from telegram.ext import Application, ApplicationBuilder

from app.config import get_settings
from app.telegram import handlers, notify

log = logging.getLogger(__name__)


async def _on_error(update, context) -> None:
    """Global error handler. Self-heals the most common breakage: a Telegram
    group silently upgrading to a supergroup (which changes its chat id). When
    that happens we repoint the registered Owner Mode group to the new id so the
    bot keeps working on the next action."""
    err = context.error
    if isinstance(err, ChatMigrated):
        try:
            from app.owner import repo as owner_repo
            old = owner_repo.get_owner_group_id()
            if old != err.new_chat_id:
                owner_repo.set_owner_group_id(err.new_chat_id)
                log.warning("Owner group migrated to supergroup %s (was %s) — "
                            "registration auto-updated.", err.new_chat_id, old)
        except Exception:
            log.exception("Failed to auto-heal chat migration")
        return
    log.error("Unhandled error while processing update", exc_info=err)


def build_application() -> Application:
    settings = get_settings()
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )
    handlers.register(application)
    application.add_error_handler(_on_error)
    notify.set_application(application)
    return application


async def start_application(application: Application) -> None:
    settings = get_settings()
    await application.initialize()
    await application.start()
    if settings.telegram_mode == "webhook":
        webhook_url = f"{settings.base_url}/telegram/webhook"
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            secret_token=settings.secret_key[:64],
            drop_pending_updates=True,
        )
        log.info("Webhook set to %s/telegram/webhook", settings.base_url)
    else:
        await application.updater.start_polling(drop_pending_updates=True)
        log.info("Polling started")


async def stop_application(application: Application) -> None:
    settings = get_settings()
    if settings.telegram_mode != "webhook" and application.updater:
        await application.updater.stop()
    await application.stop()
    await application.shutdown()
