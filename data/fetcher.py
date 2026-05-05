import yfinance as yf
import pandas as pd
import feedparser
import requests
from datetime import datetime, timedelta
from typing import Optional
from .. import config
from ..utils.display import get_logger

log = get_logger(__name__)


def fetch_ohlcv(ticker: str) -> Optional[pd.DataFrame]:
    """Pull OHLCV history for one ticker. Returns None on failure."""
    days = config.get("data.lookback_days", 90)
    interval = config.get("data.interval", "1d")
    end = datetime.today()
    start = end - timedelta(days=days)

    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        # ADD these two lines right after:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty or len(df) < 30:
            log.warning(f"{ticker}: not enough data ({len(df)} rows)")
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        log.error(f"{ticker}: fetch failed — {e}")
        return None


def fetch_vix() -> Optional[float]:
    """Fetch latest VIX close from Yahoo Finance."""
    try:
        df = yf.download("^VIX", period="5d", interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        return float(df["Close"].iloc[-1].squeeze())

    except Exception as e:
        log.error(f"VIX fetch failed — {e}")
        return None


def fetch_news_sentiment(ticker: str) -> dict:
    """
    Pull latest headlines from Yahoo Finance RSS.
    Returns a simple dict: {positive, negative, neutral, headlines}.
    No external NLP — keyword heuristics, lightweight and fast.
    """
    max_age = config.get("news.max_age_hours", 24)
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"

    pos_words = {"beat", "surges", "rises", "upgrade", "buy", "strong", "record", "profit", "growth"}
    neg_words = {"miss", "falls", "drops", "downgrade", "sell", "weak", "loss", "cut", "warn", "layoff"}

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    headlines = []
    cutoff = datetime.now() - timedelta(hours=max_age)

    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            pub = datetime(*entry.published_parsed[:6]) if hasattr(entry, "published_parsed") and entry.published_parsed else None
            if pub and pub < cutoff:
                continue
            title = entry.get("title", "").lower()
            headlines.append(entry.get("title", ""))
            words = set(title.split())
            if words & pos_words:
                counts["positive"] += 1
            elif words & neg_words:
                counts["negative"] += 1
            else:
                counts["neutral"] += 1
    except Exception as e:
        log.warning(f"{ticker}: news fetch failed — {e}")

    counts["headlines"] = headlines
    return counts


def fetch_all(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Batch fetch OHLCV for a list of tickers. Returns {ticker: df}."""
    result = {}
    for ticker in tickers:
        df = fetch_ohlcv(ticker)
        if df is not None:
            result[ticker] = df
    return result