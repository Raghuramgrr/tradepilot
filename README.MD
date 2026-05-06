# tradepilot

Autonomous trading agent for equities. Runs two complementary strategies — mean reversion for ranging markets and momentum for trending ones — with full risk management, backtesting, market scanning, and a signal explainer. Switchable between suggest and auto (paper trading) mode at runtime.

No broker connected out of the box. Runs as a paper trader until you wire one in.

---

## how it works

Every ticker goes through this pipeline on each scan:

```
yfinance (OHLCV + news RSS)
        ↓
indicators          Z-score, RSI, Bollinger Bands, ATR, ADX, DI+/DI-
        ↓
regime filter       ADX + VIX + slope check
        ↓
        ├── ranging market  →  mean reversion pipeline
        │     earnings filter → correlation check → signal scorer → MTF confirm
        │
        └── trending market →  momentum pipeline
              DI direction → RSI ceiling check → breakout confirm → volume check
        ↓
risk sizer          fractional Kelly sizing, stop at 2×ATR, target at 3×ATR
        ↓
mode switch         SUGGEST → print alert   |   AUTO → open position, update state
```

State (capital, positions, trade log) persists in `.agent_state.json` between runs.

---

## install

```bash
pip install yfinance pandas numpy scipy rich feedparser pyyaml requests
```

Requires Python 3.11+.

---

## usage

```bash
# from the parent directory of tradepilot/
python -m tradepilot.main                        # scan once, suggest mode
python -m tradepilot.main --mode auto            # scan once, auto mode (paper trades)
python -m tradepilot.main --loop 3600            # scan every hour, starts exit monitor
python -m tradepilot.main --screener             # build watchlist dynamically via screener
python -m tradepilot.main --sim AAPL             # scenario simulation on one ticker
python -m tradepilot.main --backtest             # backtest strategy across full watchlist
python -m tradepilot.main --explain              # show per-ticker gate diagnostics
python -m tradepilot.main --scan                 # scan S&P 500 + Russell 1000 for setups
python -m tradepilot.main --status               # show portfolio, positions, P&L
python -m tradepilot.main --reset                # wipe state, start fresh
```

---

## strategies

**Mean reversion** — the primary strategy. Works in ranging, low-volatility markets. The analogy is a rubber band: the further price stretches from its rolling mean, the stronger the expected snap back. Fires when |Z-score| > 2.0, confirmed by RSI and Bollinger Band position.

**Momentum** — the complementary strategy. Fires on tickers the regime filter rejects as trending. Uses DI+/DI- for direction (more reliable than slope), requires ADX confirmation, and has a hard RSI ceiling to avoid chasing exhausted moves. Does not fire if RSI > 78 (LONG) or < 22 (SHORT).

The two strategies cover opposite market conditions — when one goes quiet, the other picks up the slack.

---

## output

```
  Trader Agent  ● SUGGEST  2026-05-06 09:15

  Capital $100,000  Drawdown 0.00%  Positions 0

  Skipped: GOOGL (ADX=42.5>31.0 trending), AMZN (ADX=40.3>31.0 trending)

  Entry signals:
  Ticker   Signal      Z      RSI    Price    Entry     Stop   Target   Size   Conf
  ─────────────────────────────────────────────────────────────────────────────────
  MCD      LONG     -2.03    29.7  $284.10  $284.10  $273.39  $300.17   35sh    65

  Momentum signals:
  Ticker   Signal      Z      RSI    Price    Entry     Stop   Target   Size   Conf
  ─────────────────────────────────────────────────────────────────────────────────
  XOM      LONG      1.21    61.2  $118.40  $118.40  $112.10  $128.90   18sh    72
```

**Skipped** means the regime filter rejected that ticker for mean reversion. Trending tickers then get evaluated by the momentum strategy instead.

---

## backtesting

```bash
python -m tradepilot.main --backtest
```

Runs a walk-forward simulation on each watchlist ticker using historical data. Reports trades, win rate, average P&L, total P&L, profit factor, and average hold time.

Profit factor is the number to focus on — above 1.0 means winners make more than losers cost. Based on historical results, the strongest tickers for mean reversion are CVS, PFE, BAC, AAPL, and PG.

Set `backtest.lookback_days` in `config.yaml` to control history length. 730 days (2 years) gives statistically meaningful results. 90 days is too short.

---

## screener

```bash
python -m tradepilot.main --screener
```

Replaces the static watchlist with a dynamically generated one. Screens the `screener.universe` list in `config.yaml` for momentum breakout setups — MA alignment, price near N-day high, volume confirmation, and minimum liquidity filters. Falls back to the static watchlist if nothing passes.

Key screener filters in `config.yaml`:

| key | default | what it does |
|-----|---------|--------------|
| `screener.min_price` | 5.0 | skip penny stocks |
| `screener.min_avg_volume` | 500000 | skip illiquid names |
| `screener.min_atr_pct` | 0.01 | skip low-volatility stocks (< 1% ATR) |
| `screener.volume_spike_mult` | 0.8 | volume relative to 20-day avg |
| `screener.breakout_pct` | 0.95 | price must be within 5% of N-day high |

---

## market scanner

```bash
python -m tradepilot.main --scan                  # top 20 setups
python -m tradepilot.main --scan --scan-top 50    # top 50
python -m tradepilot.main --scan --scan-workers 20  # faster with more threads
python -m tradepilot.main --scan --scan-refresh   # force refresh ticker universe
```

Scans the full S&P 500 + Russell 1000 (~1000 stocks) for both mean reversion and momentum setups, ranked by confidence. Takes 3-5 minutes. Results show the top N setups with a suggestion of which to consider adding to your watchlist.

Ticker universe is cached locally in `.ticker_cache.json` and refreshed weekly. Run `--scan-refresh` to force an immediate refresh.

```
  Top 20 setups found across market:

  Rank  Ticker   Strategy        Signal   Conf   Price      Z     RSI   ADX   Why
  ────────────────────────────────────────────────────────────────────────────────
     1  CELH    mean reversion   LONG      82   $38.21   -2.84   27.3  12.1  |Z|=2.84 RSI=27.3
     2  SMCI    momentum         LONG      78  $812.00    1.21   63.4  44.2  ADX=44.2 RSI=63.4

  Mean reversion: 13    Momentum: 7
  Top 5 to consider adding to watchlist: CELH, SMCI, DXCM, MELI, CROX
```

---

## signal explainer

```bash
python -m tradepilot.main --explain
```

Shows exactly why each ticker passed or failed every gate in the pipeline. Useful for understanding why no signals are firing or for tuning thresholds.

```
  Ticker   Result     Failed at            Z      RSI    ADX    Conf  Note
  ────────────────────────────────────────────────────────────────────────────
  AAPL     no_setup   zscore_threshold   1.84    38.2   18.3    45   ⚡ near miss
  MSFT     skipped    regime_adx          —      52.1   33.4    —    ADX=33.4 > 31.0
  CVS      signal     —                 -2.31    28.4   14.2    72   ✓ signal fired

  Near misses — almost triggered:
    ⚡ AAPL  zscore_threshold: value=1.84  threshold=2.0  (8.0% away)
```

**Near misses** are tickers within 15% of a threshold — worth watching as they may trigger on the next scan.

---

## exit monitor

When running with `--loop`, a background thread watches all open positions every 60 seconds for stop-loss hits or take-profit targets using live prices. In auto mode it closes positions immediately. In suggest mode it prints an alert.

```bash
python -m tradepilot.main --loop 3600 --mode auto
```

Monitor interval is configurable: `monitor.interval_seconds` in `config.yaml`.

---

## scenario simulation

```bash
python -m tradepilot.main --sim NVDA
```

Runs a Monte Carlo simulation (1000 paths, 15-day horizon) on a single ticker showing probability of hitting target vs stop, average expected hold time, and how position size scales across different capital levels.

---

## tuning

Everything lives in `config.yaml`. The levers that matter most:

| key | default | what it does |
|-----|---------|--------------|
| `signals.zscore_entry` | 2.0 | how far from mean before a signal fires |
| `signals.min_confidence` | 60 | minimum score (0–100) to surface a trade |
| `regime.adx_max` | 31.0 | trending/ranging market boundary |
| `regime.vix_max` | 35.0 | halt all signals if VIX spikes above this |
| `momentum.rsi_ceiling` | 78.0 | reject momentum LONG if RSI above this |
| `momentum.rsi_floor` | 22.0 | reject momentum SHORT if RSI below this |
| `risk.max_position_pct` | 0.10 | max 10% of capital per position |
| `risk.kelly_fraction` | 0.25 | fractional Kelly (conservative) |
| `risk.stop_loss_atr_mult` | 2.0 | stop = entry ± 2×ATR |
| `risk.max_open_positions` | 6 | hard cap on concurrent positions |
| `risk.max_portfolio_dd` | 0.08 | halt new trades if drawdown exceeds 8% |
| `earnings.buffer_days` | 5 | skip ticker if earnings within N days |
| `correlation.max_r` | 0.75 | reject if correlated with open position |
| `backtest.lookback_days` | 730 | history window for backtesting |

---

## adding a real broker

In `execution/router.py`, inside the `if mode == "auto":` block in `route()`, add your broker call before `context.open_position(...)`.

**Alpaca** (free paper trading sandbox):
```python
import alpaca_trade_api as tradeapi
api = tradeapi.REST(API_KEY, SECRET_KEY, base_url='https://paper-api.alpaca.markets')
api.submit_order(symbol=ticker, qty=shares, side='buy', type='market', time_in_force='day')
```

**Interactive Brokers** via ib_insync:
```python
from ib_insync import IB, MarketOrder, Stock
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
trade = ib.placeOrder(Stock(ticker, 'SMART', 'USD'), MarketOrder('BUY', shares))
```

---

## file structure

```
tradepilot/
├── main.py                 entrypoint, CLI, agent loop
├── config.py               config loader (dot-notation access)
├── config.yaml             all tunable parameters
├── data/
│   ├── fetcher.py          yfinance OHLCV + Yahoo Finance news RSS
│   ├── calendar.py         earnings date lookup — filters risky setups
│   ├── screener.py         momentum breakout screener — dynamic watchlist
│   ├── scanner.py          whole-market parallel scanner
│   └── universe.py         S&P 500 + Russell 1000 universe, cached weekly
├── signals/
│   ├── indicators.py       Z-score, RSI, Bollinger Bands, ATR, ADX, DI+/DI-
│   ├── regime.py           VIX + ADX + slope regime filter
│   ├── scorer.py           mean reversion confidence scoring (0–100)
│   ├── correlation.py      correlation check against open positions
│   ├── mtf.py              weekly timeframe confirmation
│   └── explainer.py        per-ticker gate diagnostics and near-miss detection
├── strategy/
│   ├── mean_reversion.py   entry/exit logic, assembles full pipeline
│   ├── momentum.py         momentum strategy — DI+/DI-, RSI ceiling, breakout
│   ├── backtest.py         walk-forward backtest + universe summary
│   └── simulator.py        Monte Carlo scenario sim, capital scaling
├── risk/
│   ├── sizer.py            Kelly position sizing, portfolio limit checks
│   └── monitor.py          background exit monitor thread
├── execution/
│   └── router.py           mode switch — suggest vs auto
└── memory/
    └── context.py          state persistence (JSON), trade log
```

---

## what this doesn't do (yet)

Transaction costs are not modelled in the backtest — results are slightly optimistic. Walk-forward validation (train/test split) is not implemented — current backtest is in-sample. No maximum hold time — positions can stay open indefinitely if neither stop nor target is hit. No market hours awareness — signals can fire outside trading hours.

---

## disclaimer

This is a research and paper trading tool. Not financial advice. Past signals do not guarantee future performance. Always validate a strategy thoroughly before trading real capital.