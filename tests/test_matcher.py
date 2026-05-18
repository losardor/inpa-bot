from __future__ import annotations

from src.matcher import get_matching_users


def _offer(**overrides) -> dict:
    """Camel-case offer dict (the shape produced by the scraper)."""
    base = {
        "id": "1",
        "titolo": "Concorso per Dirigente",
        "figuraRicercata": "Funzionario amministrativo",
        "descrizioneBreve": "Bando per esperto IT",
        "sedi": "Roma, Lazio",
        "categorie": "Categoria A",
        "settori": "Informatica",
        "tipoProcedura": "Pubblica",
    }
    base.update(overrides)
    return base


def _user(filters: dict | None = None, telegram_id: int = 1, name: str = "U") -> dict:
    return {"telegram_id": telegram_id, "name": name, "filters": filters or {}}


def test_notifica_tutto_bypasses_all_filters():
    """notifica_tutto=True matches even when other filters would exclude."""
    user = _user({
        "notifica_tutto": True,
        "keywords": ["NONEXISTENT"],
        "regioni": ["Sicilia"],
    })
    matches = get_matching_users(_offer(), [user])
    assert matches == [user]


def test_keyword_match_in_titolo_case_insensitive():
    user = _user({"keywords": ["DIRIGENTE"]})
    matches = get_matching_users(_offer(titolo="Concorso per Dirigente"), [user])
    assert len(matches) == 1


def test_keyword_match_in_figura_ricercata():
    user = _user({"keywords": ["funzionario"]})
    matches = get_matching_users(
        _offer(titolo="X", descrizioneBreve="Y", figuraRicercata="Funzionario IT"),
        [user],
    )
    assert len(matches) == 1


def test_keyword_match_in_descrizione_breve():
    user = _user({"keywords": ["esperto"]})
    matches = get_matching_users(
        _offer(titolo="X", figuraRicercata="Y", descrizioneBreve="Cerchiamo esperto IT"),
        [user],
    )
    assert len(matches) == 1


def test_keyword_miss():
    user = _user({"keywords": ["medico"]})
    matches = get_matching_users(_offer(), [user])
    assert matches == []


def test_keyword_OR_within_dimension():
    """At least one keyword needs to match — not all."""
    user = _user({"keywords": ["medico", "dirigente"]})
    matches = get_matching_users(_offer(titolo="Concorso per Dirigente"), [user])
    assert len(matches) == 1


def test_region_filter_match():
    user = _user({"regioni": ["Lazio"]})
    matches = get_matching_users(_offer(sedi="Roma, Lazio"), [user])
    assert len(matches) == 1


def test_region_filter_miss():
    user = _user({"regioni": ["Sicilia"]})
    matches = get_matching_users(_offer(sedi="Roma, Lazio"), [user])
    assert matches == []


def test_categorie_filter():
    user = _user({"categorie": ["Categoria B"]})
    assert get_matching_users(_offer(categorie="Categoria A"), [user]) == []
    assert get_matching_users(_offer(categorie="Categoria A, Categoria B"), [user]) == [user]


def test_settori_filter():
    user = _user({"settori": ["Informatica"]})
    assert get_matching_users(_offer(settori="Informatica"), [user]) == [user]
    assert get_matching_users(_offer(settori="Edilizia"), [user]) == []


def test_tipo_procedura_filter():
    user = _user({"tipo_procedura": ["Pubblica"]})
    assert get_matching_users(_offer(tipoProcedura="Pubblica"), [user]) == [user]
    assert get_matching_users(_offer(tipoProcedura="Riservata"), [user]) == []


def test_multi_dimension_filters_AND_together_all_match():
    user = _user({
        "keywords": ["dirigente"],
        "regioni": ["Lazio"],
        "settori": ["Informatica"],
    })
    matches = get_matching_users(
        _offer(
            titolo="Dirigente IT",
            sedi="Roma, Lazio",
            settori="Informatica",
        ),
        [user],
    )
    assert len(matches) == 1


def test_multi_dimension_filters_one_miss_excludes():
    user = _user({
        "keywords": ["dirigente"],
        "regioni": ["Lazio"],
        "settori": ["Edilizia"],  # offer has Informatica → miss
    })
    matches = get_matching_users(
        _offer(titolo="Dirigente IT", sedi="Roma, Lazio", settori="Informatica"),
        [user],
    )
    assert matches == []


def test_empty_filters_dict_matches_everything():
    user = _user({})
    matches = get_matching_users(_offer(), [user])
    assert matches == [user]


def test_empty_array_dimensions_do_not_constrain():
    """A user with keys present but empty arrays is equivalent to no filters."""
    user = _user({"keywords": [], "regioni": [], "categorie": []})
    matches = get_matching_users(_offer(), [user])
    assert matches == [user]


def test_user_with_no_filters_attr_matches_everything():
    user = {"telegram_id": 1, "name": "X", "filters": None}
    matches = get_matching_users(_offer(), [user])
    assert matches == [user]


def test_multiple_users_only_matchers_returned():
    matching = _user({"keywords": ["dirigente"]}, telegram_id=1, name="A")
    non_matching = _user({"keywords": ["medico"]}, telegram_id=2, name="B")
    notify_all = _user({"notifica_tutto": True}, telegram_id=3, name="C")
    empty = _user({}, telegram_id=4, name="D")

    matches = get_matching_users(
        _offer(titolo="Concorso per Dirigente"),
        [matching, non_matching, notify_all, empty],
    )
    assert [u["telegram_id"] for u in matches] == [1, 3, 4]


def test_filters_with_only_notifica_tutto_false_still_applies_other_filters():
    """notifica_tutto=False is the default; other filters still apply."""
    user = _user({"notifica_tutto": False, "keywords": ["medico"]})
    assert get_matching_users(_offer(titolo="Dirigente"), [user]) == []
