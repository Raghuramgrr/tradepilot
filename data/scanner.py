"""
scanner.py — whole-market opportunity scanner.

Analogy: your existing agent is a chef who cooks the dishes on the menu.
This scanner is the sous chef who walks through the entire market every
morning and says "these ingredients look exceptional today — consider
adding them to the menu."

It doesn't trade anything. It surfaces candidates ranked by confidence
for both mean reversion and momentum setups, across the full S&P 500 +
Russell 1000 universe.

Speed: uses ThreadPoolExecutor for parallel fetching.
~1000 tickers at 10 workers ≈ 3-5 minutes depending on connection.
"""

import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from .. import config
from ..signals.indicators import compute_all
from ..signals.regime import check_regime
from ..signals.scorer import score_signal
from ..strategy.momentum import score_momentum
from ..data.universe import load as load_universe
from ..utils.display import get_logger, console

log = get_logger(__name__)


# ── Lightweight fetch — just what we need for scanning ───────────

def _fetch_slim(ticker: str, days: int = 90) -> pd.DataFrame | None:
    """
    Minimal OHLCV fetch for scanning.
    Uses a shorter window than the main agent to keep scan fast.
    """
    end   = datetime.today()
    start = end - timedelta(days=days)
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if len(df) < 30:
            return None

        # Basic liquidity filter — skip thinly traded stocks
        avg_vol = float(df["Volume"].mean())
        last_price = float(df["Close"].iloc[-1])
        if avg_vol < 500_000 or last_price < 5.0:
            return None

        return df
    except Exception:
        return None


def _scan_one(ticker: str, vix: float | None) -> dict | None:
    """
    Evaluate one ticker for both mean reversion and momentum.
    Returns best signal dict or None.
    Called in parallel threads.
    """
    df = _fetch_slim(ticker)
    if df is None:
        return None

    try:
        ind = compute_all(df)
    except Exception:
        return None

    min_conf = config.get("signals.min_confidence", 60)

    # ── Try mean reversion first ─────────────────────────────────
    regime_ok, regime_reason = check_regime(ind, vix)
    if regime_ok:
        confidence, direction = score_signal(ind)
        if confidence >= min_conf and direction:
            return {
                "ticker":     ticker,
                "strategy":   "mean_reversion",
                "direction":  direction,
                "confidence": confidence,
                "price":      ind["price"],
                "zscore":     ind["zscore"],
                "rsi":        ind["rsi"],
                "adx":        ind["adx"],
                "atr":        ind["atr"],
                "reason":     f"|Z|={abs(ind['zscore']):.2f} RSI={ind['rsi']:.1f}",
            }

    # ── Try momentum if regime filter rejected it ────────────────
    else:
        confidence, direction = score_momentum(ind, df)
        if confidence >= min_conf and direction:
            return {
                "ticker":     ticker,
                "strategy":   "momentum",
                "direction":  direction,
                "confidence": confidence,
                "price":      ind["price"],
                "zscore":     ind["zscore"],
                "rsi":        ind["rsi"],
                "adx":        ind["adx"],
                "atr":        ind["atr"],
                "reason":     f"ADX={ind['adx']:.1f} RSI={ind['rsi']:.1f}",
            }

    return None


def run(
    vix: float | None = None,
    top_n: int = 20,
    workers: int = 10,
    force_refresh_universe: bool = False,
) -> list[dict]:
    """
    Scan the full universe. Returns top_n results ranked by confidence.

    workers: parallel threads for fetching (10 is safe for yfinance rate limits)
    top_n:   how many results to surface in the table
    """
    tickers = load_universe(force_refresh=force_refresh_universe)
    total   = len(tickers)
    results = []
    done    = 0

    console.print(
        f"  [dim]Scanning {total} tickers "
        f"({'S&P 500 + Russell 1000'}) "
        f"with {workers} workers...[/dim]\n"
        f"  [dim]This takes 3-5 minutes. Go get a coffee.[/dim]\n"
    )

    start_time = datetime.now()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_scan_one, t, vix): t for t in tickers}

        for future in as_completed(futures):
            done += 1
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                log.debug(f"Scan worker error: {e}")

            # Progress bar every 50 tickers
            if done % 50 == 0 or done == total:
                pct  = done / total * 100
                hits = len(results)
                elapsed = (datetime.now() - start_time).seconds
                eta = int((elapsed / done) * (total - done)) if done > 0 else 0
                console.print(
                    f"  [dim]{done}/{total} ({pct:.0f}%)  "
                    f"hits=[white]{hits}[/white]  "
                    f"ETA=[white]{eta}s[/white][/dim]",
                    end="\r",
                )

    console.print()  # clear progress line

    # Rank by confidence descending
    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results[:top_n]


def print_scan_results(results: list[dict], top_n: int = 20):
    """Print ranked scan results table."""
    from rich.table import Table
    from rich import box

    if not results:
        console.print("  [dim]No setups found across universe.[/dim]\n")
        return

    console.print(f"\n  [bold]Top {len(results)} setups found across market:[/bold]\n")

    table = Table(box=box.SIMPLE_HEAD, header_style="bold dim", padding=(0, 1))
    table.add_column("Rank",     width=5,  justify="right")
    table.add_column("Ticker",   width=8)
    table.add_column("Strategy", width=14)
    table.add_column("Signal",   width=8)
    table.add_column("Conf",     width=6,  justify="right")
    table.add_column("Price",    width=9,  justify="right")
    table.add_column("Z",        width=7,  justify="right")
    table.add_column("RSI",      width=7,  justify="right")
    table.add_column("ADX",      width=7,  justify="right")
    table.add_column("Why",      width=30)

    for i, r in enumerate(results, 1):
        strategy  = r["strategy"]
        direction = r["direction"]
        conf      = r["confidence"]

        strat_color = "cyan"  if strategy == "mean_reversion" else "magenta"
        dir_color   = "green" if direction == "LONG"          else "red"
        conf_color  = "green" if conf >= 75 else "yellow" if conf >= 60 else "dim"

        table.add_row(
            str(i),
            f"[bold white]{r['ticker']}[/bold white]",
            f"[{strat_color}]{strategy.replace('_', ' ')}[/{strat_color}]",
            f"[{dir_color}]{direction}[/{dir_color}]",
            f"[{conf_color}]{conf:.0f}[/{conf_color}]",
            f"${r['price']:.2f}",
            f"{r['zscore']:.2f}",
            f"{r['rsi']:.1f}",
            f"{r['adx']:.1f}",
            f"[dim]{r['reason']}[/dim]",
        )

    console.print(table)

    # Strategy breakdown
    mr_hits  = sum(1 for r in results if r["strategy"] == "mean_reversion")
    mom_hits = sum(1 for r in results if r["strategy"] == "momentum")
    console.print(
        f"  [dim]Mean reversion:[/dim] [cyan]{mr_hits}[/cyan]  "
        f"[dim]Momentum:[/dim] [magenta]{mom_hits}[/magenta]\n"
    )

    # Suggest adding top picks to watchlist
    top_tickers = [r["ticker"] for r in results[:5]]
    console.print(
        f"  [dim]Top 5 to consider adding to watchlist:[/dim] "
        f"[white]{', '.join(top_tickers)}[/white]\n"
    )