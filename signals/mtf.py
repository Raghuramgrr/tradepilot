import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from ..signals.indicators import zscore, atr
from ..utils.display import get_logger

log = get_logger(__name__)


def fetch_weekly(ticker: str, weeks: int = 52) -> pd.DataFrame | None:
    """Pull weekly OHLCV for a ticker."""
    end = datetime.today()
    start = end - timedelta(weeks=weeks)
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1wk",
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df if len(df) >= 10 else None
    except Exception as e:
        log.debug(f"{ticker}: weekly fetch failed — {e}")
        return None


def weekly_trend(df_weekly: pd.DataFrame) -> str:
    """
    Classify weekly trend as 'up', 'down', or 'neutral'.
    Uses 10-week vs 30-week EMA crossover.
    """
    close = df_weekly["Close"].squeeze()
    if len(close) < 30:
        return "neutral"

    ema10 = close.ewm(span=10, adjust=False).mean()
    ema30 = close.ewm(span=30, adjust=False).mean()

    last_ema10 = float(ema10.iloc[-1])
    last_ema30 = float(ema30.iloc[-1])

    gap_pct = (last_ema10 - last_ema30) / last_ema30

    if gap_pct > 0.02:       # ema10 > ema30 by >2% → uptrend
        return "up"
    elif gap_pct < -0.02:    # ema10 < ema30 by >2% → downtrend
        return "down"
    else:
        return "neutral"


def confirm(ticker: str, direction: str) -> tuple[bool, str]:
    """
    Check weekly trend aligns with (or at least doesn't fight) the daily signal.

    Mean reversion:
      LONG signal + weekly downtrend → reject (catching a falling knife)
      LONG signal + weekly up/neutral → allow
      SHORT signal + weekly uptrend → reject
      SHORT signal + weekly down/neutral → allow

    Returns (confirmed, reason).
    Safe — returns (True, 'ok') on any data failure so it never silently kills signals.
    """
    df_weekly = fetch_weekly(ticker)
    if df_weekly is None:
        return True, "ok (no weekly data)"

    trend = weekly_trend(df_weekly)

    if direction == "LONG" and trend == "down":
        return False, f"weekly trend={trend} fights LONG"
    if direction == "SHORT" and trend == "up":
        return False, f"weekly trend={trend} fights SHORT"

    return True, f"weekly trend={trend}"