#!/usr/bin/env bash
# Deploy inpa-bot on the server.
# Run from the repo root on inpa-server as the `inpa` user:
#     cd ~/bots/inpa-bot && ./deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    echo "ERROR: .env is missing. Copy .env.example to .env and fill in values." >&2
    exit 1
fi

echo ">> Pulling latest changes"
git pull --ff-only origin main

echo ">> Building image"
docker compose build

echo ">> Restarting service"
docker compose up -d

echo ">> Tailing logs (Ctrl-C to detach; service keeps running in background)"
docker compose logs -f --tail=50
