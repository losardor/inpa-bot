# inpa-bot

A Telegram bot that monitors [inpa.gov.it](https://www.inpa.gov.it/) for new
public sector job offers and sends personalised notifications to users.

## Local development (Mac)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with real values
pytest -v
```

## Production (server)

Runs as a Docker Compose service on `inpa-server` (Ubuntu 24.04, 1 GB RAM).
Base image is `python:3.12-slim`. See the *Deployment* section of `CLAUDE.md`
and `INFRASTRUCTURE.md` for the full picture.

```bash
# on the server, as the `inpa` user
cd /opt/inpa-bot
./deploy/deploy.sh
```

## Admin enrolment (Telegram)

User registration is two-step. A friend sends `/start` to the bot, which
files them as `pending` and DMs the admin (the Telegram ID set in
`ADMIN_TELEGRAM_ID`). The admin then approves them, optionally with
filters.

```
/approva <telegram_id> [keywords=val1,val2] [regioni=val1,val2]
                       [categorie=val1,val2] [settori=val1,val2]
                       [tipo_procedura=val1,val2] [tutto=si]
```

- All filter parameters are optional. Within a dimension values are OR'd
  (`keywords=A,B` → match A *or* B). Across dimensions they're ANDed
  (`regioni=lazio categorie=concorso` → both must hit).
- Matching is **case-insensitive substring**, so `regioni=lazio` matches
  an offer's `sedi` containing `"Lazio"` or `"Roma, Lazio"`. inPA stores
  categoria as `"Concorso"` (singular) — type `categorie=concorso`, not
  `concorsi`.
- Multi-word values like
  `categorie=Selezione Professionisti ed Esperti` are supported; the
  parser only splits on whitespace when immediately followed by a known
  `key=` token.
- `tutto=si` short-circuits to `notifica_tutto: true` and ignores any
  other filter dimensions in the same command (the user receives every
  new bando).

Examples:

```text
/approva 5289994001 regioni=lazio categorie=concorso keywords=ricerca,PNRR

/approva 5289994001 categorie=concorso,Selezione Professionisti ed Esperti
                    regioni=lazio

/approva 538486056 tutto=si
```

Other admin commands:

- `/utenti` — list registered users grouped by status (pending first).
- `/revoca <telegram_id>` — flip a user back to pending and clear filters.

All admin commands are gated on `ADMIN_TELEGRAM_ID` from `.env`; the
admin doesn't have to be in the `users` table to run them.

See `CLAUDE.md` for full architecture and development guidelines.
