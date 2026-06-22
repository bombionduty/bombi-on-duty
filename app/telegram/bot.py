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
from telegram.ext import Application, ApplicationBuilder

from app.config import get_settings
from app.telegram import handlers, notify

log = logging.getLogger(__name__)


def build_application() -> Application:
    settings = get_settings()
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )
    handlers.register(application)
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
