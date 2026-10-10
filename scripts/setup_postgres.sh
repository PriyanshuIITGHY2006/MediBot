#!/usr/bin/env bash
# One-time local PostgreSQL setup for MediBot (Arch / CachyOS). Run:  sudo bash scripts/setup_postgres.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PW=$(grep '^MEDIBOT_DB_PASSWORD=' .env | cut -d= -f2-)
[ -n "$PW" ] || { echo "MEDIBOT_DB_PASSWORD missing in .env"; exit 1; }

pacman -S --needed --noconfirm postgresql pgvector

if [ ! -f /var/lib/postgres/data/PG_VERSION ]; then
  sudo -iu postgres initdb --locale=C.UTF-8 --encoding=UTF8 -D /var/lib/postgres/data
fi
systemctl enable --now postgresql

sudo -iu postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'medibot') THEN
    CREATE ROLE medibot LOGIN PASSWORD '${PW}';
  ELSE
    ALTER ROLE medibot PASSWORD '${PW}';
  END IF;
END \$\$;
SELECT 'CREATE DATABASE medibot OWNER medibot' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'medibot')\gexec
SQL
# extensions need superuser to create; afterwards the app role can use them
sudo -iu postgres psql -d medibot -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent;"
echo "OK: postgres running, database 'medibot' ready (extensions: vector, pg_trgm, unaccent)"
