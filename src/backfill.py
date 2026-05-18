"""One-shot digest backfill of all currently-open inPA offers.

Run with `python -m src.backfill [--dry-run]`. Designed to be invoked
manually (typically via `docker compose exec`) when a new user is enrolled
and we want to give them a one-time view of relevant *already-open* offers
without spamming them with one notification per match.

For every enrolled user:
- Compute matches against every open offer fetched from inPA.
- Send ONE digest Telegram message listing up to 20 matches (with a
  "+N altri" footer if there are more).
- Record every fetched offer in `seen_offers` with `source='backfill'`
  for EVERY enrolled user — so a future audit can tell which offers a
  user has been exposed to vs which they actually received notifications
  for.

In `--dry-run` mode no Telegram messages are sent and no DB writes occur;
the script just prints per-user match counts to stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import logging
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

from src import db, matcher, scraper

logger = logging.getLogger("inpa-backfill")

DIGEST_MAX_ITEMS = 20
# Telegram messages are capped at 4096 chars. We leave headroom for the
# header and a potential footer; lines beyond this budget overflow into
# the "+ N altri" tail instead of blowing the send.
DIGEST_TEXT_BUDGET = 3700
DIGEST_TITOLO_MAX = 100
DIGEST_ENTE_MAX = 50


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _format_date_ddmmyyyy(raw: object) -> str:
    if not raw:
        return "—"
    text = str(raw)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _build_digest(matches: list[dict]) -> str:
    total = len(matches)
    header = (
        "📋 <b>Offerte aperte che corrispondono al tuo profilo</b>\n"
        f"Trovate {total} offerte attualmente aperte. Ecco le più recenti:\n\n"
    )
    lines: list[str] = []
    for index, offer in enumerate(matches[:DIGEST_MAX_ITEMS], start=1):
        titolo = html.escape(_truncate(str(offer.get("titolo") or "—"), DIGEST_TITOLO_MAX))
        ente = html.escape(_truncate(str(offer.get("entiRiferimento") or "—"), DIGEST_ENTE_MAX))
        scadenza = html.escape(_format_date_ddmmyyyy(offer.get("dataScadenza")))
        url = scraper.detail_url(offer["id"])
        line = f"{index}. <a href=\"{url}\">{titolo}</a> — {ente} — Scadenza {scadenza}"
        # Stop accumulating if the next line would push us over Telegram's 4096-char
        # ceiling. The excess matches roll into the "+ N altri" footer.
        candidate_body = "\n".join(lines + [line])
        if len(header) + len(candidate_body) > DIGEST_TEXT_BUDGET:
            break
        lines.append(line)
    shown = len(lines)
    body = "\n".join(lines)
    footer = ""
    if total > shown:
        remaining = total - shown
        footer = (
            f"\n\n+ {remaining} altri risultati. "
            "Usa /offerte per vedere le tue opportunità."
        )
    return header + body + footer


async def _send_digest(bot: Bot, telegram_id: int, text: str) -> bool:
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except TelegramError as exc:
        logger.error("Digest send failed for user %s: %s", telegram_id, exc)
        return False


async def run(dry_run: bool) -> None:
    load_dotenv()
    _configure_logging()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token and not dry_run:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (required when --dry-run is off)")

    db.init_db()
    users = db.get_all_users()
    logger.info(
        "Backfill starting (dry_run=%s); %d enrolled user(s)", dry_run, len(users)
    )

    per_user_matches: dict[int, list[dict]] = defaultdict(list)
    seen_offer_ids: list[str] = []
    total_fetched = 0
    total_saved = 0

    for offer in scraper.fetch_all_open_offers():
        total_fetched += 1
        offer_id = offer.get("id")
        if offer_id is None:
            logger.warning("Skipping offer without an id: %r", offer)
            continue
        if not dry_run:
            was_new = db.is_new_offer(offer_id)
            db.save_offer(offer)
            if was_new:
                total_saved += 1
        seen_offer_ids.append(str(offer_id))
        for user in matcher.get_matching_users(offer, users):
            per_user_matches[user["telegram_id"]].append(offer)

    logger.info(
        "Fetch complete: %d offers fetched, %d newly saved", total_fetched, total_saved
    )
    for user in users:
        match_count = len(per_user_matches.get(user["telegram_id"], []))
        logger.info(
            "User %s (%s): %d match(es)",
            user["telegram_id"], user["name"], match_count,
        )

    if dry_run:
        logger.info("Dry-run complete: no DB writes, no Telegram messages sent")
        return

    # Record every fetched offer as 'seen' for every enrolled user, so a future
    # tightening of the per-user dedup logic doesn't replay this batch.
    logger.info(
        "Recording %d offer×user pair(s) as seen (source='backfill')",
        len(seen_offer_ids) * len(users),
    )
    for offer_id in seen_offer_ids:
        for user in users:
            db.mark_seen_without_notify(offer_id, user["telegram_id"])

    digests_sent = 0
    async with Bot(token=token) as bot:
        for user in users:
            matches = per_user_matches.get(user["telegram_id"], [])
            if not matches:
                continue
            text = _build_digest(matches)
            if await _send_digest(bot, user["telegram_id"], text):
                digests_sent += 1
    logger.info(
        "Backfill done: %d digest message(s) sent to %d user(s) with matches",
        digests_sent,
        sum(1 for u in users if per_user_matches.get(u["telegram_id"])),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="inPA open-offer backfill digest"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and match only; no DB writes, no Telegram messages",
    )
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
