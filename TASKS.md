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
- [ ] OS, distro, kernel version (`uname -a`, `lsb_release -a`)
- [ ] Running services: how are the existing bots managed?
      (`systemctl list-units --type=service --state=running`)
- [ ] Existing bot directories: location, structure, naming conventions
      (likely somewhere under `~`, `/opt`, or `/srv` — explore and note the pattern)
- [ ] Python setup: system Python version, whether each bot has its own venv
      or there is a shared one, where venvs live
- [ ] Dependency management: are `requirements.txt` files used? `pyproject.toml`?
      `pipenv`? Note the pattern.
- [ ] Deployment method: manual `git pull`? A `deploy.sh` script? Makefile target?
      Anything automated?
- [ ] Log setup: does each bot write to a file, rely on `journalctl`, or something else?
      Note log locations and rotation config if present.
- [ ] Secrets management: `.env` files? Environment variables set in the systemd unit?
      A shared secrets directory?
- [ ] Any shared infrastructure: common SQLite/Postgres instance, shared config,
      shared utilities library, common Telegram bot helper?
- [ ] Reverse proxy: is nginx/caddy running? (Likely not needed here, but good to know.)
- [ ] Available disk space and RAM headroom (`df -h`, `free -h`)
- [ ] Any existing cron jobs relevant to bots (`crontab -l`)

Write all findings into `INFRASTRUCTURE.md`. Note anything that should influence
the inpa-bot design and flag it explicitly at the top of that file.

---

### 2. Repo scaffold
Once the survey is done and `INFRASTRUCTURE.md` exists:

- [ ] Initialise Git repo, create `.gitignore` (Python template + `.env` + `*.db`)
- [ ] Create the directory structure from `CLAUDE.md`
- [ ] Write `.env.example` with all required variables documented
- [ ] Write a minimal `README.md` (what the project is, how to run it locally)
- [ ] Write `requirements.txt` with initial dependencies:
      `python-telegram-bot`, `requests`, `beautifulsoup4`, `python-dotenv`, `pytest`
      (adjust based on what the survey reveals about existing bot dependencies)
- [ ] Commit: `chore: initial repo scaffold`

---

### 3. inPA portal recon
Do this locally (not on the server). Goal: understand how to reliably get listing data.

- [ ] Open `https://www.inpa.gov.it/bandi-e-avvisi/` in Chrome DevTools → Network tab
- [ ] Filter for XHR/Fetch requests and note every API call made on page load and
      on pagination/filter interactions
- [ ] Check whether responses are JSON (preferred) or HTML
- [ ] If JSON API found: document base URL, query parameters, pagination pattern,
      and a sample response structure in `INFRASTRUCTURE.md` under an "inPA API" section
- [ ] If HTML only: identify the CSS selectors or DOM structure needed to extract:
      title, ente, category, region, deadline, URL/concorso_id
- [ ] Check `portale.inpa.gov.it/api/` — we have evidence this subdomain serves data
      directly (PDFs, structured content); probe whether a listing endpoint exists there
- [ ] Check for a `robots.txt` at `www.inpa.gov.it/robots.txt`
- [ ] Note rate limiting behaviour if any (response headers, HTTP 429s)
- [ ] Commit findings as a section in `INFRASTRUCTURE.md`:
      `docs: add inPA API recon findings`

---

## 📋 Backlog — Session 2

- [ ] Implement `src/scraper.py` based on recon findings
- [ ] Write `tests/test_scraper.py` with mocked HTTP responses
- [ ] Implement `src/db.py`: SQLite schema, offer deduplication, user profiles table
- [ ] Write `tests/test_db.py` using in-memory DB
- [ ] Run `pytest -v` — all tests must pass before moving on

## 📋 Backlog — Session 3

- [ ] Implement `src/matcher.py`: filter offers against user profiles
- [ ] Write `tests/test_matcher.py`
- [ ] Implement `src/notifier.py`: Telegram message formatting, inline keyboard buttons
- [ ] Implement `src/bot.py`: `/start`, `/profile`, `/offers`, `/help` command handlers
- [ ] Implement `src/scheduler.py`: polling loop wiring everything together

## 📋 Backlog — Session 4

- [ ] Deploy to server following `INFRASTRUCTURE.md` conventions
- [ ] Write `deploy/inpa-bot.service` (or Docker equivalent)
- [ ] Write `deploy/deploy.sh`
- [ ] Smoke test end-to-end on server
- [ ] Onboard first test user (one of the friends) and verify notification delivery

## 📋 Backlog — Future

- [ ] Admin Telegram command to check bot health / last successful poll
- [ ] Error alerting: Telegram message to admin chat on scraper failure
- [ ] Add more filter dimensions to user profiles (salary range, contract type)
- [ ] Consider persisting raw offer JSON for debugging past notifications

---

## ✅ Done

_(nothing yet — session 1 not started)_
