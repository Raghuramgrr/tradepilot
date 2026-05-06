import pandas as pd
import numpy as np
from ..signals.indicators import compute_all, atr
from ..risk.sizer import size_position
from .. import config
from ..utils.display import get_logger

log = get_logger(__name__)


def _volume_confirmation(df: pd.DataFrame, window: int = 20) -> bool:
    """Volume on recent bars above rolling average — confirms conviction."""
    vol = df["Volume"].squeeze()
    if len(vol) < window:
        return False
    avg_vol = float(vol.rolling(window).mean().iloc[-1])
    recent_vol = float(vol.iloc[-1])
    return recent_vol > avg_vol * 1.2


def _is_new_high(close: pd.Series, window: int = 20) -> bool:
    """Price closing above the prior bar's N-day rolling high (no look-ahead)."""
    prior_high = close.rolling(window).max().shift(1)
    return float(close.iloc[-1]) > float(prior_high.iloc[-1])


def _is_new_low(close: pd.Series, window: int = 20) -> bool:
    """Price closing below the prior bar's N-day rolling low (no look-ahead)."""
    prior_low = close.rolling(window).min().shift(1)
    return float(close.iloc[-1]) < float(prior_low.iloc[-1])


def _directional_bias(df: pd.DataFrame, window: int = 14) -> str | None:
    """
    Use DI+ vs DI- to confirm trend direction — more reliable than slope alone.
    Returns 'LONG', 'SHORT', or None if no clear bias.
    """
    high = df["High"].squeeze()
    low  = df["Low"].squeeze()
    close = df["Close"].squeeze()

    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    up_move   = high - prev_high
    down_move = prev_low - low

    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_s    = tr.ewm(alpha=1 / window, adjust=False).mean()
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(alpha=1 / window, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / window, adjust=False).mean() / atr_s

    p = float(plus_di.iloc[-1])
    m = float(minus_di.iloc[-1])
    gap = abs(p - m)

    # Require a meaningful gap between DI+ and DI- to confirm direction
    # Avoids choppy markets where they're nearly equal
    if gap < 5:
        return None

    return "LONG" if p > m else "SHORT"


def score_momentum(indicators: dict, df: pd.DataFrame) -> tuple[float, str | None]:
    """
    Score a momentum setup 0-100.
    Returns (confidence, direction) or (0, None) if no setup.

    Scoring:
      35 pts  ADX strength
      25 pts  Breakout confirmation (new N-day high/low) — no partial credit
      25 pts  RSI in momentum zone
      15 pts  Volume confirmation

    Hard gates (return 0 immediately if failed):
      - ADX below minimum
      - No clear DI direction
      - RSI exhausted (above ceiling for LONG, below floor for SHORT)
      - Breakout AND momentum both absent
    """
    adx_val  = indicators.get("adx", 0)
    rsi_val  = indicators.get("rsi", 50)
    close    = indicators.get("close_series")

    adx_min   = config.get("momentum.adx_min", 31.0)
    rsi_ceil  = config.get("momentum.rsi_ceiling", 78.0)
    rsi_floor = config.get("momentum.rsi_floor", 22.0)
    bk_win    = config.get("momentum.breakout_window", 20)

    # ── Hard gate 1: ADX must confirm a trend ───────────────────────
    if adx_val < adx_min:
        return 0.0, None

    # ── Hard gate 2: DI+/DI- must agree on direction ─────────────────
    direction = _directional_bias(df)
    if direction is None:
        return 0.0, None

    # ── Hard gate 3: RSI exhaustion — don't chase extended moves ────
    if direction == "LONG"  and rsi_val > rsi_ceil:
        return 0.0, None
    if direction == "SHORT" and rsi_val < rsi_floor:
        return 0.0, None

    # ── Hard gate 4: must have actual breakout or momentum ──────────
    # No partial credit — if price isn't confirming the trend, skip it
    has_breakout = False
    has_momentum = False
    if close is not None:
        has_breakout = _is_new_high(close, bk_win) if direction == "LONG" else _is_new_low(close, bk_win)
        # Momentum: price above its own 10-day EMA with conviction
        ema10 = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
        has_momentum = (close.iloc[-1] > ema10 * 1.005) if direction == "LONG" else (close.iloc[-1] < ema10 * 0.995)

    if not has_breakout and not has_momentum:
        return 0.0, None

    # ── Scoring ──────────────────────────────────────────────────────
    score = 0.0

    # ADX strength (35 pts)
    if adx_val >= 50:
        score += 35
    elif adx_val >= 40:
        score += 25
    elif adx_val >= 31:
        score += 15

    # Breakout confirmation (25 pts) — full points only for actual breakout
    if has_breakout:
        score += 25
    elif has_momentum:
        score += 12   # trend continuation without new high, reduced credit

    # RSI momentum zone (25 pts)
    if direction == "LONG":
        if 52 <= rsi_val <= 68:
            score += 25   # ideal zone
        elif 45 <= rsi_val < 52 or 68 < rsi_val <= rsi_ceil:
            score += 12   # acceptable but not ideal
    else:  # SHORT
        if 32 <= rsi_val <= 48:
            score += 25
        elif rsi_floor <= rsi_val < 32 or 48 < rsi_val <= 55:
            score += 12

    # Volume confirmation (15 pts)
    if _volume_confirmation(df):
        score += 15

    return min(score, 100.0), direction


def evaluate(ticker: str, df: pd.DataFrame, portfolio: dict) -> dict | None:
    """
    Momentum evaluation pipeline.
    Only called on tickers that FAILED the regime filter (ADX too high).
    """
    min_conf = config.get("signals.min_confidence", 60)

    try:
        ind = compute_all(df)
    except Exception as e:
        log.warning(f"{ticker} momentum: indicator compute failed — {e}")
        return None

    confidence, direction = score_momentum(ind, df)

    if confidence < min_conf or direction is None:
        return None

    # Skip if already in this position
    existing = portfolio.get("positions", {}).get(ticker)
    if existing and existing["direction"] == direction:
        return None

    price   = ind["price"]
    capital = portfolio.get("capital", 100_000)
    sizing  = size_position(price, ind["atr"], capital)

    if sizing["shares"] == 0:
        return None

    stop   = sizing["stop_long"]   if direction == "LONG" else sizing["stop_short"]
    target = sizing["target_long"] if direction == "LONG" else sizing["target_short"]

    return {
        "ticker":      ticker,
        "strategy":    "momentum",
        "skipped":     False,
        "direction":   direction,
        "confidence":  confidence,
        "price":       price,
        "entry":       price,
        "stop":        stop,
        "target":      target,
        "shares":      sizing["shares"],
        "dollar_risk": sizing["dollar_risk"],
        "zscore":      ind["zscore"],
        "rsi":         rsi_val if (rsi_val := ind["rsi"]) else ind["rsi"],
        "atr":         ind["atr"],
        "adx":         ind["adx"],
        "news_pos":    0,
        "news_neg":    0,
        "headlines":   [],
    }