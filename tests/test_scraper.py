from __future__ import annotations

import pytest
import requests
import responses

from src import scraper

SEARCH_URL = scraper.BASE_URL + scraper.SEARCH_PATH
CATEGORIE_URL = scraper.BASE_URL + scraper.CATEGORIE_PATH


def _make_offer(offer_id: str, **overrides) -> dict:
    """Return a minimally-populated raw offer object with sensible defaults."""
    base = {
        "id": offer_id,
        "codice": f"CODE-{offer_id}",
        "titolo": f"Concorso {offer_id}",
        "figuraRicercata": "Funzionario amministrativo",
        "descrizioneBreve": "Short description",
        "entiRiferimento": [{"denominazione": "Ente A"}, {"denominazione": "Ente B"}],
        "sedi": [{"descrizione": "Roma"}, {"descrizione": "Milano"}],
        "categorie": ["Categoria 1", "Categoria 2"],
        "settori": [{"label": "Settore X"}],
        "tipoProcedura": {"descrizione": "Pubblico"},
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


def _page(offers: list[dict]) -> dict:
    return {"content": offers, "totalElements": len(offers), "totalPages": 1}


@responses.activate
def test_extract_offer_joins_arrays_and_preserves_scalars():
    responses.add(
        responses.GET,
        SEARCH_URL,
        json=_page([_make_offer("42")]),
        status=200,
    )

    result = scraper.fetch_new_offers(since_id=None)

    assert len(result) == 1
    offer = result[0]
    assert offer["id"] == "42"
    assert offer["codice"] == "CODE-42"
    assert offer["titolo"] == "Concorso 42"
    assert offer["entiRiferimento"] == "Ente A, Ente B"
    assert offer["sedi"] == "Roma, Milano"
    assert offer["categorie"] == "Categoria 1, Categoria 2"
    assert offer["settori"] == "Settore X"
    assert offer["tipoProcedura"] == "Pubblico"
    assert offer["calculatedStatus"] == "OPEN"
    assert offer["numPosti"] == 5
    assert offer["salaryMin"] == 25000
    assert offer["salaryMax"] == 35000
    assert offer["allegatoMediaId"] == "media-123"
    assert offer["linkReindirizzamento"] is None


@responses.activate
def test_cold_start_fetches_only_page_zero():
    """When since_id is None, scraper must stop after page 0 even if more pages exist."""
    responses.add(
        responses.GET,
        SEARCH_URL,
        json=_page([_make_offer("100"), _make_offer("99")]),
        status=200,
    )

    result = scraper.fetch_new_offers(since_id=None)

    assert [o["id"] for o in result] == ["100", "99"]
    # Exactly one request made — no pagination on cold start.
    assert len(responses.calls) == 1
    assert "page=0" in responses.calls[0].request.url


@responses.activate
def test_pagination_stops_on_known_id_mid_page():
    """When a known id appears in the middle of a page, return only offers above it."""
    page_0 = _page([_make_offer("50"), _make_offer("49"), _make_offer("KNOWN")])
    responses.add(responses.GET, SEARCH_URL, json=page_0, status=200)

    result = scraper.fetch_new_offers(since_id="KNOWN")

    assert [o["id"] for o in result] == ["50", "49"]
    # Pagination must stop on page 0 — only one HTTP call.
    assert len(responses.calls) == 1


@responses.activate
def test_pagination_crosses_pages_until_known_id():
    """Walks multiple pages, accumulating, until since_id is encountered."""
    page_0 = _page([_make_offer("50"), _make_offer("49")])
    page_1 = _page([_make_offer("48"), _make_offer("KNOWN"), _make_offer("46")])

    # responses matches by URL prefix; the two GET stubs are served in order.
    responses.add(responses.GET, SEARCH_URL, json=page_0, status=200)
    responses.add(responses.GET, SEARCH_URL, json=page_1, status=200)

    result = scraper.fetch_new_offers(since_id="KNOWN")

    assert [o["id"] for o in result] == ["50", "49", "48"]
    assert len(responses.calls) == 2
    assert "page=0" in responses.calls[0].request.url
    assert "page=1" in responses.calls[1].request.url


@responses.activate
def test_pagination_stops_on_empty_page():
    """If a page comes back empty, scraping ends gracefully without hitting max_pages."""
    page_0 = _page([_make_offer("10"), _make_offer("9")])
    page_1 = _page([])
    responses.add(responses.GET, SEARCH_URL, json=page_0, status=200)
    responses.add(responses.GET, SEARCH_URL, json=page_1, status=200)

    result = scraper.fetch_new_offers(since_id="NEVER_SEEN")

    assert [o["id"] for o in result] == ["10", "9"]
    assert len(responses.calls) == 2


@responses.activate
def test_pagination_respects_max_pages_cap():
    """Without a known-id match, we stop at max_pages instead of running forever."""
    page = _page([_make_offer("a"), _make_offer("b")])
    # Stub the same response repeatedly so the scraper can loop indefinitely if it wanted to.
    for _ in range(10):
        responses.add(responses.GET, SEARCH_URL, json=page, status=200)

    result = scraper.fetch_new_offers(since_id="NEVER", max_pages=3)

    assert len(responses.calls) == 3
    # Each page has 2 offers, none match since_id → all collected.
    assert len(result) == 6


@responses.activate
def test_non_200_raises():
    responses.add(responses.GET, SEARCH_URL, json={"error": "boom"}, status=500)

    with pytest.raises(requests.HTTPError):
        scraper.fetch_new_offers(since_id=None)


@responses.activate
def test_request_exception_propagates():
    responses.add(
        responses.GET,
        SEARCH_URL,
        body=requests.ConnectionError("connection reset"),
    )

    with pytest.raises(requests.ConnectionError):
        scraper.fetch_new_offers(since_id=None)


@responses.activate
def test_fetch_categories_handles_list_response():
    responses.add(
        responses.GET,
        CATEGORIE_URL,
        json=[{"id": 1, "descrizione": "Cat A"}, {"id": 2, "descrizione": "Cat B"}],
        status=200,
    )

    result = scraper.fetch_categories()

    assert len(result) == 2
    assert result[0]["descrizione"] == "Cat A"


@responses.activate
def test_fetch_categories_handles_wrapped_response():
    responses.add(
        responses.GET,
        CATEGORIE_URL,
        json={"content": [{"id": 1, "descrizione": "Cat A"}]},
        status=200,
    )

    result = scraper.fetch_categories()

    assert len(result) == 1


def test_detail_url_builds_concorso_link():
    url = scraper.detail_url("42")
    assert url == (
        "https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/"
        "?concorso_id=42"
    )
