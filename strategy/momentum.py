import pandas as pd
import numpy as np
from ..signals.indicators import compute_all, atr
from ..risk.sizer import size_position
from ..data.fetcher import fetch_news_sentiment
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
    """Price closing at or above N-day high."""
    return float(close.iloc[-1]) >= float(close.rolling(window).max().iloc[-2])


def _is_new_low(close: pd.Series, window: int = 20) -> bool:
    """Price closing at or below N-day low."""
    return float(close.iloc[-1]) <= float(close.rolling(window).min().iloc[-2])


def score_momentum(indicators: dict, df: pd.DataFrame) -> tuple[float, str | None]:
    """
    Score a momentum setup 0-100.
    Returns (confidence, direction) or (0, None) if no setup.

    Scoring:
      35 pts  ADX strength (trend is strong)
      25 pts  Price at N-day high/low (breakout confirmation)
      25 pts  RSI in momentum zone (not overbought/oversold)
      15 pts  Volume confirmation
    """
    adx_val = indicators.get("adx", 0)
    rsi_val = indicators.get("rsi", 50)
    close = indicators.get("close_series")
    adx_min = config.get("regime.adx_max", 30.0)  # momentum needs ADX above this

    if adx_val < adx_min:
        return 0.0, None

    # Determine direction from trend slope
    slope = indicators.get("trend_slope", 0)
    if slope > 0:
        direction = "LONG"
    elif slope < 0:
        direction = "SHORT"
    else:
        return 0.0, None

    score = 0.0

    # ── ADX strength (35 pts) ────────────────────────────────────────
    if adx_val >= 50:
        score += 35
    elif adx_val >= 40:
        score += 25
    elif adx_val >= 30:
        score += 15

    # ── Breakout confirmation (25 pts) ──────────────────────────────
    if close is not None:
        if direction == "LONG" and _is_new_high(close):
            score += 25
        elif direction == "SHORT" and _is_new_low(close):
            score += 25
        else:
            score += 8  # trending but not breaking out, partial credit

    # ── RSI momentum zone (25 pts) ──────────────────────────────────
    # Momentum LONG wants RSI 50-75 (strong but not exhausted)
    # Momentum SHORT wants RSI 25-50
    if direction == "LONG" and 50 <= rsi_val <= 75:
        score += 25
    elif direction == "LONG" and 45 <= rsi_val < 50:
        score += 10
    elif direction == "SHORT" and 25 <= rsi_val <= 50:
        score += 25
    elif direction == "SHORT" and 50 < rsi_val <= 55:
        score += 10

    # ── Volume confirmation (15 pts) ────────────────────────────────
    if _volume_confirmation(df):
        score += 15

    return min(score, 100.0), direction


def evaluate(
    ticker: str,
    df: pd.DataFrame,
    portfolio: dict,
) -> dict | None:
    """
    Momentum evaluation pipeline.
    Only called on tickers that FAILED the regime filter (ADX too high).
    Returns signal dict or None.
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

    price = ind["price"]
    capital = portfolio.get("capital", 100_000)
    sizing = size_position(price, ind["atr"], capital)

    if sizing["shares"] == 0:
        return None

    stop = sizing["stop_long"] if direction == "LONG" else sizing["stop_short"]
    target = sizing["target_long"] if direction == "LONG" else sizing["target_short"]

    return {
        "ticker": ticker,
        "strategy": "momentum",
        "skipped": False,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "entry": price,
        "stop": stop,
        "target": target,
        "shares": sizing["shares"],
        "dollar_risk": sizing["dollar_risk"],
        "zscore": ind["zscore"],
        "rsi": ind["rsi"],
        "atr": ind["atr"],
        "adx": ind["adx"],
        "news_pos": 0,
        "news_neg": 0,
        "headlines": [],
    }