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
| `read-weather.py` | Current weather + 4-day forecast from Open-Meteo (free, no key). |
| `read-codex.py` | Codex 5-hour / weekly limits via the local Codex login (`~/.codex`). |
| `read-claude.py` | Claude 5-hour / weekly limits via the local Claude Code login. Sends no chat message. |
| `read-aerisiq.py` | AerisIQ map status: OK / ERROR / DOWN (LATE is decided when drawing). |
| `common.py` | Shared JSON envelope, HTTP and child-process helpers. |
| `generate.py` | Draws the image. `--data`, `--out`, `--now` options for testing. |
| `environment.yml` | Conda env (Python 3.12, Pillow, tzdata), installed in `./env`. |
| `fonts/` | DejaVu Sans fonts (with their license). |
| `.env.example` | Template for `.env`. |
| `.env` | Upload URL + token and weather location. Private (chmod 600), never committed. |
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
