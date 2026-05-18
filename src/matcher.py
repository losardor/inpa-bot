"""Match offers against user filter profiles.

User filter schema (stored as JSON in `users.filters`):

    {
        "keywords":       [str, ...],   # OR'd; matched against titolo+figura+descrizione
        "regioni":        [str, ...],
        "categorie":      [str, ...],
        "settori":        [str, ...],
        "tipo_procedura": [str, ...],
        "notifica_tutto": bool          # if true, bypass all filters
    }

All array fields are optional (missing or empty = no constraint on that
dimension). Within a dimension, values are OR'd. Across dimensions, ANDed.
"""

from __future__ import annotations

from typing import Any

# User-filter key -> offer field (camelCase, as produced by the scraper).
# The offer's `sedi` field is the closest available proxy for "region".
_FILTER_TO_OFFER_FIELD: dict[str, str] = {
    "regioni": "sedi",
    "categorie": "categorie",
    "settori": "settori",
    "tipo_procedura": "tipoProcedura",
}

_KEYWORD_SEARCH_FIELDS = ("titolo", "figuraRicercata", "descrizioneBreve")


def _normalise_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _user_matches(filters: dict | None, offer: dict) -> bool:
    if not filters:
        return True
    if filters.get("notifica_tutto"):
        return True

    keywords = _normalise_list(filters.get("keywords"))
    if keywords:
        haystack = " ".join(
            str(offer.get(field) or "") for field in _KEYWORD_SEARCH_FIELDS
        ).lower()
        if not any(kw.lower() in haystack for kw in keywords):
            return False

    for filter_key, offer_field in _FILTER_TO_OFFER_FIELD.items():
        wanted = _normalise_list(filters.get(filter_key))
        if not wanted:
            continue
        haystack = str(offer.get(offer_field) or "").lower()
        if not any(value.lower() in haystack for value in wanted):
            return False

    return True


def get_matching_users(offer: dict, users: list[dict]) -> list[dict]:
    """Return the subset of `users` whose filters match this `offer`.

    `users` is the shape returned by `db.get_all_users()` — each item carries
    `telegram_id`, `name`, and `filters` (a dict).
    """
    return [user for user in users if _user_matches(user.get("filters"), offer)]
