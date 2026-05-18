# CLAUDE.md — inpa-bot

This file is the primary reference for Claude Code working on this project.
Read it fully before starting any task.

---

## Project overview

`inpa-bot` is a Telegram bot that monitors the Italian public sector recruitment
portal [inpa.gov.it](https://www.inpa.gov.it/) for new job offers (bandi e avvisi)
and sends personalised notifications to a small group of friends. Each user has a
profile with filters (keywords, region, category, contract type). The bot only
notifies a user when a new offer matches their profile. Inline keyboard buttons
allow quick access to further details or the full listing.

The bot runs as a background service on a remote Linux server that already hosts
other Telegram bots. Consistency with the existing infrastructure on that server
is a hard requirement — always check `INFRASTRUCTURE.md` (populated after the
server survey in session 1) before making architectural decisions.

---

## Architecture

```
Scheduler (poll every 30 min)
    └── Scraper / API client   →  fetches new bandi from inpa.gov.it
            └── DB (SQLite)    →  deduplicates, stores seen offer IDs
                    └── Matcher  →  filters offers against each user profile
                            └── Notifier  →  sends Telegram messages with inline buttons
```

Telegram command handlers (`/start`, `/profile`, `/offers`, `/help`) run in a
separate async loop alongside the scheduler.

---

## Repository layout

```
inpa-bot/
├── .env.example          # documented env vars, no secrets
├── .gitignore
├── CLAUDE.md             # this file
├── TASKS.md              # session todo list — update before finishing any session
├── INFRASTRUCTURE.md     # populated after server survey (session 1)
├── README.md
├── requirements.txt
├── deploy/
│   ├── inpa-bot.service  # systemd unit file (or Docker equivalent — TBD after survey)
│   └── deploy.sh         # pull + restart script for the server
├── src/
│   ├── scraper.py        # fetches and parses inPA listings
│   ├── db.py             # SQLite interface, offer deduplication
│   ├── matcher.py        # matches offers to user profiles
│   ├── notifier.py       # Telegram message formatting and dispatch
│   ├── scheduler.py      # polling loop
│   └── bot.py            # Telegram command handlers
└── tests/
    ├── conftest.py        # shared fixtures (in-memory DB, mock HTTP, fake offers)
    ├── test_scraper.py
    ├── test_matcher.py
    └── test_db.py
```

> ⚠️ The `deploy/` layout and runtime method (systemd vs Docker) must match the
> existing server infrastructure. Do not finalise these files until `INFRASTRUCTURE.md`
> is written.

---

## Environment and setup

```bash
# clone and enter the repo
git clone <repo-url> && cd inpa-bot

# create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# configure secrets
cp .env.example .env
# then edit .env with real values
```

Required environment variables (document all of these in `.env.example`):

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `POLL_INTERVAL_SECONDS` | How often to check inPA (minimum 900 = 15 min) |
| `DB_PATH` | Path to the SQLite database file |
| `LOG_LEVEL` | `INFO` in production, `DEBUG` in development |

---

## Coding conventions

- **Python 3.11+**. Use type hints on all function signatures.
- **Conventional commits**: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
  Write the message in the imperative mood, e.g. `feat: add region filter to matcher`.
- **One module, one responsibility.** Do not let scraper logic bleed into notifier logic etc.
- **No secrets in code or commits.** All secrets come from environment variables via
  `python-dotenv`. If you catch yourself hardcoding a token or URL that could be
  configurable, move it to `.env`.
- **Logging not print.** Use Python's `logging` module throughout. Never use `print()`
  for operational output.
- **Async where it matters.** The Telegram bot handler and the scheduler should be async
  (`python-telegram-bot` v20+ is fully async). Keep blocking I/O (SQLite, HTTP) off the
  event loop using `asyncio.to_thread` where needed.

---

## Testing rules

- Use `pytest`. Run `pytest -v` before marking any task done.
- Write tests alongside every new module — not after the fact.
- **What to test:** scraper parsing logic, matcher filter logic, DB deduplication.
- **What not to test:** Telegram API calls (mock them entirely), the scheduler loop,
  network I/O (mock with `responses` or `httpretty`).
- Never mock the thing being tested. Mock its dependencies.
- The test DB must always be in-memory (`":memory:"`). Never touch the production DB
  path in tests.
- All fixtures go in `tests/conftest.py`.

---

## Git workflow

- `main` is always deployable.
- Feature work on short-lived branches: `feat/<name>`, `fix/<name>`, `chore/<name>`.
- Open a PR (even solo) before merging to `main` — it creates a reviewable diff.
- Reference issue numbers in commits where applicable: `fix: handle empty listing page (#7)`.
- **Never commit:** `.env`, `*.db`, `__pycache__/`, `.venv/`, any log files.

---

## Deployment

> Finalise this section after the server survey. The steps below are the intended
> pattern — adapt to match existing infrastructure found on the server.

```bash
# on your local machine
ssh inpa-server

# on the server
cd ~/bots/inpa-bot
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt   # only if requirements.txt changed
sudo systemctl restart inpa-bot
journalctl -u inpa-bot -f         # tail logs to confirm clean start
```

Or simply run `deploy/deploy.sh` if it has been set up.

---

## Hard constraints — never violate these

- **Minimum poll interval: 15 minutes.** Never hit the inPA portal more frequently.
  Be a polite scraper.
- **No user PII in the repo.** User profiles (names, Telegram IDs, preferences) live
  only in the SQLite database on the server, never in code or config files committed
  to Git.
- **No automatic actions on behalf of users.** The bot notifies — it never applies
  to a position, fills a form, or clicks anything on inPA on a user's behalf.
- **Fail loudly, not silently.** If the scraper fails or the inPA response changes
  structure, log an error and alert (a simple Telegram message to an admin chat ID
  is fine). Do not swallow exceptions.
- **Consistency with existing bots.** Before introducing a new dependency, deployment
  pattern, or runtime choice, check `INFRASTRUCTURE.md` to see if there is already
  a precedent on the server.
