"""SQLite persistence layer.

Three tables:
- `offers`     — every offer seen on inPA, keyed by inPA's stable `id`.
- `users`      — Telegram users we notify, with filter preferences as JSON.
- `seen_offers`— join table recording which (offer, user) pairs have been notified.

Connection is module-scoped: call `init_db()` once at startup. For tests,
call `init_db(":memory:")`.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

OFFER_FIELD_MAP: dict[str, str] = {
    "id": "id",
    "codice": "codice",
    "titolo": "titolo",
    "figuraRicercata": "figura_ricercata",
    "descrizioneBreve": "descrizione_breve",
    "entiRiferimento": "enti_riferimento",
    "sedi": "sedi",
    "categorie": "categorie",
    "settori": "settori",
    "tipoProcedura": "tipo_procedura",
    "calculatedStatus": "calculated_status",
    "dataPubblicazione": "data_pubblicazione",
    "dataScadenza": "data_scadenza",
    "numPosti": "num_posti",
    "salaryMin": "salary_min",
    "salaryMax": "salary_max",
    "linkReindirizzamento": "link_reindirizzamento",
    "allegatoMediaId": "allegato_media_id",
}

_REVERSE_OFFER_FIELD_MAP: dict[str, str] = {db: api for api, db in OFFER_FIELD_MAP.items()}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id                    TEXT PRIMARY KEY,
    codice                TEXT,
    titolo                TEXT,
    figura_ricercata      TEXT,
    descrizione_breve     TEXT,
    enti_riferimento      TEXT,
    sedi                  TEXT,
    categorie             TEXT,
    settori               TEXT,
    tipo_procedura        TEXT,
    calculated_status     TEXT,
    data_pubblicazione    TEXT,
    data_scadenza         TEXT,
    num_posti             INTEGER,
    salary_min            INTEGER,
    salary_max            INTEGER,
    link_reindirizzamento TEXT,
    allegato_media_id     TEXT,
    saved_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    filters     TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seen_offers (
    offer_id         TEXT    NOT NULL,
    user_telegram_id INTEGER NOT NULL,
    notified_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source           TEXT    NOT NULL DEFAULT 'notification',
    PRIMARY KEY (offer_id, user_telegram_id),
    FOREIGN KEY (offer_id)         REFERENCES offers(id),
    FOREIGN KEY (user_telegram_id) REFERENCES users(telegram_id)
);

CREATE INDEX IF NOT EXISTS idx_offers_data_pubblicazione
    ON offers (data_pubblicazione DESC);
"""

_connection: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _connection


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Open the SQLite connection and create the schema.

    `db_path` overrides the `DB_PATH` env var (useful for tests).
    """
    global _connection

    path = db_path if db_path is not None else os.environ.get("DB_PATH")
    if not path:
        raise RuntimeError("DB_PATH not set and no path passed to init_db()")

    logger.info("Opening SQLite database at %s", path)
    _connection = sqlite3.connect(path, check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA foreign_keys = ON")
    # WAL allows the scheduler and a parallel backfill/admin process to read+write
    # the same DB file concurrently (the scheduler keeps a long-lived connection).
    if path != ":memory:":
        _connection.execute("PRAGMA journal_mode = WAL")
    _connection.executescript(_SCHEMA)
    _migrate_schema(_connection)
    _connection.commit()
    return _connection


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive schema changes for databases that pre-date them."""
    seen_cols = {row["name"] for row in conn.execute("PRAGMA table_info(seen_offers)")}
    if "source" not in seen_cols:
        logger.info("Migrating seen_offers: adding 'source' column")
        conn.execute(
            "ALTER TABLE seen_offers ADD COLUMN source TEXT NOT NULL DEFAULT 'notification'"
        )
    user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "status" not in user_cols:
        logger.info("Migrating users: adding 'status' column (existing rows → 'active')")
        conn.execute(
            "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
        )


def close_db() -> None:
    """Close the connection. Primarily for tests; in production the process lives forever."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def is_new_offer(offer_id: str) -> bool:
    """Return True if this offer id has never been saved before."""
    row = _conn().execute(
        "SELECT 1 FROM offers WHERE id = ? LIMIT 1", (str(offer_id),)
    ).fetchone()
    return row is None


def save_offer(offer: dict) -> None:
    """Insert an offer in the scraper's shape (camelCase keys). Idempotent on `id`."""
    columns = list(OFFER_FIELD_MAP.values())
    values = [offer.get(api_key) for api_key in OFFER_FIELD_MAP.keys()]

    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(columns)
    sql = f"INSERT OR IGNORE INTO offers ({column_list}) VALUES ({placeholders})"

    with _conn():
        _conn().execute(sql, values)


def _row_to_user(row: sqlite3.Row) -> dict:
    return {
        "telegram_id": row["telegram_id"],
        "name": row["name"],
        "filters": json.loads(row["filters"]),
        "status": row["status"] if "status" in row.keys() else "active",
    }


def get_all_users() -> list[dict]:
    """Return every user (active + pending) with `filters` decoded from JSON."""
    rows = _conn().execute(
        "SELECT telegram_id, name, filters, status FROM users ORDER BY telegram_id"
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def get_users_for_notification() -> list[dict]:
    """Return only users with status='active' — the set eligible for notifications."""
    rows = _conn().execute(
        "SELECT telegram_id, name, filters, status FROM users "
        "WHERE status = 'active' ORDER BY telegram_id"
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def get_pending_users() -> list[dict]:
    """Return only users awaiting admin activation."""
    rows = _conn().execute(
        "SELECT telegram_id, name, filters, status FROM users "
        "WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def upsert_user(
    telegram_id: int,
    name: str,
    filters: dict[str, Any],
    *,
    status: str = "active",
) -> None:
    """Create or update a user. `filters` is stored as a JSON string.

    `status` defaults to 'active' for backward compatibility with callers that
    don't know about the column (e.g. older tests or admin enrolment via
    `upsert_user(..., status='active')`).
    """
    sql = """
    INSERT INTO users (telegram_id, name, filters, status)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
        name       = excluded.name,
        filters    = excluded.filters,
        status     = excluded.status,
        updated_at = CURRENT_TIMESTAMP
    """
    with _conn():
        _conn().execute(sql, (telegram_id, name, json.dumps(filters), status))


def set_user_status(telegram_id: int, status: str) -> None:
    """Toggle a user's status without touching name or filters."""
    with _conn():
        _conn().execute(
            "UPDATE users SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE telegram_id = ?",
            (status, telegram_id),
        )


def mark_seen(offer_id: str, user_telegram_id: int) -> None:
    """Record that we notified this user about this offer (source='notification')."""
    with _conn():
        _conn().execute(
            "INSERT OR IGNORE INTO seen_offers "
            "(offer_id, user_telegram_id, source) VALUES (?, ?, 'notification')",
            (str(offer_id), user_telegram_id),
        )


def mark_seen_without_notify(offer_id: str, user_telegram_id: int) -> None:
    """Record an (offer, user) pair without having actually sent a notification.

    Used by the backfill flow: offers already open when a user is enrolled should
    not generate per-offer notifications (the user gets a digest instead), but we
    still want a row so any future replay/audit logic can tell backfill-seen rows
    apart from notification-seen rows (`source='backfill'`).
    """
    with _conn():
        _conn().execute(
            "INSERT OR IGNORE INTO seen_offers "
            "(offer_id, user_telegram_id, source) VALUES (?, ?, 'backfill')",
            (str(offer_id), user_telegram_id),
        )


def _row_to_offer(row: sqlite3.Row) -> dict:
    """Convert a row from the `offers` table back into the camelCase shape
    produced by the scraper (so matcher/notifier can consume it uniformly)."""
    return {api_key: row[db_col] for db_col, api_key in _REVERSE_OFFER_FIELD_MAP.items()}


def get_recent_offers(limit: int = 50) -> list[dict]:
    """Return the most recent offers (camelCase shape), newest first."""
    rows = _conn().execute(
        "SELECT * FROM offers ORDER BY data_pubblicazione DESC, saved_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_offer(row) for row in rows]


def get_latest_offer_id() -> str | None:
    """Return the most-recent offer id known to the DB, or None if empty."""
    row = _conn().execute(
        "SELECT id FROM offers ORDER BY data_pubblicazione DESC, saved_at DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None
