"""inPA portal API client.

The public listings on inpa.gov.it are rendered client-side from a JSON
API on the `portale.inpa.gov.it` subdomain. See INFRASTRUCTURE.md →
"inPA portal recon" for the endpoint contract.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area"
SEARCH_PATH = "/search-better"
CATEGORIE_PATH = "/get-categorie"
SETTORI_PATH = "/get-settori"
REGIONS_PATH = "/find-all"

DETAIL_URL_TEMPLATE = (
    "https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/"
    "?concorso_id={offer_id}"
)

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_PAGE_SIZE = 20
DEFAULT_MAX_PAGES = 50

SCALAR_FIELDS: tuple[str, ...] = (
    "id",
    "codice",
    "titolo",
    "figuraRicercata",
    "descrizioneBreve",
    "tipoProcedura",
    "calculatedStatus",
    "dataPubblicazione",
    "dataScadenza",
    "numPosti",
    "salaryMin",
    "salaryMax",
    "linkReindirizzamento",
    "allegatoMediaId",
)

ARRAY_FIELDS: tuple[str, ...] = (
    "entiRiferimento",
    "sedi",
    "categorie",
    "settori",
)

_DISPLAY_KEYS = ("descrizione", "denominazione", "label", "name", "nome", "id")


def detail_url(offer_id: str | int) -> str:
    return DETAIL_URL_TEMPLATE.format(offer_id=offer_id)


def _display_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in _DISPLAY_KEYS:
            inner = value.get(key)
            if inner not in (None, ""):
                return str(inner)
        return str(value)
    return str(value)


def _join_array(values: Any) -> str:
    if not values:
        return ""
    if not isinstance(values, list):
        return _display_value(values) or ""
    parts = []
    for item in values:
        text = _display_value(item)
        if text:
            parts.append(text)
    return ", ".join(parts)


def _extract_offer(item: dict) -> dict:
    out: dict[str, Any] = {}
    for field in SCALAR_FIELDS:
        raw = item.get(field)
        if isinstance(raw, dict):
            out[field] = _display_value(raw)
        elif isinstance(raw, list):
            out[field] = _join_array(raw)
        else:
            out[field] = raw
    for field in ARRAY_FIELDS:
        out[field] = _join_array(item.get(field))
    return out


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: Any = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    url = BASE_URL + path
    try:
        response = requests.request(method, url, params=params, json=json, timeout=timeout)
    except requests.RequestException as exc:
        logger.error(
            "inPA request failed: %s %s params=%s — %s", method, url, params, exc
        )
        raise
    if response.status_code != 200:
        logger.error(
            "inPA returned non-200: %s %s params=%s -> %s body=%r",
            method, url, params, response.status_code, response.text[:200],
        )
        response.raise_for_status()
    return response.json()


def _get(path: str, params: dict | None = None, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    return _request("GET", path, params=params, timeout=timeout)


def _post(
    path: str,
    params: dict | None = None,
    *,
    json: Any = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    return _request("POST", path, params=params, json=json, timeout=timeout)


def _items_from_payload(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("content", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def fetch_new_offers(
    since_id: str | None,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> list[dict]:
    """Fetch offers newer than `since_id`, newest first.

    Iterates `search-better` starting at page 0 and stops as soon as the offer
    whose `id` matches `since_id` is encountered (that offer is *not* included).

    On cold start (`since_id is None`) only page 0 is fetched, so the bot does
    not flood users with the historical backlog — operators can backfill later
    if they want to.
    """
    collected: list[dict] = []

    if since_id is None:
        payload = _post(SEARCH_PATH, params={"page": 0, "size": page_size}, json={})
        items = _items_from_payload(payload)
        for raw in items:
            collected.append(_extract_offer(raw))
        logger.info("Cold start: collected %d offers from page 0", len(collected))
        return collected

    for page in range(max_pages):
        payload = _post(SEARCH_PATH, params={"page": page, "size": page_size}, json={})
        items = _items_from_payload(payload)
        if not items:
            logger.info("Empty page %d; stopping pagination", page)
            return collected
        for raw in items:
            if str(raw.get("id")) == str(since_id):
                logger.info(
                    "Hit known offer id %s on page %d (after %d new offers)",
                    since_id, page, len(collected),
                )
                return collected
            collected.append(_extract_offer(raw))

    logger.warning(
        "Reached max_pages=%d without finding since_id=%s; stopping to avoid runaway",
        max_pages, since_id,
    )
    return collected


def fetch_all_open_offers(
    max_pages: int = 200,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterator[dict]:
    """Yield every currently-open inPA offer, newest first.

    Uses the `{"status": ["OPEN"]}` body filter (~1.9k offers, vs ~67k unfiltered).
    Yields one storage-shaped offer dict at a time so memory stays flat even on
    the 1 GB server. `max_pages` is a safety cap; raise it cautiously.
    """
    total_pages: int | None = None
    yielded = 0
    for page in range(max_pages):
        payload = _post(
            SEARCH_PATH,
            params={"page": page, "size": page_size},
            json={"status": ["OPEN"]},
        )
        if total_pages is None and isinstance(payload, dict):
            tp = payload.get("totalPages")
            if isinstance(tp, int):
                total_pages = tp
        items = _items_from_payload(payload)
        if not items:
            logger.info("Backfill: empty page %d; stopping after %d offers", page, yielded)
            return
        for raw in items:
            yield _extract_offer(raw)
            yielded += 1
        if (page + 1) % 10 == 0:
            logger.info(
                "Backfill progress: page %d/%s, %d offers so far",
                page + 1, total_pages if total_pages is not None else "?", yielded,
            )
    logger.warning(
        "Backfill hit max_pages=%d (yielded %d); raise the cap if the dataset has grown",
        max_pages, yielded,
    )


def _fetch_reference(path: str) -> list:
    payload = _get(path)
    if isinstance(payload, list):
        return payload
    return _items_from_payload(payload)


def fetch_categories() -> list:
    return _fetch_reference(CATEGORIE_PATH)


def fetch_sectors() -> list:
    return _fetch_reference(SETTORI_PATH)


def fetch_regions() -> list:
    return _fetch_reference(REGIONS_PATH)
