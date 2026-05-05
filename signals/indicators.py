import numpy as np
import pandas as pd
from .. import config


def zscore(series: pd.Series, window: int = None) -> pd.Series:
    """Rolling Z-score: how many std devs from rolling mean."""
    w = window or config.get("signals.zscore_window", 20)
    mean = series.rolling(w).mean()
    std = series.rolling(w).std()
    return (series - mean) / std.replace(0, np.nan)


def rsi(series: pd.Series, window: int = None) -> pd.Series:
    """Wilder RSI."""
    w = window or config.get("signals.rsi_window", 14)
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / w, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / w, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def bollinger_bands(series: pd.Series, window: int = None, num_std: float = None):
    """Returns (upper, mid, lower) bands."""
    w = window or config.get("signals.bb_window", 20)
    n = num_std or config.get("signals.bb_std", 2.0)
    mid = series.rolling(w).mean()
    std = series.rolling(w).std()
    return mid + n * std, mid, mid - n * std


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range — measures volatility for stop/target sizing."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


def adx(df: pd.DataFrame, window: int = None) -> pd.Series:
    """Average Directional Index — measures trend strength (not direction)."""
    w = window or config.get("regime.adx_window", 14)
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_s = tr.ewm(alpha=1 / w, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / w, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / w, adjust=False).mean() / atr_s

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.ewm(alpha=1 / w, adjust=False).mean()


def trend_slope(series: pd.Series, window: int = None) -> float:
    """Linear regression slope over last N bars, normalised by mean price."""
    w = window or config.get("regime.trend_slope_window", 20)
    s = series.dropna().tail(w)
    if len(s) < w // 2:
        return 0.0
    x = np.arange(len(s))
    slope = np.polyfit(x, s.values, 1)[0]
    return slope / s.mean()


def compute_all(df: pd.DataFrame) -> dict:
    """Compute all indicators for a ticker dataframe. Returns latest values."""
    close = df["Close"].squeeze()

    z = zscore(close)
    r = rsi(close)
    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    atr_s = atr(df)
    adx_s = adx(df)
    slope = trend_slope(close)

    return {
        "zscore": float(z.iloc[-1]),
        "rsi": float(r.iloc[-1]),
        "bb_upper": float(bb_upper.iloc[-1]),
        "bb_mid": float(bb_mid.iloc[-1]),
        "bb_lower": float(bb_lower.iloc[-1]),
        "atr": float(atr_s.iloc[-1]),
        "adx": float(adx_s.iloc[-1]),
        "trend_slope": slope,
        "price": float(close.iloc[-1]),
        "close_series": close,
    }