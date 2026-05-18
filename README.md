# inpa-bot

A Telegram bot that monitors [inpa.gov.it](https://www.inpa.gov.it/) for new
public sector job offers and sends personalised notifications to users.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with real values
```

See `CLAUDE.md` for full architecture and development guidelines.
