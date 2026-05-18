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

The bot runs as a Docker container on a remote Linux server (Ubuntu 24.04,
1 vCPU, 1 GB RAM). The server was freshly provisioned for this project: no
other bots run on it yet, but Docker + the Compose plugin are already
installed. `inpa-bot` sets the deployment pattern that any future bot on the
box will inherit. Always check `INFRASTRUCTURE.md` for the up-to-date picture
of the server before making architectural decisions.

---

## Architecture

```
Scheduler (poll every 30 min)
    └── Scraper / API client   →  fetches new bandi from inpa.gov.it
            └── DB (SQLite)    →  deduplicates, stores seen offer IDs
                    └── Matcher  →  filters offers against each user profile
                            └── Notifier  →  sends Telegram messages with inline buttons
```

Telegram command handlers (`/start`, `/profilo`, `/offerte`, `/help`, plus
the admin-only `/utenti`) run in a separate async loop alongside the
scheduler.

---

## Repository layout

```
inpa-bot/
├── .env.example          # documented env vars, no secrets
├── .gitignore
├── CLAUDE.md             # this file
├── TASKS.md              # session todo list — update before finishing any session
├── INFRASTRUCTURE.md     # server survey + runtime decisions
├── README.md
├── requirements.txt
├── Dockerfile            # python:3.12-slim base; runs `python -m src.scheduler`
├── docker-compose.yml    # one service, named volume for the SQLite DB, log rotation
├── deploy/
│   └── deploy.sh         # wraps `git pull && docker compose build && up -d`
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

---

## Environment and setup

**Local development on the Mac uses a Python virtualenv.** Production on the
server uses Docker (see *Deployment* below) — do not mix the two. The venv is
for running tests, iterating on parsing/matching logic, and ad-hoc scripts.

```bash
# clone and enter the repo
git clone <repo-url> && cd inpa-bot

# create and activate a virtual environment (local dev only)
python3 -m venv .venv
source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# configure secrets
cp .env.example .env
# then edit .env with real values

# run the test suite
pytest -v
```

Required environment variables (document all of these in `.env.example`):

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `POLL_INTERVAL_SECONDS` | How often to check inPA (minimum 900 = 15 min) |
| `DB_PATH` | Path to the SQLite database file |
| `LOG_LEVEL` | `INFO` in production, `DEBUG` in development |
| `ADMIN_TELEGRAM_ID` | Numeric Telegram id allowed to run admin commands (e.g. `/utenti`); empty disables them |

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

Production runs on `inpa-server` (SSH alias in `~/.ssh/config`) as a single
Docker Compose service.

**Base image:** `python:3.12-slim`. Chosen deliberately to keep the image
small — the server has only 1 GB of RAM and a 20 GB disk, and the Docker
daemon already uses ~100 MB at idle. Do not switch to a fatter base
(`python:3.12`, `ubuntu`, distroless variants with extra tooling) without
revisiting the resource budget in `INFRASTRUCTURE.md`.

**Before the first deploy (one-time setup on the server):**

1. Create a dedicated unprivileged user for the bot (e.g. `inpa`) and add
   it to the `docker` group. The bot should not run from `root`'s home.
   This is captured as a Session 4 prerequisite in `TASKS.md`.
2. Clone the repo into `~/bots/inpa-bot` for that user.
3. Copy `.env.example` to `.env` and fill in real values. `chmod 600 .env`.

**Each deploy:**

```bash
# on your local machine
ssh inpa-server

# on the server, as the inpa user
cd ~/bots/inpa-bot
./deploy/deploy.sh
```

`deploy/deploy.sh` wraps the standard sequence:

```bash
git pull --ff-only origin main
docker compose build
docker compose up -d
docker compose logs -f --tail=50    # tail logs to confirm clean start
```

The SQLite database lives in a named Docker volume (`data`), so
`docker compose down` is safe and `docker compose up -d` resumes with the
same data. To inspect the DB, `docker compose exec inpa-bot sqlite3
/app/data/inpa-bot.db` (the `sqlite3` CLI inside the slim image needs to be
installed via the Dockerfile if we want this — currently the host has no
`sqlite3` either).

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
- **Respect the server's resource budget.** 1 vCPU / 961 MiB RAM / 20 GB disk.
  Before adding a heavy dependency, a second long-running process, or a fatter
  base image, check `INFRASTRUCTURE.md` and confirm the choice still fits. Log
  output is capped to ~30 MB per container via `docker-compose.yml` — do not
  remove those limits.
