# TradePilot

Autonomous mean reversion trading agent for equities. Scans a watchlist, identifies statistically oversold/overbought setups, sizes positions with risk controls, and either suggests trades or executes them — switchable at runtime.

No broker connected out of the box. Runs as a paper trader until you wire one in.

---

## how it works

Every ticker goes through this pipeline on each scan:

```
yfinance (OHLCV)
      ↓
indicators       Z-score, RSI, Bollinger Bands, ATR, ADX
      ↓
regime filter    skip if ADX > threshold or VIX too high (trending market = wrong conditions)
      ↓
signal scorer    confidence 0–100 across Z-score magnitude, RSI, BB touch, news sentiment
      ↓
risk sizer       fractional Kelly sizing, stop at 2×ATR, target at 3×ATR
      ↓
mode switch      SUGGEST → print alert   |   AUTO → open position, update state
```

State (capital, positions, trade log) persists in `.agent_state.json` between runs.

---

## install

```bash
pip install yfinance pandas numpy scipy rich feedparser pyyaml
```

Requires Python 3.11+.

---

## usage

```bash
# from the parent directory of tradepilot/
python -m tradepilot.main                   # scan once, suggest mode
python -m tradepilot.main --mode auto       # scan once, auto mode (paper trades)
python -m tradepilot.main --loop 3600       # scan every hour
python -m tradepilot.main --sim AAPL        # scenario simulation on one ticker
python -m tradepilot.main --status          # show portfolio, positions, P&L
python -m tradepilot.main --reset           # wipe state, start fresh
```

---

## output

```
  Trader Agent  ● SUGGEST  2026-05-05 11:38

  Capital $100,000  Drawdown 0.00%  Positions 0

  Skipped: GOOGL (ADX=42.5>30.0 trending), AMZN (ADX=41.1>30.0 trending)

  Ticker   Signal      Z      RSI    Price    Entry     Stop   Target   Size   Conf
  ─────────────────────────────────────────────────────────────────────────────────
  MCD      LONG     -2.03    29.7  $284.10  $284.10  $273.39  $300.17   35sh    65
```

**Skipped** means the regime filter rejected that ticker — ADX too high (trending market, wrong conditions for mean reversion). Not a bug.

A signal appears only when: regime is ok AND |Z-score| > 2.0 AND confidence ≥ 60.

---

## tuning

Everything lives in `config.yaml`. The levers that matter most:

| key | default | what it does |
|-----|---------|--------------|
| `signals.zscore_entry` | 2.0 | how far from mean before a signal fires |
| `signals.min_confidence` | 60 | minimum score (0–100) to surface a trade |
| `regime.adx_max` | 30.0 | reject trending tickers above this ADX |
| `regime.vix_max` | 35.0 | halt all signals if VIX spikes above this |
| `risk.max_position_pct` | 0.10 | max 10% of capital per position |
| `risk.kelly_fraction` | 0.25 | fractional Kelly (conservative) |
| `risk.stop_loss_atr_mult` | 2.0 | stop = entry ± 2×ATR |
| `risk.max_open_positions` | 6 | hard cap on concurrent positions |
| `risk.max_portfolio_dd` | 0.08 | halt new trades if drawdown exceeds 8% |

For mean reversion to fire, you want range-bound tickers. Consumer staples, telcos, and utilities work better than trending mega-cap tech. The default watchlist includes both — adjust to taste.

---

## adding a real broker

In `execution/router.py`, inside the `if mode == "auto":` block in `route()`, add your broker call before `context.open_position(...)`.

**Alpaca** (has a free paper trading sandbox at paper-api.alpaca.markets):
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
│   └── fetcher.py          yfinance OHLCV + Yahoo Finance news RSS
├── signals/
│   ├── indicators.py       Z-score, RSI, Bollinger Bands, ATR, ADX
│   ├── regime.py           VIX + ADX regime filter
│   └── scorer.py           confidence scoring (0–100)
├── strategy/
│   ├── mean_reversion.py   entry/exit logic, assembles pipeline
│   └── simulator.py        Monte Carlo scenario sim, capital scaling
├── risk/
│   └── sizer.py            Kelly position sizing, portfolio limit checks
├── execution/
│   └── router.py           mode switch — suggest vs auto
└── memory/
    └── context.py          state persistence (JSON), trade log
```

---

## disclaimer

This is a research and paper trading tool. Not financial advice. Past signals do not guarantee future performance. Always validate a strategy thoroughly before trading real capital.