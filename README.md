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
cd ~/bots/inpa-bot
./deploy/deploy.sh
```

See `CLAUDE.md` for full architecture and development guidelines.
