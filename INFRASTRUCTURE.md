# INFRASTRUCTURE.md — inpa-bot deployment target

Survey completed 2026-05-18 against `inpa-server` (`root@80.211.24.50`,
hostname `mordekai`). First production deploy completed the same day —
see the "Production deployment" section at the bottom for the live
layout and operational commands.

---

## ⚠️ Headline findings — read before any design decision

1. **The server is freshly provisioned. There are no existing Telegram bots.**
   `CLAUDE.md` assumed we would be matching established patterns on the box;
   we are not. There is no precedent for directory layout, runtime manager,
   dependency tooling, log location, or secrets handling. **We are setting
   the pattern, not following one.** Any choice we make here will become the
   convention if/when other bots land on this server.
2. **Docker (with the Compose plugin) is already installed and running.**
   No images, no containers. Choosing Docker for `inpa-bot` is a zero-cost
   path; choosing systemd means apt-installing `python3-venv` and `python3-pip`
   first.
3. **Tiny box: 1 vCPU, 961 MiB RAM, 20 GB root disk (15 GB free).**
   Keep dependencies lean. Avoid frameworks that load a lot at import.
4. **Only port 22 is open inbound (ufw).** Fine for a polling bot;
   would need a firewall rule change for a Telegram webhook setup.
5. **Only `root` has working SSH access.** There is an `ubuntu` user but no
   shell history and no keys provisioned for it. For a long-running service
   we should create a dedicated unprivileged user (e.g. `inpa`) and run the
   bot as that user — flag for Session 4.
6. **No Python package manager installed at all** (no `pip`, `pip3`, `pipx`,
   `poetry`, `pipenv`, `uv`). The system has only `/usr/bin/python3.12`.
   Docker sidesteps this entirely; native venv path requires
   `apt install python3-venv python3-pip`.
7. **No SQLite CLI** (`sqlite3` not installed). The Python `sqlite3` stdlib
   module still works, so the bot itself is fine, but apt-install `sqlite3`
   on the server for ad-hoc DB inspection.

---

## Host

| Field | Value |
|---|---|
| Hostname | `mordekai` |
| Public IP | `80.211.24.50` |
| SSH alias | `inpa-server` (in `~/.ssh/config`) |
| SSH user | `root` (key: `~/.ssh/id_ed25519`) |
| OS | Ubuntu 24.04.2 LTS (Noble Numbat) |
| Kernel | `6.8.0-59-generic` (PREEMPT_DYNAMIC, x86_64) |
| Virtualisation | KVM/QEMU guest (qemu-guest-agent running, open-vm-tools present) |
| Timezone | `Europe/Rome` (CEST / UTC+2). NTP active, clock synced. |
| Uptime at survey | ~6 minutes — recently rebooted |

### Hardware

| Resource | Capacity |
|---|---|
| CPU | 1 × Intel Core (Broadwell, IBRS) |
| RAM | 961 MiB total, ~280 MiB free, ~620 MiB available at idle |
| Swap | 511 MiB (unused) |
| `/` (lv-root) | 20 GB, 3.9 GB used, 15 GB free (22 %) |
| `/boot` (sda2) | 488 MB, 41 % used |

---

## Users and access

- `root` — only account with SSH key authorized. Login from `193.206.238.5`
  observed today.
- `ubuntu` — exists in `/home/ubuntu`, sudo group, but `.ssh/` is empty and
  `.bash_history` is empty. Effectively unused.
- `wtmp` starts 2026-05-18 12:20 → server has essentially no historical
  login data; confirms recent provisioning.

**Recommendation**: create a dedicated `inpa` (or reuse `ubuntu`) system
user before deploying. Do not run the bot as root.

---

## Existing services

`systemctl list-units --type=service --state=running` returns 21 units,
**all of them OS or platform services**. No custom services. Specifically:

| Custom-relevant | Status |
|---|---|
| `docker.service` | active (running) |
| `containerd.service` | active (running) |
| `fail2ban.service` | active (running, sshd jail only) |
| `cron.service` | active (running) — no user crontabs |
| `rsyslog.service` | active (running) |
| `ssh.service` | active (running) |
| `qemu-guest-agent.service` | active (running) |
| `unattended-upgrades.service` | active (running) |

No `*.service` units under `/etc/systemd/system/` related to bots, scrapers,
or Python workloads.

---

## Container runtime

Docker is fully installed and running, but unused:

```
$ docker ps -a       # empty
$ docker images      # empty
$ docker compose ls --all   # empty
```

Packages: `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`,
`docker-compose-plugin` (all apt-managed via the Docker upstream repo).

---

## Python toolchain

| Tool | Path / version |
|---|---|
| `python3` | `/usr/bin/python3` → 3.12.3 |
| `python3.12` | `/usr/bin/python3.12` (same) |
| `pip` / `pip3` | **not installed** |
| `pipx` | **not installed** |
| `poetry` | **not installed** |
| `pipenv` | **not installed** |
| `uv` | **not installed** |
| `python3-venv` apt package | **not installed** |

No virtualenvs anywhere under `/root`, `/home`, `/opt`, `/srv`.
No `requirements.txt`, `pyproject.toml`, or `Pipfile` anywhere on disk.

---

## Bot / application directories

Searched `/home`, `/root`, `/opt`, `/srv` (and a `find` for `*bot*` /
`*telegram*` directories under the first 4 levels of `/`):

- `/home/ubuntu` — empty except dotfiles.
- `/root` — only `.bashrc`, `.profile`, `.cache`, `.config`, `.ssh`, `.viminfo`.
- `/opt` — only `containerd/`.
- `/srv` — empty.

No precedent for `~/bots/<name>` or `/opt/<name>` layout. We pick one.
The `CLAUDE.md` template assumes `~/bots/inpa-bot`; that is fine to establish
as the convention.

---

## Data stores

| Tool | Installed? |
|---|---|
| `sqlite3` CLI | **no** |
| `psql` (Postgres client) | **no** |
| `redis-cli` | **no** |

No Postgres or Redis server running. No shared DB instance.
SQLite via Python stdlib is the right choice for `inpa-bot`; the
`sqlite3` apt package is worth installing on the server for inspection.

---

## Networking & firewall

- `ufw` is **active**, default-deny incoming, allow outgoing.
- Only allowed rule: `22/tcp (OpenSSH)` from anywhere (v4 and v6).
- Listening ports (`ss -tlnp`):
  - `:22` — sshd
  - `127.0.0.53:53`, `127.0.0.54:53` — systemd-resolved (localhost only)
- No nginx / caddy / apache / haproxy installed.
- `fail2ban` jails: `sshd` only.

For a Telegram bot using **long polling** (the default for
`python-telegram-bot`), no inbound port is needed — outbound HTTPS to
`api.telegram.org` and `www.inpa.gov.it` works through the
default-allow-outgoing policy. If we ever switch to webhooks, we'd need to
open a port and set up TLS termination.

---

## Cron and scheduled jobs

- `crontab -l` (root): **no crontab**
- `/var/spool/cron/crontabs/` is empty (no per-user crontabs).
- `/etc/cron.d/`: only stock entries (`e2scrub_all`, `sysstat`).
- `/etc/cron.daily/`: stock only (`apport`, `apt-compat`, `dpkg`,
  `logrotate`, `man-db`, `sysstat`).
- `/etc/cron.hourly/`: empty (only `.placeholder`).

No relevant pre-existing scheduling we need to coordinate with.

---

## Logging

- `rsyslog` is running, default config.
- `journalctl` is the system log query path (systemd-journald active).
- `/etc/logrotate.d/` contains only OS-level configs (apt, fail2ban,
  rsyslog, ufw, etc.) — no per-application configs.
- No bot-specific `/var/log/<bot>/` directories exist.

**Choice to make for inpa-bot**: log to stdout and let systemd-journald or
Docker capture it (preferred — zero config, queryable via `journalctl -u
inpa-bot` or `docker logs`). Avoid writing to flat files unless we have a
specific reason — there's no rotation set up for application logs.

---

## Secrets management

Nothing in place. No shared `.env` directory, no Vault, no
`/etc/<bot>/<bot>.env` convention.

**Choice to make**: either `EnvironmentFile=/etc/inpa-bot/inpa-bot.env`
in a systemd unit, or a Docker Compose `env_file:` reference. Either way,
keep the file out of `/root/` and chmod 0600 owned by the service user.

---

## Installed dev tooling

| Tool | Present |
|---|---|
| `git` | yes (`/usr/bin/git`) |
| `curl`, `wget` | yes |
| `tmux`, `screen` | yes |
| `htop`, `byobu` | yes (apt-manual) |
| `make` | **no** |
| `gcc` | **no** |
| `build-essential` | **no** |

Pure-Python dependencies will install fine; anything with a C extension
that lacks a wheel for cp312/manylinux will fail without
`apt install build-essential`. Pin dependencies to wheel-available
versions or use Docker.

---

## Implications for inpa-bot design

### Runtime: Docker Compose, recommended

Pros: Docker is already there. Python interpreter and all build tooling
isolated in the image. No need to apt-install `python3-venv`, `pip`,
`build-essential` on the host. Easy to redeploy (`docker compose pull &&
docker compose up -d`). Logs via `docker logs` / journald.

Cons: 1 GB RAM box — Docker daemon already uses ~100 MB. Tolerable but tight.

If we go this route: `deploy/docker-compose.yml` + a slim `Dockerfile`
(e.g. `python:3.12-slim`), and a one-line `deploy/deploy.sh`.

### Runtime: systemd, alternative

Pros: lighter on RAM. More direct journald integration. Matches the
`CLAUDE.md` template (`deploy/inpa-bot.service`).

Cons: must apt-install `python3-venv python3-pip` first (and possibly
`build-essential` and `sqlite3`). Per-bot venvs become our problem to
maintain.

If we go this route: `deploy/inpa-bot.service` with
`ExecStart=/home/inpa/inpa-bot/.venv/bin/python -m src.scheduler`,
`User=inpa`, `EnvironmentFile=/etc/inpa-bot/inpa-bot.env`,
`Restart=on-failure`.

### Other decisions baked in by the survey

- **Log to stdout**, capture via journald or `docker logs`. Don't write
  files.
- **SQLite file location**: `/var/lib/inpa-bot/inpa-bot.db` (FHS-correct)
  or `~/inpa-bot/data/inpa-bot.db` if we go the per-user-dir route.
  Pick one when scaffolding `deploy/`.
- **Dedicated service user** (`inpa` or `ubuntu`). Not root.
- **Outbound only**; no firewall changes needed.
- **`sqlite3` apt package** should be installed on the server for
  ad-hoc DB inspection (does not affect the running bot).

---

## inPA portal recon

Findings from 2026-05-18. The public listings on
`https://www.inpa.gov.it/bandi-e-avvisi/` are rendered client-side by
calling a JSON API on the `portale.inpa.gov.it` subdomain. No HTML
scraping is required.

### Base URL

```
https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/
```

No authentication. Plain HTTPS GET. Returns `application/json`.

### Main listing endpoint

```
POST /search-better?page=0&size=20
Content-Type: application/json
Body: {}
```

- **Verb is POST**, not GET. The Session 1 recon misrecorded this; live
  deployment in Session 4 surfaced the bug (GET returns HTTP 400 with
  `cs.app.ex.general.competition_not_found` because the API treats
  `/concorso-public-area/{id}` as a single-concorso lookup route, so a GET
  on `search-better` is parsed as "find concorso with id 'search-better'").
- An empty JSON body (`{}`) is accepted; that's how we request the
  unfiltered listing. Filtered queries presumably take filter parameters in
  the body — out of scope for now.
- Paginated. Default sort is `dataPubblicazione DESC` (newest first).
- Total population at recon time: ~67k offers across all of history.
- Pagination via `page` (0-indexed) and `size` query params.
- Each item carries a stable `id` field; treat that as the primary key.

### New-offer detection strategy

The scheduler should:

1. Fetch `page=0` on each poll.
2. For each offer in the response, check if its `id` is already in the
   local `offers` table.
3. **Stop paginating as soon as a known `id` is encountered** — everything
   beyond that is older and already seen.
4. On the very first run (empty DB), the bot operator decides how far
   back to seed. For MVP we only ingest page 0 on cold start, so users
   only get notifications for genuinely new offers going forward
   (we do not flood them with the whole 67k backlog).

### Fields to store per offer

From each item in the `search-better` response:

| Field | Notes |
|---|---|
| `id` | Stable primary key. |
| `codice` | Human-readable concorso code (e.g. ministry-specific). |
| `titolo` | Title. |
| `figuraRicercata` | Role/profile sought. |
| `descrizioneBreve` | Short description. |
| `entiRiferimento` | Array — join into a single string for storage. |
| `sedi` | Array (work locations) — join. |
| `categorie` | Array — join. |
| `settori` | Array — join. |
| `tipoProcedura` | Procedure type. |
| `calculatedStatus` | Computed status (open/closed/etc.). |
| `dataPubblicazione` | Publication date. |
| `dataScadenza` | Deadline. |
| `numPosti` | Number of positions. |
| `salaryMin` | Nullable. |
| `salaryMax` | Nullable. |
| `linkReindirizzamento` | External link, if any. |
| `allegatoMediaId` | Attachment media id (PDF). |

### Detail page URL (for inline-keyboard buttons)

```
https://www.inpa.gov.it/bandi-e-avvisi/dettaglio-bando-avviso/?concorso_id=<id>
```

### Reference / lookup endpoints

These are slow-changing taxonomies. Fetch once, cache in the DB, refresh
occasionally (e.g. weekly):

| Endpoint | Returns |
|---|---|
| `/get-categorie` | List of categorie. |
| `/get-settori` | List of settori. |
| `/find-all` | List of regions. |

> ⚠️ **Untested against live API.** Session 4 probing showed all three paths
> return HTTP 400 under `/concorso-public-area/` (same single-concorso route
> collision as `search-better`) and HTTP 405 for POST. The verb is correct
> (GET) but the URL paths are almost certainly wrong — these endpoints
> likely live under a different controller base path. The bot does not call
> these functions today (only `fetch_new_offers` runs in the poll loop), so
> this is a follow-up — see the "Future" backlog in `TASKS.md`.

### Politeness

The `CLAUDE.md` hard constraint (`POLL_INTERVAL_SECONDS >= 900`) is
sufficient — at 15 min cadence with `size=20`, we hit `search-better`
~96 times per day, each request returning ~20 records. Negligible load
on the portal.

---

## Production deployment

First successful deploy: 2026-05-18. Smoke test passed (Telegram commands
respond; synthetic notification delivered; subsequent poll cycle ran
incremental-mode and short-circuited on the known id).

### Server-side layout

| Item | Value |
|---|---|
| Service user | `inpa` (UID 1001, GID 1001) — member of `docker` (GID 988) |
| App directory | `/opt/inpa-bot` (owned by `inpa:inpa`) |
| `.env` location | `/opt/inpa-bot/.env` (chmod 600, owned by `inpa:inpa`) |
| Data store | Named Docker volume `inpa-bot_data` (managed by Docker; not bind-mounted from the host) |
| `/opt/inpa-bot/data` on host | Created during provisioning but currently **unused** — the compose file uses a named volume, not a bind mount. Safe to leave or remove. |
| Container name | `inpa-bot` |
| Image tag | `inpa-bot:latest` |
| Restart policy | `unless-stopped` |
| Log driver | `json-file`, capped at 10 MB × 3 files per container |

### Operational commands (run as the `inpa` user from `/opt/inpa-bot`)

```bash
# Standard redeploy (pull + rebuild + restart + show last 50 log lines)
./deploy/deploy.sh

# Just look at logs
docker compose logs -f --tail=100

# Restart without rebuilding (e.g. after .env change)
docker compose up -d

# Stop the bot
docker compose down

# Enroll or modify a user from inside the container
docker compose exec inpa-bot python -c "
from src import db
db.init_db()
db.upsert_user(<telegram_id>, '<Name>', {'notifica_tutto': True})
print(db.get_all_users())
"

# Open a SQLite shell against the live DB
docker compose exec inpa-bot python -c "
import sqlite3
conn = sqlite3.connect('/app/data/inpa-bot.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT id, codice, titolo FROM offers LIMIT 10'):
    print(dict(r))
"
```

### Operational notes / gotchas

- **`deploy.sh` updates take effect on the *next* run.** If you change
  `deploy.sh` upstream and `git pull` inside the script picks up the new
  version, bash is still running the old in-memory copy for the rest of
  the current run. We hit this once during initial deploy.
- **First-run httpx ReadTimeout.** On the very first `docker compose up`,
  the container hit one `httpx.ReadTimeout` against `api.telegram.org`
  during `Application.initialize()` and exited; the `unless-stopped` policy
  restarted it cleanly and it has been stable since. Likely a cold-network
  artifact on a 1 vCPU box. Worth keeping an eye on — if it recurs, bump
  the PTB httpx pool timeout.
- **scp as root, then `chown inpa:inpa`** — the SSH config only has a
  `root@` alias, so the `.env` upload pattern is
  `scp .env inpa-server:/tmp/inpa-bot.env`, then on the server
  `mv /tmp/inpa-bot.env /opt/inpa-bot/.env && chown inpa:inpa ... && chmod 600 ...`.
- **`git clone .` into a non-empty dir.** The provisioning step creates
  `/opt/inpa-bot/data` *before* the clone, which blocks `git clone . .`.
  Workaround used: rmdir data, clone, mkdir data. Future provisioning
  scripts should clone first and create data afterwards.
- **First-run cold start** intentionally ingests only page 0 of inPA
  (~20 most recent offers). Users enrolled before the next live poll
  will not be notified about those 20 unless we add a backfill path —
  see the Future backlog.

