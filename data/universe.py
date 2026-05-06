"""
universe.py — fetches and caches S&P 500 + Russell 1000 tickers.

Analogy: this is your fishing net. The scanner is the boat.
This file decides how wide the net is.

Tickers are cached locally in .ticker_cache.json and refreshed
every N days so we don't hammer Wikipedia on every scan.
"""

import json
import time
import pandas as pd
from pathlib import Path
from ..utils.display import get_logger, console

log = get_logger(__name__)

CACHE_FILE  = Path(__file__).parent.parent / ".ticker_cache.json"
CACHE_DAYS  = 7   # refresh universe weekly


def _fetch_sp500() -> list[str]:
    """Pull S&P 500 constituents from Wikipedia."""
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info(f"Fetched {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as e:
        log.error(f"S&P 500 fetch failed — {e}")
        return []


def _fetch_russell1000() -> list[str]:
    """
    Pull Russell 1000 constituents.
    iShares IWB ETF holdings page is the most reliable free source.
    Falls back to a curated static list if fetch fails.
    """
    try:
        # iShares Russell 1000 ETF holdings CSV
        url = "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund"
        df = pd.read_csv(url, skiprows=9)
        df.columns = df.columns.str.strip()
        tickers = (
            df[df["Asset Class"] == "Equity"]["Ticker"]
            .str.strip()
            .str.replace(".", "-", regex=False)
            .dropna()
            .tolist()
        )
        log.info(f"Fetched {len(tickers)} Russell 1000 tickers")
        return tickers
    except Exception as e:
        log.warning(f"Russell 1000 live fetch failed ({e}) — using static fallback")
        return _russell1000_static()


def _russell1000_static() -> list[str]:
    """
    Static list of large/mid cap Russell 1000 names not in S&P 500.
    Covers the most liquid names. Refresh periodically.
    """
    return [
        "AXON","DKNG","DUOL","RBLX","RIVN","LCID","HOOD","SOFI","UPST",
        "AFRM","OPEN","WISH","CLOV","SPCE","GDRX","OZON","UWMC","COMP",
        "LMND","ROOT","PSFE","MVST","BIRD","BARK","PETS","DOCS","ONEM",
        "ACMR","NOVA","STEM","BE","PLUG","FCEL","BLNK","CHPT","EVGO",
        "FSR","GOEV","XPEV","LI","NIO","NKLA","WKHS","RIDE","HYLN",
        "SPWR","ENPH","SEDG","RUN","NOVA","ARRY","CSIQ","FSLR","JKS",
        "DQ","SOL","MAXN","SHLS","POWI","IRAO","GPRE","REX","ALTO",
        "ANDE","MGPI","PEIX","GEVO","AMTX","WEST","HNRG","TPVG","GAIN",
        "MAIN","HTGC","ARCC","PSEC","GBDC","SLRC","BXSL","CGBD","TRIN",
        "CSWC","PFLT","OCSL","FDUS","TCPC","GSBD","NMFC","FSK","ORCC",
        "OBDC","BLUE","FATE","BEAM","EDIT","NTLA","CRSP","VERV","GRPH",
        "PRME","SANA","TGTX","IMVT","ACAD","HALO","INVA","PETQ","PAHC",
        "PRGO","ENDP","BDSI","COLL","TREVENA","ZYNE","LPCN","ATNF",
        "ZAFG","LQDA","TRVI","VNDA","NEOS","IRWD","CPIX","MACK","IDRA",
    ]


def load(force_refresh: bool = False) -> list[str]:
    """
    Load ticker universe. Uses cache if fresh, fetches if stale or missing.
    Returns deduplicated, sorted list of tickers.
    """
    # Check cache freshness
    if not force_refresh and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                cached = json.load(f)
            age_days = (time.time() - cached.get("timestamp", 0)) / 86400
            if age_days < CACHE_DAYS:
                tickers = cached["tickers"]
                log.info(f"Universe loaded from cache: {len(tickers)} tickers ({age_days:.1f}d old)")
                return tickers
        except Exception:
            pass

    console.print("  [dim]Refreshing ticker universe (S&P 500 + Russell 1000)...[/dim]")

    sp500   = _fetch_sp500()
    r1000   = _fetch_russell1000()

    combined = list({t for t in sp500 + r1000 if t and len(t) <= 5})
    combined.sort()

    # Persist cache
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"tickers": combined, "timestamp": time.time()}, f)
        log.info(f"Universe cached: {len(combined)} tickers")
    except Exception as e:
        log.warning(f"Cache write failed — {e}")

    return combined