from __future__ import annotations

from src import scraper, seed


def test_seed_saves_open_and_page0_without_duplicates(db, offer_factory, monkeypatch):
    open_offers = [offer_factory("3", dataPubblicazione="2026-11-26"),
                   offer_factory("2", dataPubblicazione="2026-11-25")]
    page0 = [offer_factory("4", dataPubblicazione="2026-11-27", calculatedStatus="FUTURE"),
             offer_factory("3", dataPubblicazione="2026-11-26")]
    monkeypatch.setattr(scraper, "fetch_all_open_offers", lambda: iter(open_offers))
    monkeypatch.setattr(scraper, "fetch_new_offers", lambda since_id: page0)

    assert seed.seed() == (3, 3)
    assert not db.is_new_offer("4") and not db.is_new_offer("2")
    assert db.get_latest_offer_id() == "4"
    # idempotent
    assert seed.seed() == (3, 0)


def test_seed_dry_run_writes_nothing(db, offer_factory, monkeypatch):
    monkeypatch.setattr(scraper, "fetch_all_open_offers", lambda: iter([offer_factory("9")]))
    monkeypatch.setattr(scraper, "fetch_new_offers", lambda since_id: [])
    assert seed.seed(dry_run=True) == (1, 0)
    assert db.is_new_offer("9")


def test_seed_sends_nothing(db, offer_factory, monkeypatch):
    """Seeding must not touch Telegram: no notifier or Bot use at all."""
    from src import notifier

    def boom(*a, **k):
        raise AssertionError("seed tried to notify")
    monkeypatch.setattr(notifier, "notify_user", boom)
    monkeypatch.setattr(scraper, "fetch_all_open_offers", lambda: iter([offer_factory("1")]))
    monkeypatch.setattr(scraper, "fetch_new_offers", lambda since_id: [offer_factory("1")])
    assert seed.seed() == (1, 1)
