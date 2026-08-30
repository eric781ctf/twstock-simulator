> 🌐 中文版說明: [README.md](README.md)

# Taiwan Stock Odd-Lot Trading Simulator

A **odd-lot (零股) trading simulator** for the Taiwan stock market, driven by real market quotes. Practice placing limit orders, watch order matching happen, and track cash/position changes — no real money and no real orders are ever involved. It's a sandbox for getting comfortable with how Taiwan odd-lot trading actually works.

## What this is

- Uses real, live quotes from Taiwan's stock exchanges (TWSE for listed stocks, TPEx for OTC stocks) to drive simulated order matching — not random or replayed data.
- Orders are genuine **limit orders**: a buy fills only when the traded price ≤ your limit, a sell fills only when the traded price ≥ your limit. Fills are not guaranteed.
- Each account is an independent simulated portfolio, starting with NT$1,000,000 in cash.
- Commission (0.1425%) and the sell-side securities transaction tax (0.3%) are calculated automatically.
- A background job polls quotes and attempts to match pending orders every few seconds (default: 7s) during odd-lot trading hours (09:00–13:30, Mon–Fri, Taipei time).

> ⚠️ **This project is for learning and practice only. It is not a real trading system and does not constitute investment advice.**

## Features

- **Login / register**: each user has an independent account, cash balance, and holdings.
- **Home**: a candlestick + price-trend chart block for every stock currently held.
- **Search**: look up any stock by code, view a large candlestick/intraday chart plus fundamentals (P/E ratio, dividend yield, P/B ratio, with ~2–3 years of monthly history), and add/remove it from your watchlist directly.
- **Trade**: an order panel (buy/sell, code, quantity, limit price) plus pending-order and filled-order tables.
- **Trade history**: full record of executed trades, including commission and tax.
- **Positions**: a dedicated tab for current holdings and unrealized P&L.
- **Market tutorials**: topic-based sub-pages covering candlestick basics, moving averages, price-volume relationships, the KD indicator, how to read fundamentals, ex-dividend/ex-rights mechanics, odd-lot trading rules, fees & tax, and the order lifecycle.
- **Charts**: daily candlestick charts overlay 5/20/60-day moving averages (weekly/monthly/quarterly); intraday charts render correctly in Asia/Taipei time.
- **Watchlist**: watchlisted stocks get continuous intraday tracking for the day; a searched stock outside the watchlist with no intraday data yet instead shows a link to its Yahoo奇摩股市 page.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python + FastAPI + SQLAlchemy 2.0 + APScheduler |
| Database | PostgreSQL 16 |
| Frontend | React + TypeScript + Vite + react-router-dom |
| Charts | lightweight-charts |
| Auth | JWT (PyJWT) + bcrypt |
| Containerization | Docker Compose |

On each poll interval (`TWSTOCK_POLL_INTERVAL_SECONDS`), the backend batches every stock code it currently needs a quote for (pending orders, held positions, watchlist items) into a single request to TWSE's public quote endpoint, then attempts to match pending orders against the latest price. Any order still pending after market close is automatically expired and its reserved cash/shares released.

## Getting started

### Requirements

- Docker and Docker Compose

### Steps

1. Copy the example env file and fill in your own values:

   ```bash
   cp .env.example .env
   ```

   Edit `.env` and set `POSTGRES_PASSWORD` and `TWSTOCK_JWT_SECRET` to random strings (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`). **`TWSTOCK_JWT_SECRET` has no default — the backend fails to start without it.**

2. Start everything:

   ```bash
   docker compose up -d --build
   ```

3. Open in a browser:
   - Frontend: http://localhost:5173
   - Backend API docs (Swagger): http://localhost:8000/docs

4. Register an account from the frontend to get started — every new account starts with NT$1,000,000 in simulated cash.

### Environment variables (`.env`)

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password | must be set |
| `TWSTOCK_JWT_SECRET` | JWT signing secret | **required, no default** |
| `TWSTOCK_INITIAL_CASH` | Starting cash for new accounts | 1,000,000 |
| `TWSTOCK_POLL_INTERVAL_SECONDS` | Order-matching poll interval (seconds) | 7 |
| `TWSTOCK_TRADING_START` / `TWSTOCK_TRADING_END` | Odd-lot trading hours | 09:00 / 13:30 |

## Project structure

```
backend/
  app/
    main.py            # FastAPI entrypoint, scheduled jobs
    config.py           # Environment-based settings
    models.py           # SQLAlchemy tables
    schemas.py           # Pydantic schemas
    routers/             # API routes (auth, stocks, account, positions, orders, trades, market_data, watchlist)
    services/
      matching.py        # Order matching logic, trading-hours checks
      twse_client.py      # TWSE / TPEx quote and historical data clients
      stock_sync.py        # Stock list and fundamentals sync/backfill
frontend/
  src/
    pages/               # Home, Search, Trade, Trade History, Positions, Tutorials, Login
    components/           # Charts, tables, order panel, etc.
    hooks/, lib/, api.ts  # Data fetching and helpers
docker-compose.yml
.env.example
```

## Known limitations

- TPEx (OTC) stocks have no official historical-data API, so daily candlesticks and fundamentals history for OTC stocks only accumulate day-by-day from whenever the app was first run. TWSE (listed) stocks get a full recent backfill instead.
- Intraday charts are only tracked continuously for watchlisted stocks. A searched stock that isn't watchlisted and has no intraday data yet shows a link to Yahoo奇摩股市 instead.
- Quotes come from a public, unofficial real-time quote endpoint, which can lag or occasionally be unavailable — this is not suitable for any real trading decision.
- This system never touches real money and never connects to a brokerage; it's a local simulation only.

## License

For personal learning and practice use only.
