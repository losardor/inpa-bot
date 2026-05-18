from __future__ import annotations

from src import backfill


def _offer(offer_id: str, titolo: str = "Concorso X", ente: str = "Ente Y") -> dict:
    return {
        "id": offer_id,
        "titolo": titolo,
        "entiRiferimento": ente,
        "dataScadenza": "2026-06-30",
    }


def test_build_digest_under_telegram_length_limit_with_max_items():
    """Even with 20 long-titled offers the message must fit Telegram's 4096-char cap."""
    long_title = "AVVISO PUBBLICO MOBILITÀ VOLONTARIA " * 12  # ~430 chars before truncation
    matches = [_offer(f"id{i:032x}", titolo=long_title) for i in range(20)]

    msg = backfill._build_digest(matches)

    assert len(msg) <= 4096, f"digest is {len(msg)} chars"


def test_build_digest_truncates_titolo_with_ellipsis():
    matches = [_offer("a", titolo="x" * 500)]
    msg = backfill._build_digest(matches)
    # The line for the single offer should not contain the full 500-char title.
    assert "x" * 500 not in msg
    assert "…" in msg


def test_build_digest_footer_counts_remaining_when_truncated_by_budget():
    """If lines overflow the budget, the footer must account for *all* unshown items."""
    long_title = "AVVISO PUBBLICO MOBILITÀ VOLONTARIA " * 12
    matches = [_offer(f"id{i:032x}", titolo=long_title) for i in range(30)]

    msg = backfill._build_digest(matches)

    # 30 total, but the budget may have forced fewer than 20 to be shown.
    # The footer must mention "+ N altri" where N covers everything not in the body.
    assert "altri risultati" in msg
    assert "/offerte" in msg
    # Sanity: still under the Telegram cap.
    assert len(msg) <= 4096


def test_build_digest_no_footer_when_all_fit():
    matches = [_offer("1", titolo="Breve")]
    msg = backfill._build_digest(matches)
    assert "altri risultati" not in msg
    assert "Trovate 1 offerte" in msg


def test_build_digest_caps_at_max_items_even_under_budget():
    """If a user has 100 short matches, we still only show DIGEST_MAX_ITEMS=20."""
    matches = [_offer(f"id{i:032x}", titolo="t") for i in range(100)]
    msg = backfill._build_digest(matches)

    # Body lines start with "N. " — count them.
    body_lines = [
        line for line in msg.splitlines()
        if line and line[0].isdigit() and ". " in line[:4]
    ]
    assert len(body_lines) <= backfill.DIGEST_MAX_ITEMS
    assert "+ 80 altri risultati" in msg
