# TASKS.md — inpa-bot

Session-level todo list. Update this file at the end of every Claude Code session
before closing. Completed items move to the Done section with a brief note on
outcome or any surprises found.

---

## 🔄 Session 1 — In progress

### 1. Server survey
Connect to the remote server and document the existing infrastructure so that
all subsequent architectural decisions are consistent with what is already there.
Output goes into `INFRASTRUCTURE.md` (create it during this task).

Checklist:
- [x] OS, distro, kernel version (`uname -a`, `lsb_release -a`)
- [x] Running services: how are the existing bots managed?
      (`systemctl list-units --type=service --state=running`)
- [x] Existing bot directories: location, structure, naming conventions
      (likely somewhere under `~`, `/opt`, or `/srv` — explore and note the pattern)
- [x] Python setup: system Python version, whether each bot has its own venv
      or there is a shared one, where venvs live
- [x] Dependency management: are `requirements.txt` files used? `pyproject.toml`?
      `pipenv`? Note the pattern.
- [x] Deployment method: manual `git pull`? A `deploy.sh` script? Makefile target?
      Anything automated?
- [x] Log setup: does each bot write to a file, rely on `journalctl`, or something else?
      Note log locations and rotation config if present.
- [x] Secrets management: `.env` files? Environment variables set in the systemd unit?
      A shared secrets directory?
- [x] Any shared infrastructure: common SQLite/Postgres instance, shared config,
      shared utilities library, common Telegram bot helper?
- [x] Reverse proxy: is nginx/caddy running? (Likely not needed here, but good to know.)
- [x] Available disk space and RAM headroom (`df -h`, `free -h`)
- [x] Any existing cron jobs relevant to bots (`crontab -l`)

Write all findings into `INFRASTRUCTURE.md`. Note anything that should influence
the inpa-bot design and flag it explicitly at the top of that file.

**Outcome (2026-05-18):** Server is freshly provisioned — no existing bots, no
precedent to match. Docker + Compose already installed; Python 3.12 system
interpreter but no pip/venv/package managers. 1 vCPU / 961 MiB RAM / 20 GB disk,
ufw default-deny inbound (only port 22 open), Europe/Rome TZ. See
`INFRASTRUCTURE.md` for full details and runtime recommendation
(Docker Compose preferred, systemd documented as alternative).

---

### 2. Repo scaffold
Once the survey is done and `INFRASTRUCTURE.md` exists:

- [x] Initialise Git repo, create `.gitignore` (Python template + `.env` + `*.db`)
- [x] Create the directory structure from `CLAUDE.md`
- [x] Write `.env.example` with all required variables documented
- [x] Write a minimal `README.md` (what the project is, how to run it locally)
- [x] Write `requirements.txt` with initial dependencies:
      `python-telegram-bot`, `requests`, `beautifulsoup4`, `python-dotenv`, `pytest`
      (adjust based on what the survey reveals about existing bot dependencies)
- [x] Commit: `chore: initial repo scaffold`

**Outcome (2026-05-18):** Initial scaffold landed in commit `5b5809c`. After the
server survey, switched the deployment target from systemd to Docker Compose:
added `Dockerfile` (python:3.12-slim, non-root user, tini init), `docker-compose.yml`
(named volume for SQLite data, log size capped), `.dockerignore`, rewrote
`deploy/deploy.sh` as a Compose wrapper, removed `deploy/inpa-bot.service`,
and updated CLAUDE.md + README.md to match. See commit
`chore: switch to Docker, update CLAUDE.md and scaffold deploy files`.

---

### 3. inPA portal recon
Do this locally (not on the server). Goal: understand how to reliably get listing data.

- [x] Open `https://www.inpa.gov.it/bandi-e-avvisi/` in Chrome DevTools → Network tab
- [x] Filter for XHR/Fetch requests and note every API call made on page load and
      on pagination/filter interactions
- [x] Check whether responses are JSON (preferred) or HTML
- [x] If JSON API found: document base URL, query parameters, pagination pattern,
      and a sample response structure in `INFRASTRUCTURE.md` under an "inPA API" section
- [x] If HTML only: identify the CSS selectors or DOM structure needed to extract:
      title, ente, category, region, deadline, URL/concorso_id
- [x] Check `portale.inpa.gov.it/api/` — we have evidence this subdomain serves data
      directly (PDFs, structured content); probe whether a listing endpoint exists there
- [x] Check for a `robots.txt` at `www.inpa.gov.it/robots.txt`
- [x] Note rate limiting behaviour if any (response headers, HTTP 429s)
- [x] Commit findings as a section in `INFRASTRUCTURE.md`:
      `docs: add inPA API recon findings`

**Outcome (2026-05-18):** No HTML scraping needed. The listings page is rendered
client-side by `https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/`,
which exposes a public JSON `search-better` endpoint (paginated by `page`/`size`,
sorted by `dataPubblicazione DESC`) plus reference endpoints
(`/get-categorie`, `/get-settori`, `/find-all`). Detection strategy: fetch
page 0, stop paginating on first known `id`. Full field list and detail URL
template captured in `INFRASTRUCTURE.md` → "inPA portal recon".

---

## 🔄 Session 2 — Complete

- [x] Implement `src/scraper.py` based on recon findings
- [x] Write `tests/test_scraper.py` with mocked HTTP responses
- [x] Implement `src/db.py`: SQLite schema, offer deduplication, user profiles table
- [x] Write `tests/test_db.py` using in-memory DB
- [x] Run `pytest -v` — all tests must pass before moving on

**Outcome (2026-05-18):** scraper and db modules landed with 22 passing tests.
- `src/scraper.py`: `requests` client (10 s timeout) against
  `portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/`. Public
  surface: `fetch_new_offers(since_id, page_size, max_pages)`,
  `fetch_categories/sectors/regions`, `detail_url(offer_id)`. Cold start
  (`since_id is None`) intentionally fetches only page 0 to avoid flooding
  users with the ~67k historical backlog — call out to revisit if we ever
  want a backfill mode.
- `src/db.py`: SQLite with module-scoped connection (`init_db(path=None)`,
  `close_db()`). Tables: `offers`, `users`, `seen_offers`. Camel→snake field
  map keeps DB column names Pythonic while still accepting the scraper's
  raw dicts. `save_offer` uses `INSERT OR IGNORE` for race-safe dedup;
  `upsert_user` uses `ON CONFLICT DO UPDATE`.
- Added `pytest.ini` (`pythonpath = .`, `testpaths = tests`) and
  `src/__init__.py` so `from src import db` works under pytest.
- Tests use the `responses` library for HTTP mocking and `":memory:"` for
  the DB, per the testing rules in CLAUDE.md.

## 🔄 Session 3 — Complete

- [x] Implement `src/matcher.py`: filter offers against user profiles
- [x] Write `tests/test_matcher.py`
- [x] Implement `src/notifier.py`: Telegram message formatting, inline keyboard buttons
- [x] Implement `src/bot.py`: `/start`, `/profilo`, `/offerte`, `/help` command handlers
      (commands ended up in Italian to match the bot's user-facing language;
      added admin-only `/utenti`)
- [x] Implement `src/scheduler.py`: polling loop wiring everything together

**Outcome (2026-05-18):** end-to-end flow in place; 47 tests pass.
- `src/matcher.py`: pure-function `get_matching_users(offer, users)`. Within a
  filter dimension values OR; across dimensions AND; `notifica_tutto` bypasses.
  Keyword matching is case-insensitive substring across
  `titolo + figuraRicercata + descrizioneBreve`. Region filter targets `sedi`
  (the closest offer field we have).
- `src/notifier.py`: async `notify_user(bot, telegram_id, offer)` with HTML
  message body and a two-button inline keyboard (the second button only when
  `allegatoMediaId` is present). `TelegramError` is logged, never raised.
- `src/bot.py`: PTB v22 async handlers for /start, /profilo, /offerte, /help,
  and admin-only /utenti gated by `ADMIN_TELEGRAM_ID`. Profile creation is
  out-of-band; users without a profile see their `telegram_id` so they can
  ask the admin to enrol them.
- `src/scheduler.py`: `python -m src.scheduler` entry point. Loads .env,
  configures logging to stdout, opens the DB, builds the bot Application,
  starts the updater, then runs `poll_loop` every `POLL_INTERVAL_SECONDS`
  (enforced minimum 900). Each cycle: `fetch_new_offers(since_id) → save_offer →
  matcher.get_matching_users → notifier.notify_user → db.mark_seen`. Logs a
  one-line summary per cycle. Blocking I/O goes through `asyncio.to_thread`.
- `src/db.py` extended with `mark_seen`, `get_recent_offers`, `get_latest_offer_id`,
  and a reverse field map so DB rows are returned in the same camelCase shape
  the scraper produces — matcher/notifier are agnostic to the data source.
- Added `ADMIN_TELEGRAM_ID` to `.env.example` and the CLAUDE.md env table.

## 🔄 Session 4 — Complete

- [x] Deploy to server following `INFRASTRUCTURE.md` conventions
- [x] Write `deploy/inpa-bot.service` (or Docker equivalent)
      — Docker equivalent was already in place from Session 1 (Dockerfile +
      docker-compose.yml). Verified live.
- [x] Write `deploy/deploy.sh` — already in place; tweaked the path comment
      and switched the trailing log tail to one-shot so the script returns.
- [x] Smoke test end-to-end on server
- [x] Onboard first test user (one of the friends) and verify notification delivery

**Outcome (2026-05-18):** bot live in production at `/opt/inpa-bot` on
`inpa-server`, running as the `inpa` user (UID 1001) via Docker Compose.

Deployment surfaced one real bug not caught by tests: the Session 1 recon
documented the inPA search endpoint as GET, but the live API is
`POST /search-better` with `{}` body — GET returns 400 because the
`/concorso-public-area/{id}` route interprets `search-better` as a concorso
id. Fixed in commit `4ca23fb` (one-line scraper change + test mock updates);
all 47 tests still pass. `INFRASTRUCTURE.md` recon section corrected and
flagged.

Smoke test results:
- All four commands (`/start`, `/help`, `/profilo`, `/utenti`) responded as
  designed in Telegram.
- Cold-start poll ingested 20 offers from `dataPubblicazione DESC` page 0.
- Admin user (telegram_id 237844366) enrolled with `notifica_tutto: True`.
- Synthetic notification dispatched via `docker compose exec` to validate the
  full notify chain (DB → matcher → notifier → Telegram) without waiting for
  inPA to publish a new bando; full keyboard + message format verified by the
  user in Telegram.
- Next live poll at 12:33:00 confirmed since-id pagination: scraper hit the
  most recent known id on page 0, returned 0 new offers, 0 notifications —
  exactly the steady-state behaviour we want.
- `deploy/deploy.sh` re-tested end-to-end (`git pull` → `docker compose build`
  → `up -d` → `logs --tail=50`); completes cleanly.

Operational notes (gotchas seen during deploy, captured in
`INFRASTRUCTURE.md`):
- `git clone .` failed because `/opt/inpa-bot/data` was pre-created. Future
  provisioning should clone first, then create `data`.
- One `httpx.ReadTimeout` against api.telegram.org on the very first start;
  the `unless-stopped` policy recovered immediately. Watch list item.
- `deploy.sh` mutates itself in place — the first run pulled the new version
  but kept executing the old in-memory copy. Re-runs are fine.

Prerequisite from earlier sessions:
- The dedicated `inpa` service user (Session 4 hard prereq from Session 2)
  was created during this session via `useradd -m -s /bin/bash inpa &&
  usermod -aG docker inpa`.

## 📋 Backlog — Future

- [ ] Admin Telegram command to check bot health / last successful poll
- [ ] Error alerting: Telegram message to admin chat on scraper failure
- [ ] Add more filter dimensions to user profiles (salary range, contract type)
- [ ] Consider persisting raw offer JSON for debugging past notifications
- [ ] Find the correct URL paths for the reference taxonomies
      (`fetch_categories/sectors/regions`) — the current `/concorso-public-area/`
      paths return 400. Then wire a periodic refresh job to cache them in the DB.

---

## ✅ Done

_(nothing yet — session 1 not started)_
