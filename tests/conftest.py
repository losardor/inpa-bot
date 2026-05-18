from __future__ import annotations

import pytest

from src import db as db_module


@pytest.fixture
def db():
    """Fresh in-memory SQLite DB for each test. Yields the db module itself."""
    db_module.init_db(":memory:")
    try:
        yield db_module
    finally:
        db_module.close_db()


def make_offer(offer_id: str, **overrides) -> dict:
    """Storage-shaped offer dict (camelCase keys, arrays already joined)."""
    base = {
        "id": offer_id,
        "codice": f"CODE-{offer_id}",
        "titolo": f"Concorso {offer_id}",
        "figuraRicercata": "Funzionario amministrativo",
        "descrizioneBreve": "Short description",
        "entiRiferimento": "Ente A, Ente B",
        "sedi": "Roma, Milano",
        "categorie": "Categoria 1",
        "settori": "Settore X",
        "tipoProcedura": "Pubblico",
        "calculatedStatus": "OPEN",
        "dataPubblicazione": "2026-05-18",
        "dataScadenza": "2026-06-30",
        "numPosti": 5,
        "salaryMin": 25000,
        "salaryMax": 35000,
        "linkReindirizzamento": None,
        "allegatoMediaId": "media-123",
    }
    base.update(overrides)
    return base


@pytest.fixture
def offer_factory():
    return make_offer
