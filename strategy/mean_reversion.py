import pandas as pd
from .. import config
from ..signals.indicators import compute_all
from ..signals.regime import check_regime
from ..signals.scorer import score_signal
from ..risk.sizer import size_position
from ..data.fetcher import fetch_news_sentiment
from ..utils.display import get_logger
from ..data.calendar import is_near_earnings
from ..signals.correlation import is_too_correlated
log = get_logger(__name__)


def evaluate(ticker: str, df: pd.DataFrame, vix: float | None,
             portfolio: dict) -> dict | None:
    """
    Full evaluation pipeline for one ticker.
    Returns a signal dict ready for the router, or None if no setup found.
    """
    min_conf = config.get("signals.min_confidence", 60)

    # ── 1. Compute all indicators ────────────────────────────────────
    try:
        ind = compute_all(df)
    except Exception as e:
        log.warning(f"{ticker}: indicator compute failed — {e}")
        return None

    # ── 2. Regime filter ─────────────────────────────────────────────
    regime_ok, regime_reason = check_regime(ind, vix)
    if not regime_ok:
        return {"ticker": ticker, "skipped": True, "reason": regime_reason}
    near_earnings, earnings_reason = is_near_earnings(ticker)
    if near_earnings:
        return {"ticker": ticker, "skipped": True, "reason": earnings_reason}
    too_correlated, corr_reason = is_too_correlated(
        ticker, portfolio.get("positions", {}), {ticker: df}
    )
    if too_correlated:
        return {"ticker": ticker, "skipped": True, "reason": f"corr {corr_reason}"}

    # ── 3. Score signal ──────────────────────────────────────────────
    news = fetch_news_sentiment(ticker)
    confidence, direction = score_signal(ind, news)

    if confidence < min_conf or direction is None:
        return None

    # ── 4. Check not already in this position ────────────────────────
    existing = portfolio.get("positions", {}).get(ticker)
    if existing and existing["direction"] == direction:
        return None

    # ── 5. Size the position ─────────────────────────────────────────
    price = ind["price"]
    capital = portfolio.get("capital", 100_000)
    sizing = size_position(price, ind["atr"], capital)

    if sizing["shares"] == 0:
        return None

    stop = sizing["stop_long"] if direction == "LONG" else sizing["stop_short"]
    target = sizing["target_long"] if direction == "LONG" else sizing["target_short"]

    return {
        "ticker": ticker,
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
        "news_pos": news.get("positive", 0),
        "news_neg": news.get("negative", 0),
        "headlines": news.get("headlines", [])[:3],
    }


def check_exits(portfolio: dict, market_data: dict[str, pd.DataFrame]) -> list[dict]:
    """
    Scan open positions for stop-loss hits or mean reversion completion (Z back to 0).
    Returns list of {ticker, action, reason, price}.
    """
    exits = []
    z_exit = config.get("signals.zscore_exit", 0.5)

    for ticker, pos in portfolio.get("positions", {}).items():
        df = market_data.get(ticker)
        if df is None:
            continue

        try:
            ind = compute_all(df)
        except Exception:
            continue

        price = ind["price"]
        direction = pos["direction"]
        stop = pos["stop"]
        target = pos["target"]
        z = ind["zscore"]

        reason = None

        if direction == "LONG":
            if price <= stop:
                reason = "stop_loss"
            elif price >= target:
                reason = "take_profit"
            elif abs(z) <= z_exit:
                reason = "mean_reverted"
        else:
            if price >= stop:
                reason = "stop_loss"
            elif price <= target:
                reason = "take_profit"
            elif abs(z) <= z_exit:
                reason = "mean_reverted"

        if reason:
            exits.append({"ticker": ticker, "action": "CLOSE", "reason": reason, "price": price})

    return exits