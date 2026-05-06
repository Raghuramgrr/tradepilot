"""
Run this from your repo root to see exactly which condition
is killing each ticker in the screener.

    python diagnose_screener.py
"""
import yfinance as yf
import pandas as pd

TICKERS = ["AAPL", "MSFT", "NVDA", "META", "JPM", "SPY", "QQQ"]

# Thresholds — match your config.yaml
MIN_PRICE      = 5.0
MIN_AVG_VOL    = 500_000
MIN_ATR_PCT    = 0.01
VOL_SPIKE_MULT = 0.8
BREAKOUT_PCT   = 0.95

for ticker in TICKERS:
    df = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if len(df) < 30:
        print(f"{ticker}: not enough bars")
        continue

    close  = df["Close"].squeeze()
    high   = df["High"].squeeze()
    low    = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    latest_close = float(close.iloc[-1])
    latest_vol   = float(volume.iloc[-1])
    avg_vol_20   = float(volume.rolling(20).mean().iloc[-1])
    avg_vol_5    = float(volume.rolling(5).mean().iloc[-1])

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.rolling(14).mean().iloc[-1]) / latest_close

    ma5  = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])

    trend     = latest_close > ma20 and ma5 > ma10 > ma20
    momentum  = latest_close > float(close.rolling(10).max().shift(1).iloc[-1])
    breakout  = latest_close >= BREAKOUT_PCT * float(high.rolling(20).max().iloc[-1])
    vol_spike = latest_vol > VOL_SPIKE_MULT * avg_vol_5

    fails = []
    if latest_close < MIN_PRICE:       fails.append(f"price ${latest_close:.2f} < ${MIN_PRICE}")
    if avg_vol_20 < MIN_AVG_VOL:       fails.append(f"avg_vol {avg_vol_20:,.0f} < {MIN_AVG_VOL:,.0f}")
    if atr_pct < MIN_ATR_PCT:          fails.append(f"atr {atr_pct:.2%} < {MIN_ATR_PCT:.0%}")
    if not trend:                      fails.append(f"trend FAIL (ma5={ma5:.1f} ma10={ma10:.1f} ma20={ma20:.1f})")
    if not (momentum or breakout):     fails.append(f"no momentum/breakout")
    if not vol_spike:                  fails.append(f"vol spike FAIL ({latest_vol:,.0f} vs {VOL_SPIKE_MULT}x{avg_vol_5:,.0f})")

    status = "PASS" if not fails else "FAIL"
    print(f"\n{ticker}  [{status}]  price=${latest_close:.2f}  atr={atr_pct:.2%}  avg_vol={avg_vol_20:,.0f}")
    if fails:
        for f in fails:
            print(f"  ✗ {f}")
    else:
        print(f"  ✓ trend={trend}  momentum={momentum}  breakout={breakout}  vol_spike={vol_spike}")