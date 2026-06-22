"""
The single FastAPI application (spec section 49).

It hosts everything in one process:
  * Telegram webhook receiver
  * Staff + Admin Mini App JSON API
  * Secure evidence image serving
  * Static Mini App frontend
  * The 1-minute scheduler
  * A health check
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from telegram import Update

from app.config import get_settings
from app.logging_setup import setup_logging
from app.scheduler import runner as scheduler_runner
from app.telegram import bot as tg_bot
from app.web.routes_evidence import router as evidence_router
from app.web.routes_miniapp import router as miniapp_router

setup_logging()
log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("Starting Berry Bomb Ops (%s, test_mode=%s)",
             settings.environment_name, settings.test_mode)
    application = tg_bot.build_application()
    app.state.tg = application
    await tg_bot.start_application(application)
    scheduler_runner.start()
    try:
        yield
    finally:
        scheduler_runner.shutdown()
        await tg_bot.stop_application(application)


app = FastAPI(title="Berry Bomb Daily Ops", lifespan=lifespan)
app.include_router(miniapp_router)
app.include_router(evidence_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    settings = get_settings()
    # Verify Telegram's secret token (set in bot.start_application).
    if x_telegram_bot_api_secret_token != settings.secret_key[:64]:
        raise HTTPException(403, "Bad secret token.")
    data = await request.json()
    application = request.app.state.tg
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}


# Static Mini App frontend (served at /static/...).
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
