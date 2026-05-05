from .. import config


def score_signal(indicators: dict, news: dict | None = None) -> tuple[float, str | None]:
    """
    Score a mean reversion setup 0–100.
    Returns (confidence, direction) where direction is 'LONG', 'SHORT', or None.

    Scoring breakdown:
      40 pts  Z-score magnitude (primary driver)
      20 pts  RSI confirmation
      20 pts  Bollinger Band confirmation
      20 pts  News sentiment alignment
    """
    z = indicators["zscore"]
    r = indicators["rsi"]
    price = indicators["price"]
    bb_upper = indicators["bb_upper"]
    bb_lower = indicators["bb_lower"]

    z_entry = config.get("signals.zscore_entry", 2.0)
    rsi_os = config.get("signals.rsi_oversold", 30)
    rsi_ob = config.get("signals.rsi_overbought", 70)

    # Determine direction from Z-score sign
    if z < -z_entry:
        direction = "LONG"   # price below mean → expect bounce up
    elif z > z_entry:
        direction = "SHORT"  # price above mean → expect reversion down
    else:
        return 0.0, None

    score = 0.0

    # ── Z-score component (40 pts) ──────────────────────────────────
    # More extreme Z = stronger mean reversion candidate
    z_abs = abs(z)
    if z_abs >= 3.0:
        score += 40
    elif z_abs >= 2.5:
        score += 30
    elif z_abs >= 2.0:
        score += 20

    # ── RSI component (20 pts) ──────────────────────────────────────
    if direction == "LONG" and r <= rsi_os:
        score += 20
    elif direction == "LONG" and r <= 40:
        score += 10
    elif direction == "SHORT" and r >= rsi_ob:
        score += 20
    elif direction == "SHORT" and r >= 60:
        score += 10

    # ── Bollinger Band component (20 pts) ───────────────────────────
    if direction == "LONG" and price <= bb_lower:
        score += 20
    elif direction == "LONG" and price <= (bb_lower * 1.01):
        score += 10
    elif direction == "SHORT" and price >= bb_upper:
        score += 20
    elif direction == "SHORT" and price >= (bb_upper * 0.99):
        score += 10

    # ── News sentiment component (20 pts) ───────────────────────────
    if news:
        pos = news.get("positive", 0)
        neg = news.get("negative", 0)
        if direction == "LONG" and neg > pos:
            # oversold AND bad news = classic mean reversion setup
            score += 20
        elif direction == "SHORT" and pos > neg:
            # overbought AND good news = classic exhaustion setup
            score += 20
        elif pos == neg:
            score += 5  # neutral news, small bonus

    return min(score, 100.0), direction