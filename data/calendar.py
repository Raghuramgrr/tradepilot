import yfinance as yf
from datetime import datetime, timedelta
from ..utils.display import get_logger

log = get_logger(__name__)


def days_to_earnings(ticker: str) -> int | None:
    """
    Returns number of calendar days until next earnings.
    Returns None if we can't determine it.
    """
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None or cal.empty:
            return None

        # yfinance returns calendar as a DataFrame with date in columns or index
        # Try both layouts
        if "Earnings Date" in cal.index:
            date_val = cal.loc["Earnings Date"].iloc[0]
        elif "Earnings Date" in cal.columns:
            date_val = cal["Earnings Date"].iloc[0]
        else:
            return None

        if date_val is None:
            return None

        earnings_dt = pd.Timestamp(date_val).to_pydatetime().replace(tzinfo=None)
        delta = (earnings_dt - datetime.now()).days
        return max(delta, 0)

    except Exception as e:
        log.debug(f"{ticker}: earnings calendar lookup failed — {e}")
        return None


def is_near_earnings(ticker: str, buffer_days: int = 5) -> tuple[bool, str]:
    """
    Returns (True, reason) if ticker has earnings within buffer_days.
    Returns (False, 'ok') otherwise.
    Safe to call — never raises, returns False on any failure.
    """
    days = days_to_earnings(ticker)
    if days is None:
        return False, "ok"  # can't determine, don't penalise
    if days <= buffer_days:
        return True, f"earnings in {days}d"
    return False, "ok"


# keep pandas import here to avoid polluting top-level namespace
import pandas as pd