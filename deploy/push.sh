#!/usr/bin/env bash
# Ship MediBot to the VM and (re)start it.  bash deploy/push.sh <host> [--with-db]   (SSH_USER=azureuser for Azure)
#   1. builds the web app for same-origin API calls
#   2. dumps the local medibot schema (first deploy, or --with-db)
#   3. rsyncs code + runtime data to /opt/medibot
#   4. builds and starts the stack; restores the database dump if the DB is empty
set -euo pipefail
HOST=${1:?usage: push.sh <host> [--with-db]}
WITH_DB=${2:-}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
USER_=${SSH_USER:-ubuntu}                  # ubuntu on Oracle Cloud, azureuser on Azure
SSH="ssh -o StrictHostKeyChecking=accept-new $USER_@$HOST"
cd "$ROOT"
[ -f deploy/.env ] || { echo "deploy/.env missing (copy deploy/.env.example)"; exit 1; }

echo "== web build"
(cd web && npm ci --silent && VITE_API_URL= npx vite build >/dev/null)

if [ "$WITH_DB" = --with-db ] || [ ! -f deploy/dump/medibot.dump ]; then
  echo "== database dump"
  mkdir -p deploy/dump
  URL=$(grep ^DATABASE_URL= .env | cut -d= -f2-)
  pg_dump "$URL" -Fc -n medibot --no-owner --no-privileges -f deploy/dump/medibot.dump
  ls -lh deploy/dump/medibot.dump
fi

echo "== upload"
rsync -az --delete --info=progress2 -R \
  backend/requirements.txt backend/medibot deploy/Dockerfile.api deploy/docker-compose.yml deploy/Caddyfile deploy/remote_start.sh deploy/.env deploy/dump \
  web/dist data/processed data/reference data/pipeline data/raw/jan_aushadhi/kendras.json data/interim/models data/interim/regulatory data/interim/llm_cache.sqlite data/interim/price_cache.sqlite \
  --exclude '__pycache__' --exclude '.pytest_cache' \
  "$USER_@$HOST:/opt/medibot/"

echo "== start"
$SSH "bash /opt/medibot/deploy/remote_start.sh </dev/null"
echo "== live: https://$(grep ^DOMAIN= deploy/.env | cut -d= -f2 | awk '{print $1}')"
