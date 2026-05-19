from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import bot


# ----- pure parser tests -------------------------------------------------

def test_parse_approva_no_args():
    tid, filters, errors = bot._parse_approva_command("")
    assert tid is None
    assert filters == {}
    assert errors and "Uso:" in errors[0]


def test_parse_approva_invalid_telegram_id():
    tid, filters, errors = bot._parse_approva_command("nonnumeric keywords=a")
    assert tid is None
    assert any("telegram_id non valido" in e for e in errors)


def test_parse_approva_id_only_returns_empty_filters():
    tid, filters, errors = bot._parse_approva_command("12345")
    assert tid == 12345
    assert filters == {}
    assert errors == []


def test_parse_approva_single_dimension():
    tid, filters, errors = bot._parse_approva_command("12345 keywords=PNRR,formazione")
    assert tid == 12345
    assert filters == {"keywords": ["PNRR", "formazione"]}
    assert errors == []


def test_parse_approva_multiple_dimensions():
    tid, filters, errors = bot._parse_approva_command(
        "12345 keywords=PNRR regioni=lazio,toscana categorie=concorso"
    )
    assert tid == 12345
    assert filters == {
        "keywords": ["PNRR"],
        "regioni": ["lazio", "toscana"],
        "categorie": ["concorso"],
    }
    assert errors == []


def test_parse_approva_value_with_spaces():
    """Multi-word values like 'Selezione Professionisti ed Esperti' must survive."""
    tid, filters, errors = bot._parse_approva_command(
        "12345 categorie=concorso,Selezione Professionisti ed Esperti,"
        "Procedure Straordinarie regioni=lazio"
    )
    assert tid == 12345
    assert filters == {
        "categorie": [
            "concorso",
            "Selezione Professionisti ed Esperti",
            "Procedure Straordinarie",
        ],
        "regioni": ["lazio"],
    }
    assert errors == []


def test_parse_approva_tutto_si_sets_notifica_tutto_and_drops_other_filters():
    tid, filters, errors = bot._parse_approva_command(
        "12345 keywords=ignored regioni=ignored tutto=si"
    )
    assert tid == 12345
    assert filters == {"notifica_tutto": True}
    assert errors == []


def test_parse_approva_tutto_no_is_a_noop():
    tid, filters, errors = bot._parse_approva_command(
        "12345 keywords=a tutto=no"
    )
    assert tid == 12345
    assert filters == {"keywords": ["a"]}
    assert errors == []


def test_parse_approva_unknown_key_reports_error():
    tid, filters, errors = bot._parse_approva_command("12345 bogus=value")
    assert tid == 12345
    # 'bogus' isn't a known key; since the splitter only splits before known keys,
    # the whole "bogus=value" ends up as a single chunk and triggers a "chiave
    # sconosciuta" error.
    assert any("chiave sconosciuta" in e or "non riconosciuto" in e for e in errors)


def test_parse_approva_keys_are_case_insensitive():
    tid, filters, errors = bot._parse_approva_command("12345 KEYWORDS=a Regioni=lazio")
    assert tid == 12345
    assert filters == {"keywords": ["a"], "regioni": ["lazio"]}
    assert errors == []


def test_parse_approva_strips_empty_csv_values():
    tid, filters, errors = bot._parse_approva_command("12345 keywords=a,,b, ,c")
    assert tid == 12345
    assert filters == {"keywords": ["a", "b", "c"]}


# ----- handler tests (mocking PTB Update/Context) ------------------------

def _make_update(text: str = "", user_id: int = 100):
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = text
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.full_name = f"User{user_id}"
    update.effective_user.first_name = f"User{user_id}"
    return update


def _make_context():
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


def _run(coro):
    return asyncio.run(coro)


def test_start_registers_new_user_as_pending_and_pings_admin(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "999")
    update = _make_update(text="/start", user_id=42)
    update.effective_user.full_name = "Alice Smith"
    context = _make_context()

    _run(bot.start_handler(update, context))

    users = db.get_all_users()
    assert len(users) == 1
    assert users[0]["telegram_id"] == 42
    assert users[0]["status"] == "pending"
    assert users[0]["name"] == "Alice Smith"

    # User got the pending message.
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args.args[0].lower()
    assert "registrato" in reply and "amministratore" in reply

    # Admin got pinged with the new-user details.
    context.bot.send_message.assert_awaited_once()
    admin_call = context.bot.send_message.call_args
    assert admin_call.kwargs["chat_id"] == 999
    assert "42" in admin_call.kwargs["text"]
    assert "Alice Smith" in admin_call.kwargs["text"]


def test_start_existing_active_user_gets_welcome(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "999")
    db.upsert_user(42, "Alice", {}, status="active")
    update = _make_update(text="/start", user_id=42)
    context = _make_context()

    _run(bot.start_handler(update, context))

    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.call_args.args[0]
    assert "inpa-bot" in msg
    # No admin ping for existing users.
    context.bot.send_message.assert_not_called()


def test_start_existing_pending_user_gets_status_reminder(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "999")
    db.upsert_user(42, "Alice", {}, status="pending")
    update = _make_update(text="/start", user_id=42)
    context = _make_context()

    _run(bot.start_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "attesa" in msg.lower()
    context.bot.send_message.assert_not_called()


def test_approva_rejects_non_admin(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    update = _make_update(text="/approva 42 keywords=test", user_id=999)
    context = _make_context()

    _run(bot.approva_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "amministratore" in msg.lower()
    # No DB writes.
    assert db.get_all_users() == []


def test_approva_unknown_user_id(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    update = _make_update(text="/approva 42 keywords=test", user_id=1)
    context = _make_context()

    _run(bot.approva_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "non trovato" in msg.lower()
    # No user got notified.
    context.bot.send_message.assert_not_called()


def test_approva_activates_pending_user_and_notifies_them(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    db.upsert_user(42, "Alice", {}, status="pending")
    update = _make_update(
        text="/approva 42 keywords=PNRR regioni=lazio",
        user_id=1,
    )
    context = _make_context()

    _run(bot.approva_handler(update, context))

    # DB state changed.
    user = next(u for u in db.get_all_users() if u["telegram_id"] == 42)
    assert user["status"] == "active"
    assert user["filters"] == {"keywords": ["PNRR"], "regioni": ["lazio"]}

    # Admin got a confirmation summary.
    admin_msg = update.message.reply_text.call_args.args[0]
    assert "Alice" in admin_msg and "42" in admin_msg

    # User got the activation DM.
    context.bot.send_message.assert_awaited_once()
    user_call = context.bot.send_message.call_args
    assert user_call.kwargs["chat_id"] == 42
    assert "attivato" in user_call.kwargs["text"].lower()


def test_approva_with_tutto_si_sets_notifica_tutto(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    db.upsert_user(42, "Alice", {}, status="pending")
    update = _make_update(text="/approva 42 tutto=si", user_id=1)
    context = _make_context()

    _run(bot.approva_handler(update, context))

    user = next(u for u in db.get_all_users() if u["telegram_id"] == 42)
    assert user["filters"] == {"notifica_tutto": True}
    assert user["status"] == "active"


def test_revoca_rejects_non_admin(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    db.upsert_user(42, "Alice", {"keywords": ["x"]}, status="active")
    update = _make_update(text="/revoca 42", user_id=999)
    context = _make_context()

    _run(bot.revoca_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "amministratore" in msg.lower()
    user = next(u for u in db.get_all_users() if u["telegram_id"] == 42)
    assert user["status"] == "active"
    assert user["filters"] == {"keywords": ["x"]}


def test_revoca_unknown_user(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    update = _make_update(text="/revoca 42", user_id=1)
    context = _make_context()

    _run(bot.revoca_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "non trovato" in msg.lower()


def test_revoca_sets_pending_and_clears_filters(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    db.upsert_user(42, "Alice", {"keywords": ["a", "b"]}, status="active")
    update = _make_update(text="/revoca 42", user_id=1)
    context = _make_context()

    _run(bot.revoca_handler(update, context))

    user = next(u for u in db.get_all_users() if u["telegram_id"] == 42)
    assert user["status"] == "pending"
    assert user["filters"] == {}


def test_utenti_shows_pending_and_active_counts(db, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "1")
    db.upsert_user(10, "Pending One", {}, status="pending")
    db.upsert_user(20, "Active One", {"keywords": ["a"]}, status="active")
    db.upsert_user(30, "Active Two", {"notifica_tutto": True}, status="active")
    update = _make_update(text="/utenti", user_id=1)
    context = _make_context()

    _run(bot.utenti_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "3" in msg  # total
    assert "1 in attesa" in msg
    assert "2 attivi" in msg
    assert "Pending One" in msg
    assert "Active One" in msg
    assert "Active Two" in msg


def test_profilo_for_pending_user_says_in_attesa(db, monkeypatch):
    db.upsert_user(42, "Alice", {}, status="pending")
    update = _make_update(text="/profilo", user_id=42)
    context = _make_context()

    _run(bot.profilo_handler(update, context))

    msg = update.message.reply_text.call_args.args[0]
    assert "attesa" in msg.lower()
