#!/usr/bin/env bash
# Runs ON the server (called by push.sh): start db, restore the dump once, build + start the stack.
set -euo pipefail
cd /opt/medibot/deploy
mkdir -p ../data/interim
docker compose up -d db
until docker compose exec -T db pg_isready -U medibot -d medibot >/dev/null 2>&1; do sleep 2; done
if [ "$(docker compose exec -T db psql -U medibot -d medibot -Atc "select count(*) from pg_namespace where nspname='medibot'")" = 0 ]; then
  echo "restoring database (a few minutes)..."
  docker compose exec -T db psql -U medibot -d medibot -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent;"
  docker compose exec -T db pg_restore -U medibot -d medibot --no-owner -j 2 /dump/medibot.dump
fi
docker compose build api
docker compose up -d
docker compose restart caddy   # rsync replaces the Caddyfile; a single-file bind mount keeps the old inode until restart
echo "waiting for the API to load the catalog..."
for i in $(seq 60); do docker compose exec -T api curl -fs localhost:8000/health >/dev/null 2>&1 && break; sleep 3; done
docker compose ps
