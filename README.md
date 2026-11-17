# Kindle Dashboard

Every 10 minutes this machine collects weather, AI plan limits and the AerisIQ
map status, draws a 600×800 black & white PNG, and uploads it to a Cloudflare
Worker. The Kindle (KOReader) downloads it with its read token.

```
cron (*/10) → run.sh
               ├─ read-weather.py  → data/weather.json  (Open-Meteo: now + 4 days, °C)
               ├─ read-codex.py    → data/codex.json    (codex app-server, account/rateLimits/read)
               ├─ read-claude.py   → data/claude.json   (claude stream-json, get_usage)
               ├─ read-aerisiq.py  → data/aerisiq.json  (aerisiq.io/map + /api/v1/forecast/run)
               ├─ generate.py      → dashboard.png
               └─ curl PUT         → UPLOAD_URL  (Bearer UPLOAD_TOKEN from .env)
```

## Files

| File | What it does |
|---|---|
| `run.sh` | Runs everything in order and uploads. `--no-upload` draws only. |
| `read-weather.py` | Current weather + 4-day forecast from Open-Meteo (free, no key). The city name is looked up from the coordinates with OpenStreetMap Nominatim, once, and cached in `data/place.json` (looked up again only if the coordinates change). |
| `read-codex.py` | Codex 5-hour / weekly limits via the local Codex login (`~/.codex`). |
| `read-claude.py` | Claude 5-hour / weekly limits via the local Claude Code login. Sends no chat message. |
| `read-aerisiq.py` | AerisIQ map status: OK / ERROR / DOWN (LATE is decided when drawing). |
| `common.py` | Shared JSON envelope, HTTP and child-process helpers. |
| `generate.py` | Draws the image. `--data`, `--out`, `--now` options for testing. |
| `environment.yml` | Conda env (Python 3.12, Pillow, tzdata), installed in `./env`. |
| `fonts/` | DejaVu Sans fonts (with their license). |
| `worker/worker.js` | The Cloudflare Worker that stores the PNG and serves it to the Kindle (same code as deployed). |
| `worker/wrangler.toml` | Deploy config for the Worker (KV id is a placeholder, no secrets). |
| `.env.example` | Template for `.env`. |
| `.env` | Upload URL + token and weather coordinates. Private (chmod 600), never committed. |
| `data/`, `logs/`, `dashboard.png` | Generated at run time, not committed. |

## Setup

```bash
mamba env create -p ./env -f environment.yml   # once
cp .env.example .env && chmod 600 .env         # then fill in the values
./run.sh --no-upload                           # test: look at dashboard.png
./run.sh                                       # real run with upload
```

Cron entry (`crontab -e`):

```
*/10 * * * * /home/xcang/kindle_dashboard/run.sh
```

## Cloudflare Worker

The Worker sits between this machine and the Kindle. It keeps only the latest
image, in Workers KV.

```
this machine ── PUT  /image.png  (Bearer UPLOAD_TOKEN) ──▶ Worker ──▶ KV "IMAGES", key dashboard.png
Kindle       ── GET  /image.png  (Bearer READ_TOKEN)   ──▶ Worker ──▶ returns the PNG
anyone       ── GET  /health                           ──▶ "OK" (no private data)
```

Two different tokens: the upload token lives only on this machine (`.env`), the
read token lives only on the Kindle. A lost Kindle can read the image but not change it.

### Set it up again (from `worker/`)

```bash
cd worker
openssl rand -hex 24                         # run twice: one upload token, one read token
npx wrangler login                           # once per computer
npx wrangler kv namespace create IMAGES      # paste the printed id into wrangler.toml
npx wrangler secret put UPLOAD_TOKEN         # paste the upload token when asked
npx wrangler secret put READ_TOKEN           # paste the read token when asked
npx wrangler deploy                          # prints https://kindle-dashboard.<subdomain>.workers.dev
curl https://kindle-dashboard.<subdomain>.workers.dev/health   # -> OK
```

Without the CLI, in the Cloudflare dashboard: **Workers & Pages → Create → Worker**,
paste `worker.js`, deploy, then in the Worker's **Settings**:
**Bindings → Add → KV namespace**, variable name `IMAGES`;
**Variables and Secrets → Add → type Secret**: `UPLOAD_TOKEN` and `READ_TOKEN`.

Then:

1. **This machine:** put `UPLOAD_URL=https://…workers.dev/image.png` and
   `UPLOAD_TOKEN=…` in `.env`, run `./run.sh`, expect `Uploaded`.
2. **Kindle:** download with the read token in a header (not in the URL):
   ```bash
   curl -fsS -H "Authorization: Bearer <READ_TOKEN>" -o dashboard.png \
        https://kindle-dashboard.<subdomain>.workers.dev/image.png
   ```

To change a token: run `wrangler secret put` again (or edit it in the dashboard);
the old one stops working at once. Then update `.env` (upload) or the Kindle (read).

### Responses

| Code | Meaning |
|---|---|
| 200 | `Uploaded` (PUT) or the PNG (GET) |
| 401 | missing or wrong token |
| 404 | no image uploaded yet, or wrong path |
| 413 | image empty or larger than 2 MB |
| 415 | `Content-Type` is not `image/png` |
| 400 | body is not a real PNG |

### Limits

- Workers KV free plan: 1,000 writes per day. Every 10 minutes = 144 writes/day;
  every minute (1,440/day) would be too many.
- KV is eventually consistent: a new image can take up to ~60 s to show everywhere.
- Do not test the read token with `curl` on this shared server: other users can
  see command lines with `ps`. Test from your own computer or the Kindle.

## AerisIQ status rules

| Status | Meaning |
|---|---|
| OK | `/map` returns the AerisIQ page and `/api/v1/forecast/run` works |
| LATE | the live run started more than 24 h ago |
| ERROR | `/run` answered 503 twice, 30 s apart, or returned unreadable data |
| DOWN | no answer, timeout, or another HTTP error |

## When something fails

- A collector that fails keeps the last good data. The screen then shows
  "as of <time>", and the error is written to `logs/run.log`.
- If drawing fails, nothing is uploaded, so the Kindle keeps the previous image.
- Overlapping runs are skipped (`flock`).
- `get_usage` is marked experimental in Claude Code. If a Claude update breaks
  it, `read-claude.py` is the only file to fix.
