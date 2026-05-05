import pandas as pd
import numpy as np
from ..utils.display import get_logger

log = get_logger(__name__)


def correlation_matrix(market_data: dict[str, pd.DataFrame], window: int = 60) -> pd.DataFrame:
    """Build a correlation matrix from recent returns across all fetched tickers."""
    returns = {}
    for ticker, df in market_data.items():
        close = df["Close"].squeeze()
        returns[ticker] = close.pct_change().dropna().tail(window)

    if not returns:
        return pd.DataFrame()

    df_returns = pd.DataFrame(returns).dropna()
    return df_returns.corr()


def is_too_correlated(
    ticker: str,
    open_positions: dict,
    market_data: dict[str, pd.DataFrame],
    threshold: float = 0.75,
) -> tuple[bool, str]:
    """
    Returns (True, reason) if new ticker is too correlated with any open position.
    Skips check if fewer than 2 data points to compare.
    """
    if not open_positions:
        return False, "ok"

    position_tickers = list(open_positions.keys())
    all_tickers = position_tickers + [ticker]

    # Need data for all tickers involved
    available = {t: market_data[t] for t in all_tickers if t in market_data}
    if len(available) < 2 or ticker not in available:
        return False, "ok"

    corr = correlation_matrix(available)

    if corr.empty or ticker not in corr.columns:
        return False, "ok"

    for pos_ticker in position_tickers:
        if pos_ticker not in corr.columns:
            continue
        r = corr.loc[ticker, pos_ticker]
        if abs(r) >= threshold:
            return True, f"r={r:.2f} with {pos_ticker}"

    return False, "ok"