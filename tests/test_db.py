from __future__ import annotations

import pytest

from src import db as db_module


def test_init_db_requires_path_when_env_missing(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    db_module.close_db()
    with pytest.raises(RuntimeError, match="DB_PATH"):
        db_module.init_db()


def test_init_db_creates_tables(db):
    rows = db._conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row["name"] for row in rows}
    assert {"offers", "users", "seen_offers"}.issubset(table_names)


def test_is_new_offer_true_before_save(db, offer_factory):
    assert db.is_new_offer("brand-new-id") is True


def test_save_offer_persists_all_fields(db, offer_factory):
    offer = offer_factory("42")
    db.save_offer(offer)

    row = db._conn().execute("SELECT * FROM offers WHERE id = ?", ("42",)).fetchone()
    assert row is not None
    assert row["codice"] == "CODE-42"
    assert row["titolo"] == "Concorso 42"
    assert row["figura_ricercata"] == "Funzionario amministrativo"
    assert row["enti_riferimento"] == "Ente A, Ente B"
    assert row["sedi"] == "Roma, Milano"
    assert row["num_posti"] == 5
    assert row["salary_min"] == 25000
    assert row["salary_max"] == 35000
    assert row["allegato_media_id"] == "media-123"


def test_dedup_is_new_offer_returns_false_after_save(db, offer_factory):
    offer = offer_factory("dedup-1")
    assert db.is_new_offer("dedup-1") is True
    db.save_offer(offer)
    assert db.is_new_offer("dedup-1") is False


def test_dedup_save_offer_twice_is_idempotent(db, offer_factory):
    db.save_offer(offer_factory("dup", titolo="First insert"))
    db.save_offer(offer_factory("dup", titolo="Second insert (ignored)"))

    rows = db._conn().execute(
        "SELECT titolo FROM offers WHERE id = ?", ("dup",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["titolo"] == "First insert"


def test_upsert_user_inserts_new(db):
    db.upsert_user(12345, "Alice", {"keywords": ["dirigente"], "region": "Lazio"})

    users = db.get_all_users()
    assert len(users) == 1
    assert users[0]["telegram_id"] == 12345
    assert users[0]["name"] == "Alice"
    assert users[0]["filters"] == {"keywords": ["dirigente"], "region": "Lazio"}


def test_upsert_user_updates_existing(db):
    db.upsert_user(1, "Alice", {"region": "Lazio"})
    db.upsert_user(1, "Alice Renamed", {"region": "Lombardia", "keywords": ["nuovo"]})

    users = db.get_all_users()
    assert len(users) == 1
    assert users[0]["name"] == "Alice Renamed"
    assert users[0]["filters"] == {"region": "Lombardia", "keywords": ["nuovo"]}


def test_get_all_users_returns_empty_list_when_none(db):
    assert db.get_all_users() == []


def test_get_all_users_orders_by_telegram_id(db):
    db.upsert_user(30, "C", {})
    db.upsert_user(10, "A", {})
    db.upsert_user(20, "B", {})

    users = db.get_all_users()
    assert [u["telegram_id"] for u in users] == [10, 20, 30]


def test_filters_roundtrip_as_json(db):
    complex_filters = {
        "keywords": ["dirigente", "funzionario"],
        "regions": ["Lazio", "Lombardia"],
        "min_salary": 30000,
        "active_only": True,
    }
    db.upsert_user(1, "Alice", complex_filters)

    users = db.get_all_users()
    assert users[0]["filters"] == complex_filters
