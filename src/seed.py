"""Seed a fresh database with the offers already on inPA, without notifying anyone.

Run once, before the scheduler's first poll, on a new install:

    python -m src.seed            # saves every currently open offer, plus page 0
    python -m src.seed --dry-run  # fetch and count only; no DB writes

A fresh DB has no known offers, so the scheduler's cold start would treat
page 0 as new. After seeding, the scheduler's `since_id` is the newest offer
already published, and only offers published afterwards count as new. No
Telegram message is sent. Users enrolled later (``/start`` + ``/approva``)
can get a one-time digest of open offers with ``python -m src.backfill``.

``seen_offers`` (per user) is left empty: there are no users yet, and
"new" is decided by the ``offers`` table.
"""

from __future__ import annotations

import argparse
import sys

from src import db, runtime, scraper


def seed(dry_run: bool = False) -> tuple:
    """Fetch open offers and page 0; save them. Returns (fetched, newly_saved)."""
    offers = {}
    for offer in scraper.fetch_all_open_offers():
        offers[str(offer["id"])] = offer
    # page 0 of the unfiltered listing is what the scheduler polls; it can hold
    # offers that are not OPEN (future or just closed).
    for offer in scraper.fetch_new_offers(None):
        offers.setdefault(str(offer["id"]), offer)

    saved = 0
    if not dry_run:
        for offer_id, offer in offers.items():
            if db.is_new_offer(offer_id):
                db.save_offer(offer)
                saved += 1
    return len(offers), saved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.seed", description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and count only")
    args = parser.parse_args(argv)

    logger = runtime.configure("inpa-seed")
    db.init_db()
    users = db.get_all_users()
    if users and not args.dry_run:
        logger.warning("DB already has %d user(s); seeding marks offers known without notifying them",
                       len(users))
    fetched, saved = seed(dry_run=args.dry_run)
    latest = db.get_latest_offer_id()
    logger.info("Seed %s: fetched=%d saved=%d latest_offer_id=%s",
                "dry run" if args.dry_run else "done", fetched, saved, latest)
    return 0 if fetched else 1


if __name__ == "__main__":
    sys.exit(main())
