# Chanakya AI v5 — Project Continuation in Emergent

## Original Problem Statement
> Continue github project task is attached projects link below https://github.com/helpdeskdcp/chanakya_v5.git

## What This Project Is
Chanakya AI v5 is a professional trading platform originally designed to run on a self-hosted server (`bramha.cloud/v5`, port 5002). Stack:
- **Backend:** Flask + Flask-SocketIO (Python 3.11), SQLite (`data/chanakya_v5.db`)
- **Frontend:** Server-rendered single-page HTML (`frontend/templates/index.html`, ~1500 lines, vanilla JS SPA, Chart.js)
- **Broker:** Angel One SmartAPI (live NSE/MCX feed)
- **AI:** Groq LLaMA 3.3 70B for chat / signals; XGBoost ML confidence
- **Notifications:** Telegram bot
- **Auth:** SHA-256 + SQLite sessions, 7 subscription tiers (`developer`, `administrator`, `platinum`, `gold`, `silver`, `premium`, `demo`)

## Architecture in this Emergent Pod
Supervisor's `backend` program is fixed to `uvicorn server:app` on port 8001. To host the Flask app here:

1. **`/app/chanakya/`** — full upstream repo (cleaned of junk files & local cache).
2. **`/app/backend/server.py`** — ASGI wrapper: loads `.env`, sets CWD, imports `main.app` (Flask) and exposes it via `asgiref.wsgi.WsgiToAsgi`.
3. **`/app/chanakya/main.py`** — patched:
   - `sys.path` no longer hardcoded to `/root/chanakya_v5`
   - `APPLICATION_ROOT=/v5` removed (Kubernetes ingress maps `/api/*` → backend)
   - New routes: `/api/health`, `/api/ui`, `/api/static/<path>` so the SPA is reachable through the preview URL.
4. **`/app/chanakya/notifications/telegram.py`** — compatibility shim re-exporting from `alerts.telegram_bot` (legacy modules imported `notifications.telegram` which never existed in the repo).
5. **`/app/frontend/src/App.js`** — replaced template scaffold with a thin shell (top bar + health pill) that embeds `/api/ui` in a full-height iframe.
6. **Repo path migration** — `sed` replaced 16 hardcoded `/root/chanakya_v5` paths with `/app/chanakya` across `data_stream`, `broker`, `ai`, `scripts`, `engine`, `api/routes`.

## What's Working Now
- App boots, all background services come up: Auto Trader, Adaptive Manager, Telegram polling, WS Manager, Watchdog, Recovery Engine.
- `/api/health` → `{"status":"ok","version":"5.0"}`
- `/api/calculator_data?symbol=NIFTY` returns live indicators (EMA9/21/200, RSI, MACD, VWAP, ATR, supertrend) — Angel One live connection confirmed.
- `/api/login` returns a session token; verified with `admin / admin123`.
- Full UI loads inside the React shell → login → dashboard renders live NIFTY/BANK/FIN/CRUDE/NATGAS prices.

## Known Limitations
- **WebSockets disabled** in this transport: `asgiref.WsgiToAsgi` only forwards HTTP. Flask-SocketIO falls back to long-polling; some "live tick" pushes will not stream. Long-polling continues to work for periodic refreshes.
- **Angel One LTP errors for stale tokens** — 14 trades were recovered from the SQLite DB at startup, but their `symboltoken` field is empty, so per-second LTP calls return `AB4006 Invalid symboltoken`. This is dirty production data, not a code bug.
- **Telegram polling** — bot starts cleanly with the supplied token. Be aware it now runs on a non-production environment.

## Test Credentials
Stored in `/app/memory/test_credentials.md`:
- `admin / admin123` (administrator)
- `avinash / avinash123` (developer)
- `demo / demo123` (demo)

## Implementation Log
- **2026-01-18** — Migrated repo to `/app/chanakya`, cleaned junk files, fixed hardcoded paths, created ASGI wrapper, added `/api/ui` route, shim for `notifications.telegram`, reset test passwords, embedded UI through React shell. Verified login + live market data.

## Backlog / Next Tasks (P0 → P2)
- **P0** — Clean the 14 stale recovered trades (empty `symboltoken`) to stop the per-second `AB4006` log spam.
- **P1** — Persist Angel JWT/feed/refresh tokens from `.env` into `broker.auth_manager` cache so the WebSocket reconnect loop succeeds without a daily re-login.
- **P1** — Restore real-time push: either swap `WsgiToAsgi` for `python-socketio` ASGI server, or replace `socketio.emit` calls with an SSE channel that Emergent ingress allows.
- **P2** — Delete `.BACKUP_WORKING`, `.FINAL_STABLE`, `.STABLE_*` shadow files cluttering `trading/` and `broker/`.
- **P2** — Add a small admin route to seed/reset passwords (currently done via a one-shot SQLite script).
- **P2** — Document required `.env` keys in `README.md` and ship a `.env.example`.

## Suggested Enhancement
Add an in-app "Share My Edge" tile that lets a `gold`/`platinum` user generate a one-click public PnL card (already has reportlab PDF — extend it to PNG) and post it to Telegram/Twitter. Users showing real returns is the cheapest viral loop for a trading SaaS and converts the existing PnL engine into a growth surface with almost no new logic.
