"""Main entry point — wires every module together and runs the polling loop.

Run with `python -m src.scheduler`. Expects env vars per `.env.example`.

The process hosts two concurrent activities:
1. The Telegram Application (`updater.start_polling()`) — serves command handlers.
2. A poll loop that ticks every POLL_INTERVAL_SECONDS:
   fetch new offers → save → match against users → notify → mark_seen.

Blocking I/O (SQLite, the requests-based scraper) is offloaded via
asyncio.to_thread so the Telegram event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from telegram import Bot

from src import bot as bot_module
from src import db, matcher, notifier, scraper

logger = logging.getLogger("inpa-bot")

MIN_POLL_SECONDS = 900  # CLAUDE.md hard constraint
DEFAULT_POLL_SECONDS = 1800


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _read_poll_interval() -> int:
    raw = os.environ.get("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_SECONDS))
    try:
        interval = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"POLL_INTERVAL_SECONDS must be an int, got {raw!r}") from exc
    if interval < MIN_POLL_SECONDS:
        raise RuntimeError(
            f"POLL_INTERVAL_SECONDS={interval} violates the {MIN_POLL_SECONDS}s minimum"
        )
    return interval


async def _process_offer(telegram_bot: Bot, offer: dict, users: list[dict]) -> int:
    """Save the offer and notify any matching users. Returns notifications sent."""
    await asyncio.to_thread(db.save_offer, offer)
    matches = matcher.get_matching_users(offer, users)
    for user in matches:
        await notifier.notify_user(telegram_bot, user["telegram_id"], offer)
        await asyncio.to_thread(db.mark_seen, offer["id"], user["telegram_id"])
    return len(matches)


async def poll_once(telegram_bot: Bot) -> None:
    """One poll cycle: fetch → save → match → notify → mark_seen."""
    since_id = await asyncio.to_thread(db.get_latest_offer_id)

    try:
        offers = await asyncio.to_thread(scraper.fetch_new_offers, since_id)
    except Exception:
        logger.exception("Scraper call failed; skipping this cycle")
        return

    if not offers:
        logger.info("Poll cycle: fetched=0 new=0 notifications=0")
        return

    users = await asyncio.to_thread(db.get_all_users)

    new_count = 0
    notif_count = 0
    for offer in offers:
        offer_id = offer.get("id")
        if offer_id is None:
            logger.warning("Skipping offer with no id: %r", offer)
            continue
        was_new = await asyncio.to_thread(db.is_new_offer, offer_id)
        if not was_new:
            # Already in DB (shouldn't happen with since_id pagination, but be defensive).
            continue
        new_count += 1
        notif_count += await _process_offer(telegram_bot, offer, users)

    logger.info(
        "Poll cycle: fetched=%d new=%d notifications=%d",
        len(offers), new_count, notif_count,
    )


async def poll_loop(telegram_bot: Bot, interval: int) -> None:
    """Run poll cycles forever, sleeping `interval` seconds between them."""
    while True:
        try:
            await poll_once(telegram_bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Poll cycle crashed; will retry next tick")
        await asyncio.sleep(interval)


async def main_async() -> None:
    load_dotenv()
    _configure_logging()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    interval = _read_poll_interval()

    await asyncio.to_thread(db.init_db)
    application = bot_module.build_application(token)

    logger.info("Starting inpa-bot; poll interval = %d s", interval)
    async with application:
        await application.start()
        await application.updater.start_polling()
        try:
            await poll_loop(application.bot, interval)
        finally:
            logger.info("Shutting down")
            await application.updater.stop()
            await application.stop()


def main() -> None:
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped")


if __name__ == "__main__":
    main()
