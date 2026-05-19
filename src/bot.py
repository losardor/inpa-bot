"""Telegram command handlers.

User-facing: /start, /profilo, /offerte, /help.
Admin-only:  /utenti, /approva, /revoca — gated by ADMIN_TELEGRAM_ID env var.

Enrolment flow:
- First /start from an unknown user creates a row in `users` with
  status='pending' and empty filters, replies with a "in attesa" message, and
  pings the admin to approve.
- /approva <telegram_id> [key=val,val ...] activates the pending user with the
  given filters and DMs them a confirmation.
- /revoca <telegram_id> flips the user back to pending and clears their
  filters (used when a friend's situation changes).
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from typing import Any

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from src import db, matcher, scraper

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Ciao! Sono <b>inpa-bot</b>. Monitoro inpa.gov.it per nuovi concorsi "
    "pubblici e ti avviso quando ne trovo uno adatto al tuo profilo.\n\n"
    "Usa /profilo per vedere i tuoi filtri, /offerte per gli ultimi bandi che "
    "ti riguardano, /help per la lista completa dei comandi."
)

PENDING_TEXT = (
    "Ciao! Sei stato registrato. Un amministratore attiverà il tuo profilo "
    "a breve. Ti avviseremo non appena sarà pronto."
)

ACTIVATED_TEXT = (
    "Il tuo profilo è stato attivato! Riceverai notifiche per le nuove "
    "offerte che corrispondono al tuo profilo. Usa /profilo per vedere i "
    "tuoi filtri e /offerte per le opportunità già disponibili."
)

HELP_TEXT = (
    "Comandi disponibili:\n"
    "/start — registrazione / messaggio di benvenuto\n"
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

APPROVA_KEYS: tuple[str, ...] = (
    "keywords",
    "regioni",
    "categorie",
    "settori",
    "tipo_procedura",
    "tutto",
)

_APPROVA_SPLITTER = re.compile(
    r"\s+(?=(?:" + "|".join(APPROVA_KEYS) + r")=)",
    re.IGNORECASE,
)


def _is_admin(telegram_id: int) -> bool:
    raw = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
    if not raw:
        return False
    try:
        return int(raw) == telegram_id
    except ValueError:
        logger.warning("ADMIN_TELEGRAM_ID is set but not an int: %r", raw)
        return False


def _admin_chat_id() -> int | None:
    raw = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_filter_kv(text: str, errors: list[str]) -> dict:
    """Parse `key=v1,v2 key=v1,v2 ...` text. Values may contain spaces
    (we split on whitespace only when immediately followed by a known key=).
    Errors are appended in-place; the return value is the filters dict.
    """
    text = text.strip()
    if not text:
        return {}

    chunks = [c.strip() for c in _APPROVA_SPLITTER.split(text) if c.strip()]
    filters: dict[str, Any] = {}
    notifica_tutto = False

    for chunk in chunks:
        if "=" not in chunk:
            errors.append(f"parametro non riconosciuto: {chunk!r}")
            continue
        key, raw_val = chunk.split("=", 1)
        key = key.strip().lower()
        raw_val = raw_val.strip()
        if key not in APPROVA_KEYS:
            errors.append(f"chiave sconosciuta: {key!r}")
            continue
        if key == "tutto":
            if raw_val.lower() in ("si", "sì", "true", "1"):
                notifica_tutto = True
            elif raw_val.lower() in ("no", "false", "0", ""):
                pass
            else:
                errors.append(f"valore tutto non valido: {raw_val!r}")
        else:
            values = [v.strip() for v in raw_val.split(",") if v.strip()]
            if values:
                filters[key] = values

    if notifica_tutto:
        return {"notifica_tutto": True}
    return filters


def _parse_approva_command(args_str: str) -> tuple[int | None, dict, list[str]]:
    """Parse the text that follows the /approva command.

    Returns (telegram_id, filters_dict, errors). If `telegram_id` is None the
    parse failed; callers should surface `errors` to the admin.
    """
    errors: list[str] = []
    text = args_str.strip()
    if not text:
        return None, {}, [
            "Uso: /approva <telegram_id> [keywords=...] [regioni=...] "
            "[categorie=...] [settori=...] [tipo_procedura=...] [tutto=si]"
        ]

    parts = text.split(None, 1)
    tid_str = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    try:
        telegram_id = int(tid_str)
    except ValueError:
        return None, {}, [f"telegram_id non valido: {tid_str!r}"]

    filters = _parse_filter_kv(rest, errors)
    return telegram_id, filters, errors


def _parse_single_id(args_str: str, command_name: str) -> tuple[int | None, str | None]:
    """Parse a single telegram_id argument. Returns (id, error_message_or_None)."""
    text = args_str.strip()
    if not text:
        return None, f"Uso: /{command_name} <telegram_id>"
    parts = text.split()
    try:
        return int(parts[0]), None
    except ValueError:
        return None, f"telegram_id non valido: {parts[0]!r}"


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


def _format_approva_summary(name: str, telegram_id: int, filters: dict) -> str:
    lines = [f"✅ Utente {name} ({telegram_id}) attivato."]
    if filters.get("notifica_tutto"):
        lines.append("Notifica tutto: attivo (riceve ogni offerta).")
        return "\n".join(lines)
    for key, label in _FILTER_LABELS.items():
        values = filters.get(key)
        if values:
            lines.append(f"{label}: {', '.join(values)}")
    if len(lines) == 1:
        lines.append("Nessun filtro impostato — riceverà tutte le offerte nuove.")
    return "\n".join(lines)


async def _get_user(telegram_id: int) -> dict | None:
    users = await asyncio.to_thread(db.get_all_users)
    return next((u for u in users if u["telegram_id"] == telegram_id), None)


async def _notify_admin(bot, text: str) -> None:
    chat_id = _admin_chat_id()
    if chat_id is None:
        logger.warning("ADMIN_TELEGRAM_ID not set; cannot notify admin: %s", text)
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except TelegramError as exc:
        logger.error("Failed to notify admin (%s): %s", chat_id, exc)


async def _notify_user(bot, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except TelegramError as exc:
        logger.error("Failed to notify user %s: %s", telegram_id, exc)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    tg_user = update.effective_user
    telegram_id = tg_user.id
    name = tg_user.full_name or tg_user.first_name or "Friend"

    existing = await _get_user(telegram_id)
    if existing is None:
        await asyncio.to_thread(
            db.upsert_user, telegram_id, name, {}, status="pending"
        )
        await update.message.reply_text(PENDING_TEXT)
        await _notify_admin(
            context.bot,
            (
                "👤 Nuovo utente in attesa di attivazione:\n"
                f"Nome: {name}\n"
                f"ID: {telegram_id}\n\n"
                "Usa /approva per attivarlo."
            ),
        )
        logger.info("Registered new pending user: %s (%s)", telegram_id, name)
        return

    if existing.get("status") == "pending":
        await update.message.reply_text(
            "Sei già registrato e in attesa di attivazione da parte "
            "dell'amministratore."
        )
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
            "Non hai ancora un profilo. Usa /start per registrarti."
        )
        return

    if user.get("status") == "pending":
        await update.message.reply_text(
            "Il tuo profilo è in attesa di attivazione da parte dell'amministratore."
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
            "Non hai un profilo. Usa /start per registrarti."
        )
        return

    if user.get("status") == "pending":
        await update.message.reply_text(
            "Il tuo profilo è in attesa di attivazione."
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

    pending = [u for u in users if u.get("status") == "pending"]
    active = [u for u in users if u.get("status") != "pending"]

    lines = [
        f"<b>Utenti registrati ({len(users)}):</b> "
        f"{len(pending)} in attesa, {len(active)} attivi",
        "",
    ]
    if pending:
        lines.append("<b>In attesa di attivazione:</b>")
        for user in pending:
            name = html.escape(str(user.get("name") or ""))
            lines.append(f"• <code>{user['telegram_id']}</code> {name}")
        lines.append("")
    if active:
        lines.append("<b>Attivi:</b>")
        for user in active:
            name = html.escape(str(user.get("name") or ""))
            summary = html.escape(_summarise_filters(user.get("filters")))
            lines.append(f"• <code>{user['telegram_id']}</code> {name} — {summary}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def approva_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Comando riservato all'amministratore.")
        return

    text = update.message.text or ""
    parts = text.split(None, 1)
    args_str = parts[1] if len(parts) > 1 else ""

    telegram_id, filters, errors = _parse_approva_command(args_str)
    if telegram_id is None or errors:
        msg = "Errore nei parametri:\n" + "\n".join(f"- {e}" for e in errors)
        await update.message.reply_text(msg)
        return

    target = await _get_user(telegram_id)
    if target is None:
        await update.message.reply_text(
            f"Utente {telegram_id} non trovato. Deve usare /start prima."
        )
        return

    await asyncio.to_thread(
        db.upsert_user, telegram_id, target["name"], filters, status="active"
    )
    logger.info(
        "Admin activated user %s (%s) with filters=%s",
        telegram_id, target["name"], filters,
    )
    await update.message.reply_text(
        _format_approva_summary(target["name"], telegram_id, filters)
    )
    await _notify_user(context.bot, telegram_id, ACTIVATED_TEXT)


async def revoca_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Comando riservato all'amministratore.")
        return

    text = update.message.text or ""
    parts = text.split(None, 1)
    args_str = parts[1] if len(parts) > 1 else ""

    telegram_id, error = _parse_single_id(args_str, "revoca")
    if telegram_id is None:
        await update.message.reply_text(error or "Uso: /revoca <telegram_id>")
        return

    target = await _get_user(telegram_id)
    if target is None:
        await update.message.reply_text(f"Utente {telegram_id} non trovato.")
        return

    await asyncio.to_thread(
        db.upsert_user, telegram_id, target["name"], {}, status="pending"
    )
    logger.info("Admin revoked user %s (%s)", telegram_id, target["name"])
    await update.message.reply_text(
        f"✅ Utente {target['name']} ({telegram_id}) revocato. "
        "Non riceverà più notifiche fino a una nuova attivazione."
    )


def build_application(token: str) -> Application:
    """Wire all command handlers onto a fresh Application."""
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("profilo", profilo_handler))
    application.add_handler(CommandHandler("offerte", offerte_handler))
    application.add_handler(CommandHandler("utenti", utenti_handler))
    application.add_handler(CommandHandler("approva", approva_handler))
    application.add_handler(CommandHandler("revoca", revoca_handler))
    return application
