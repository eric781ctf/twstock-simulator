> 🌐 中文版本：[README.md](README.md)

# Taiwan Stock AI Stock-Picking System

Trains machine-learning models on real Taiwan Stock Exchange history, picks ten stocks after the close on every trading day, decides when to exit, and lays every result out for inspection. **The point is not to make money — it is to make "does this model actually work?" measurable, visible, and falsifiable.**

> ⚠️ **For learning and research only. Not investment advice, and not connected to any broker.** The signal measured so far is weak (see "Where it stands" below); trading on it would lose money.

## What this is

- **Not** a trading simulator, and there is no virtual cash. The system records only the **net return percentage** of each holding (after 0.1425% commission and 0.3% transaction tax), because a model's quality has nothing to do with how much money you put in, and fake virtual cash just makes people mistake it for real performance.
- **TWSE-listed stocks only** — no TPEx, no emerging board.
- Each training run produces an **immutable model version**. Versions can be archived (stops daily picking, keeps the history) or deleted.
- Visitors **do not need to log in** to browse every model's parameters, metrics, charts and holdings. Only training and administration require an admin login.

## How the models work

**Dual-task**: one feature set trains two heads — a regression head predicting the return over the next N trading days, and a classification head predicting whether that return clears a threshold. For the traditional ML types these are two independently trained models sharing one feature matrix; for the neural types they genuinely share an encoder and branch into two heads.

**Selection score**: each output is **z-scored across that day's cross-section**, then combined as a weighted average (weights are configurable). An earlier "expected return × probability" formula was removed — it multiplies inflated probabilities straight into the score, and probability is exactly the least reliable part of these models.

**Exit rules**, four layers in order: max holding days → stop-loss / take-profit → minimum holding days (before which nothing else is even checked) → rule conditions (reusing the existing KD / moving-average / streak condition engine). Backtest and live both call the same `exit_rules.py`, so the two cannot quietly drift apart.

**Daily schedule**: at 15:00 on each trading day, every completed and unarchived model runs once — first deciding whether to sell what it holds, then buying the top 10 by score from the whole market. Each run's duration is recorded.

### Available model types

| Type | Notes |
|---|---|
| XGBoost / LightGBM / Random Forest | Tree models. Trees, depth, learning rate, sampling ratios, min child samples and `n_jobs` are all adjustable |
| Logistic / Linear Regression | Linear models. Coefficients are signed, so direction is visible |
| MLP / GRU / LSTM | PyTorch, **GPU required**. Layers, widths, activation, dropout, learning rate, epochs, batch size and sequence length are adjustable, with early stopping and best-weight restoration |

The neural path deliberately **fails loudly** when GPU is configured but unavailable rather than silently falling back to CPU — otherwise you would think you were training on a GPU while running far slower without noticing.

## Feature engineering

**112 features** at present, all strictly limited to information known once that trading day has closed. Avoiding look-ahead is the single most important thing here: one feature that peeks into the future makes the backtest look wonderful and the live system worthless.

| Source | Contents |
|---|---|
| Price / volume | Candle geometry, 4 windows (5/10/20/60) × 7 rolling operators, MA deviation, volume ratio, streaks. Modelled on Qlib's Alpha158 |
| Technical | KD (shares one implementation with the strategy engine) |
| Valuation | P/E, dividend yield, P/B. Monthly snapshots joined with `merge_asof` taking the last row not later than the feature date |
| Market | Index return (1/5/20 day), market breadth, index MA deviation, plus each stock's strength relative to the market |
| Institutional flows | Foreign / trust / total institutional net buying, margin balance change, foreign holding ratio and its 20-day change (TWSE T86 / MI_MARGN / MI_QFIIS) |
| Shareholder distribution | Large / mid / retail holder share and 4-week changes (TDCC, **weekly**) |
| Industry | Industry one-hot columns (TWSE listed-company profile). 1093 of 1382 securities are classified; the rest are ETFs and beneficiary certificates |

The weekly shareholder data is joined with `allow_exact_matches=False` so the match is **strictly before** the feature date — Friday's snapshot is published on Saturday, and `<=` would let Friday's features see numbers that had not been released yet.

Four presets: **Curated** (19, hand-picked with low mutual overlap) / **Curated + industry** (57) / **Alpha158 lite** (all 112) / **Price-volume only** (50, as a control).

### Cross-sectional handling

Stock picking asks "which of today's ~1300 names are relatively strong", so the goal is not precision but comparability within a day. All three options are same-day cross-sectional operations and never look ahead:

- **Cross-sectional rank**: replaces each feature with its percentile across that day's market. Better than z-score because it never compares last year's values against this year's.
- **Excess-return label**: subtracts the market return over the same window, asking "will it beat the market" rather than "will it go up".
- **Industry neutralization**: subtracts the same-day, same-industry median. **Measured as harmful; off by default** (see below).

Market features and industry one-hot columns are always excluded from these operations — they are either constant across a day or 0/1 indicators, so ranking would give the whole market one rank and subtracting a median would zero the column out.

## Validation

A single split (one train/validation/test partition) mostly measures what the market happened to do during that one test window. The default is therefore **walk-forward validation**: the history is cut into several folds, each shifted forward by a fixed number of months, each trained and scored on its own, and the result is reported as mean and standard deviation. Scaler parameters are fit per fold, never shared.

**How many folds came out positive matters more than the mean** — a high mean with only three positive folds just means one fold was unusually good.

## Where it stands

Best configuration so far (LightGBM, 5-day horizon, excess return, cross-sectional rank, 19 curated features, 6 folds):

```
Test Rank IC  +0.0651 ± 0.0145   6/6 folds positive
Test AUC      0.5985
```

Industry multi-factor signals that hold 0.03–0.05 over the long run are considered usable, so this is **not meaningless — but nowhere near usable either**: the same configuration's backtest still averages a negative return once the ~0.6% round-trip cost is deducted.

Things that were measured and **did not work**, recorded so they are not retried blindly:

| Approach | Result |
|---|---|
| Industry neutralization | +0.065 → **+0.039**, and the training score fell too, meaning it removed real signal |
| Industry one-hot | +0.072, but the standard deviation doubled, only 4 of 6 folds improved, paired t=0.69 — indistinguishable from noise |
| Foreign holding ratio and other stock-level flows | Ranked most important in the whole model, yet training score rose while test score fell — a feature the model loves but cannot extrapolate from |
| TDCC shareholder distribution | **Could not be evaluated**: every fold's training window ends before the data begins, so the columns are 100% empty during training |

## Pages

| Path | Contents |
|---|---|
| `/` | Model list: status, training duration, realized and unrealized average return |
| `/models/:id` | Model detail: training parameters, per-fold metrics, four charts (predicted vs actual scatter, probability calibration curve, trade-return scatter, feature importance), current and past holdings |
| `/tutorial` | Market basics: candles, moving averages, volume, KD, fundamentals, dividends, fees and taxes |
| `/model-tutorial` | Model tutorial: business logic (score computation, exit rules, feature handling, why walk-forward) plus the theory behind each model type |
| `/admin` | Data panel: coverage and backfill triggers for daily bars, institutional flows, shareholder distribution and industry; scheduler switches |
| `/admin/models` | Training form, model version list, training progress and queue position |

## Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2.0 + APScheduler |
| Machine learning | scikit-learn, XGBoost, LightGBM, PyTorch 2.5 (CUDA 12.4) |
| Data processing | NumPy + pandas (the feature pipeline is fully vectorized) |
| Database | PostgreSQL 16 |
| Frontend | React + TypeScript + Vite |
| Charts | lightweight-charts plus hand-written SVG (the scatter and calibration charts do not have a time X axis) |
| Containers | Docker Compose |

Training runs in a `ProcessPoolExecutor(max_workers=1)`, so **only one model trains at a time** and concurrent requests queue up — this keeps the FastAPI event loop free and prevents two training runs from competing for memory. On restart, interrupted runs are marked failed and not-yet-started ones are re-queued.

## Getting started

### Requirements

- Docker and Docker Compose
- **An NVIDIA GPU plus the NVIDIA Container Toolkit** — only needed to train MLP / GRU / LSTM. Without one, remove the `deploy.resources` block from the backend service in `docker-compose.yml`; tree and linear models work as usual.

### Steps

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

   Set `POSTGRES_PASSWORD` and `TWSTOCK_JWT_SECRET` to random strings (`python -c "import secrets; print(secrets.token_urlsafe(32))"`). **`TWSTOCK_JWT_SECRET` has no default — the backend refuses to start without it.** Also change `TWSTOCK_ADMIN_PASSWORD` from the default `admin`.

2. Start everything:

   ```bash
   docker compose up -d --build
   ```

   The first build pulls the PyTorch CUDA wheel, roughly 2.5GB.

3. Open:
   - Frontend http://localhost:5173
   - API docs http://localhost:8000/docs

4. Log in with the admin credentials from `.env`, go to `/admin` and backfill daily bars and institutional flows first (**do not skip this** — without enough history there is nothing to train on), then submit the first training run from `/admin/models`.

### Environment variables (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password | must be set |
| `TWSTOCK_JWT_SECRET` | JWT signing key | **required, no default** |
| `TWSTOCK_ADMIN_USERNAME` / `TWSTOCK_ADMIN_PASSWORD` | Admin credentials | `admin` / `admin` (**change these**) |
| `TWSTOCK_CORS_ORIGIN_REGEX` | Only needed to reach the app from another device; localhost-only by default | empty |

`.env.example` also carries `TWSTOCK_INITIAL_CASH`, `TWSTOCK_POLL_INTERVAL_SECONDS`, `TWSTOCK_TRADING_START` / `TWSTOCK_TRADING_END` and a few others — leftovers from the odd-lot simulator that have no effect on this system.

For access from outside the local network, use something like Tailscale rather than exposing the port directly — this system has had no hardening for public exposure.

## Project layout

```
backend/app/
  main.py                   # FastAPI entry point, startup, queue recovery
  models.py / schemas.py    # Tables and API schemas
  routers/
    models.py                 # Admin: create training, archive, delete
    public_models.py          # Public: model list and detail (no login)
    admin.py                  # Data backfill and scheduler switches
  services/
    ml/
      features.py               # Feature assembly (vectorized)
      price_features.py         # Rolling price/volume features
      dataset.py                # Labels, splits, rank normalization, industry neutralization
      train.py                  # Model construction per type, score combination
      torch_models.py           # PyTorch dual-task networks (MLP / GRU / LSTM)
      walk_forward.py           # Fold generation and summarization
      training_runner.py        # Background training, queue, progress reporting
      exit_rules.py             # Exit decisions (shared by backtest and live)
      selection.py              # Daily selection cycle
      backtest_eval.py          # Backtest and metric computation
      inference.py              # Live post-close selection
    chip_sync.py / shareholding_sync.py / industry_sync.py
    twse_client.py / stock_sync.py / history.py
frontend/src/
  pages/                    # ModelsPage, ModelDetailPage, AdminModelsPage, ModelTutorialPage…
  components/               # Chart components (scatter, calibration, feature importance)
docker-compose.yml
```

## Known limitations

- **Industry classification has no history.** TWSE only publishes the current mapping, so earlier samples are labelled with today's classification. Industries rarely change, which makes this an acceptable approximation — but it is an approximation.
- **Shareholder distribution can only accumulate going forward.** TDCC's open-data endpoint serves the latest week only, with no historical query.
- **The sample period is still short.** Roughly two years of daily bars; the six walk-forward folds have heavily overlapping training windows, so the standard deviation is not a confidence interval.
- **Memory, not CPU, is the bottleneck.** Features are a list of dicts — one row with 115 keys costs about 6KB, so 650k rows come to roughly 3.7GB (the same numbers in a float64 matrix would be 0.56GB). Check headroom before raising `n_jobs`.
- The original odd-lot trading simulator (order entry, matching, watchlist, leaderboard, ordinary user accounts) has been fully retired. Its code and tables remain in the repository but are no longer exposed; some services (fee calculation, technical indicators, the condition engine) are reused internally by the new system.

## License

For personal learning and research only.
