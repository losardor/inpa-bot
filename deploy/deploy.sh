#!/usr/bin/env bash
# Deploy inpa-bot on the server.
# Run from the repo root on inpa-server as the `inpa` user:
#     cd /opt/inpa-bot && ./deploy/deploy.sh
#
# Idempotent: pulls, rebuilds the image if anything changed, restarts the
# container, and prints the last 50 log lines so you can see startup.
# Run `docker compose logs -f` separately if you want a live tail.
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

echo ">> Recent logs:"
docker compose logs --tail=50
