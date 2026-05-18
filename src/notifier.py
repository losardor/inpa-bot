"""Telegram notification dispatch.

Single async entry point: `notify_user(bot, telegram_id, offer)`. Errors are
logged, never raised — one bad chat (e.g. user blocked the bot) must not
break the rest of a poll cycle.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from src import scraper

logger = logging.getLogger(__name__)

ALLEGATO_URL_TEMPLATE = "https://portale.inpa.gov.it/api/media/{media_id}"


def _format_date_ddmmyyyy(raw: Any) -> str:
    """ISO-ish date → DD/MM/YYYY; if we can't parse, fall back to raw text."""
    if not raw:
        return "—"
    text = str(raw)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text


def _format_message(offer: dict) -> str:
    titolo = html.escape(str(offer.get("titolo") or "—"))
    enti = html.escape(str(offer.get("entiRiferimento") or "—"))
    sedi = html.escape(str(offer.get("sedi") or "—"))
    scadenza = html.escape(_format_date_ddmmyyyy(offer.get("dataScadenza")))
    posti_raw = offer.get("numPosti")
    posti = html.escape(str(posti_raw) if posti_raw is not None else "—")
    procedura = html.escape(str(offer.get("tipoProcedura") or "—"))

    return (
        f"<b>{titolo}</b>\n\n"
        f"<b>Ente:</b> {enti}\n"
        f"<b>Sedi:</b> {sedi}\n"
        f"<b>Scadenza:</b> {scadenza}\n"
        f"<b>Posti:</b> {posti}\n"
        f"<b>Procedura:</b> {procedura}"
    )


def _build_keyboard(offer: dict) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text="Vedi bando 🔗",
            url=scraper.detail_url(offer["id"]),
        )]
    ]
    media_id = offer.get("allegatoMediaId")
    if media_id:
        rows.append([InlineKeyboardButton(
            text="Scheda completa 📄",
            url=ALLEGATO_URL_TEMPLATE.format(media_id=media_id),
        )])
    return InlineKeyboardMarkup(rows)


async def notify_user(bot: Bot, telegram_id: int, offer: dict) -> None:
    """Send a formatted offer notification. Logs and swallows TelegramError."""
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=_format_message(offer),
            reply_markup=_build_keyboard(offer),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.error(
            "Telegram send_message failed: user=%s offer=%s — %s",
            telegram_id, offer.get("id"), exc,
        )
