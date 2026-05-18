"""Telegram command handlers.

User-facing: /start, /profilo, /offerte, /help.
Admin-only:  /utenti — gated by ADMIN_TELEGRAM_ID env var.

Profiles are configured out-of-band (no /register command); a user without a
profile sees a friendly message with their telegram_id so they can ask the
admin to set them up.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src import db, matcher, scraper

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Ciao! Sono <b>inpa-bot</b>. Monitoro inpa.gov.it per nuovi concorsi "
    "pubblici e ti avviso quando ne trovo uno adatto al tuo profilo.\n\n"
    "Usa /profilo per vedere i tuoi filtri, /offerte per gli ultimi bandi che "
    "ti riguardano, /help per la lista completa dei comandi."
)

HELP_TEXT = (
    "Comandi disponibili:\n"
    "/start — messaggio di benvenuto\n"
    "/profilo — i tuoi filtri attuali\n"
    "/offerte — ultime 5 offerte che corrispondono al tuo profilo\n"
    "/help — questo elenco"
)

_FILTER_LABELS: dict[str, str] = {
    "keywords": "Parole chiave",
    "regioni": "Regioni",
    "categorie": "Categorie",
    "settori": "Settori",
    "tipo_procedura": "Tipo procedura",
}


def _is_admin(telegram_id: int) -> bool:
    raw = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
    if not raw:
        return False
    try:
        return int(raw) == telegram_id
    except ValueError:
        logger.warning("ADMIN_TELEGRAM_ID is set but not an int: %r", raw)
        return False


def _format_profile(user: dict[str, Any]) -> str:
    filters = user.get("filters") or {}
    name = html.escape(str(user.get("name") or ""))
    lines = [f"<b>Profilo di {name}</b>"]

    if filters.get("notifica_tutto"):
        lines.append("\n<i>Notifica tutto attivo</i>: ricevi ogni nuovo bando.")
        return "\n".join(lines)

    any_set = False
    for key, label in _FILTER_LABELS.items():
        values = filters.get(key)
        if values:
            any_set = True
            rendered = ", ".join(html.escape(str(v)) for v in values)
            lines.append(f"<b>{label}:</b> {rendered}")

    if not any_set:
        lines.append("<i>Nessun filtro impostato — riceverai ogni nuovo bando.</i>")
    return "\n".join(lines)


def _summarise_filters(filters: dict[str, Any] | None) -> str:
    if not filters:
        return "nessun filtro"
    if filters.get("notifica_tutto"):
        return "notifica_tutto"
    bits = []
    for key in _FILTER_LABELS:
        values = filters.get(key)
        if values:
            bits.append(f"{key}={len(values)}")
    return ", ".join(bits) or "nessun filtro"


async def _get_user(telegram_id: int) -> dict | None:
    users = await asyncio.to_thread(db.get_all_users)
    return next((u for u in users if u["telegram_id"] == telegram_id), None)


async def start_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode="HTML")


async def help_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(HELP_TEXT)


async def profilo_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    telegram_id = update.effective_user.id
    user = await _get_user(telegram_id)

    if user is None:
        await update.message.reply_text(
            "Non hai ancora un profilo configurato.\n\n"
            "<b>Impostazioni di default:</b>\n"
            "Nessun filtro — riceveresti ogni nuovo bando.\n\n"
            "Per impostare filtri personalizzati, contatta l'amministratore "
            f"e fornisci il tuo Telegram ID: <code>{telegram_id}</code>",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(_format_profile(user), parse_mode="HTML")


async def offerte_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    telegram_id = update.effective_user.id
    user = await _get_user(telegram_id)

    if user is None:
        await update.message.reply_text(
            "Non hai un profilo configurato. Usa /profilo per maggiori informazioni."
        )
        return

    recent = await asyncio.to_thread(db.get_recent_offers, 100)
    matched: list[dict] = []
    for offer in recent:
        if matcher.get_matching_users(offer, [user]):
            matched.append(offer)
            if len(matched) >= 5:
                break

    if not matched:
        await update.message.reply_text(
            "Nessuna offerta recente corrisponde al tuo profilo."
        )
        return

    lines = ["<b>Ultime offerte per te:</b>", ""]
    for offer in matched:
        titolo = html.escape(str(offer.get("titolo") or "—"))
        link = scraper.detail_url(offer["id"])
        lines.append(f"• <a href=\"{link}\">{titolo}</a>")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="HTML", disable_web_page_preview=True
    )


async def utenti_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Comando riservato all'amministratore.")
        return

    users = await asyncio.to_thread(db.get_all_users)
    if not users:
        await update.message.reply_text("Nessun utente registrato.")
        return

    lines = [f"<b>Utenti registrati ({len(users)}):</b>", ""]
    for user in users:
        name = html.escape(str(user.get("name") or ""))
        summary = html.escape(_summarise_filters(user.get("filters")))
        lines.append(f"• <code>{user['telegram_id']}</code> {name} — {summary}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def build_application(token: str) -> Application:
    """Wire all command handlers onto a fresh Application."""
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("profilo", profilo_handler))
    application.add_handler(CommandHandler("offerte", offerte_handler))
    application.add_handler(CommandHandler("utenti", utenti_handler))
    return application
