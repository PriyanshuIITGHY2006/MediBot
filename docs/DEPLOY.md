# Deploying MediBot (Azure VM)

One VM runs everything with Docker Compose: **Caddy** (HTTPS, serves the web app) → **API** (FastAPI, in-memory
catalog ≈ 2.1 GB) → **Postgres 18 + pgvector** (≈ 2.2 GB). Same origin for app and API, so no CORS setup.

| Piece | Where |
|---|---|
| `deploy/Dockerfile.api` | API image: Python 3.14 + Tesseract |
| `deploy/docker-compose.yml` | db, api, caddy; `data/` is mounted from the host |
| `deploy/Caddyfile` | automatic Let's Encrypt certificate for `$DOMAIN`, `/api/*` → API, everything else → `web/dist` |
| `deploy/cloud-init.yml` | first boot: Docker, 4 GB swap, `/opt/medibot` |
| `deploy/azure_vm.sh` | creates resource group `medibot-rg`, VM `medibot-vm`, DNS name, ports 80/443 |
| `deploy/push.sh` | builds the web app, dumps the DB, rsyncs code + runtime data, starts the stack |

## First deploy

```bash
az login                                  # Azure for Students account
bash deploy/azure_vm.sh                   # Standard_B2s (4 GB) in Central India; prints <label>.centralindia.cloudapp.azure.com
cp deploy/.env.example deploy/.env        # DOMAIN=<that name>, DB_PASSWORD, GROQ_API_KEY, MEDIBOT_LLM2_API_KEY
bash deploy/push.sh <that name>           # ~575 MB upload the first time; DB restore takes a few minutes
```

Open `https://<that name>`. The API needs ~15 s after a restart to load the catalog (`/health` turns green).

## Updates

`bash deploy/push.sh <host>` — code and web app only (rsync sends changes). Add `--with-db` after a database rebuild.

## Operating

```bash
ssh azureuser@<host>
cd /opt/medibot/deploy
docker compose ps                         # health of db / api / caddy
docker compose logs -f api                # API log
docker compose restart api
```

Cost: Standard_B2s ≈ US$35–40 / month from the Azure for Students credit. `az vm deallocate -g medibot-rg -n medibot-vm`
stops billing for compute when the demo isn't needed (`az vm start` to resume; the DNS name stays).
Secrets live only in `deploy/.env` on your machine and the server (git-ignored).
