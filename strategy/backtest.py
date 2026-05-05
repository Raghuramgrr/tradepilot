import pandas as pd
import numpy as np
from datetime import datetime
from ..signals.indicators import compute_all
from ..signals.regime import check_regime
from ..signals.scorer import score_signal
from ..risk.sizer import size_position
from .. import config
from ..utils.display import console, get_logger

log = get_logger(__name__)


def run(
    ticker: str,
    df: pd.DataFrame,
    capital: float = 100_000.0,
    verbose: bool = False,
) -> dict:
    """
    Walk-forward backtest on a single ticker.
    Steps through each bar after a warm-up period, checks if a signal would
    have fired, simulates the trade, and records the outcome.
    """
    z_entry = config.get("signals.zscore_entry", 2.0)
    z_exit = config.get("signals.zscore_exit", 0.5)
    min_conf = config.get("signals.min_confidence", 60)
    warm_up = 30  # bars needed before indicators are reliable

    trades = []
    position = None  # {direction, entry, stop, target, shares, entry_bar}

    close = df["Close"].squeeze()

    for i in range(warm_up, len(df)):
        slice_df = df.iloc[: i + 1].copy()
        bar_date = df.index[i]
        price = float(close.iloc[i])

        # ── Check exit on open position first ────────────────────────
        if position is not None:
            z_now = float(compute_all(slice_df)["zscore"])
            hit = None

            if position["direction"] == "LONG":
                if price <= position["stop"]:
                    hit = "stop_loss"
                elif price >= position["target"]:
                    hit = "take_profit"
                elif abs(z_now) <= z_exit:
                    hit = "mean_reverted"
            else:
                if price >= position["stop"]:
                    hit = "stop_loss"
                elif price <= position["target"]:
                    hit = "take_profit"
                elif abs(z_now) <= z_exit:
                    hit = "mean_reverted"

            if hit:
                shares = position["shares"]
                entry = position["entry"]
                direction = position["direction"]
                pnl = (price - entry) * shares if direction == "LONG" else (entry - price) * shares
                capital += shares * price if direction == "LONG" else (entry - price + entry) * shares

                trades.append({
                    "ticker": ticker,
                    "direction": direction,
                    "entry_date": position["entry_date"],
                    "exit_date": bar_date,
                    "entry": entry,
                    "exit": price,
                    "shares": shares,
                    "pnl": round(pnl, 2),
                    "hold_bars": i - position["entry_bar"],
                    "reason": hit,
                })
                if verbose:
                    pnl_col = "green" if pnl >= 0 else "red"
                    console.print(
                        f"  {bar_date.date()} CLOSE {direction} {ticker} "
                        f"[{pnl_col}]${pnl:+.0f}[/{pnl_col}] ({hit})"
                    )
                position = None

        # ── Check entry if flat ───────────────────────────────────────
        if position is None:
            try:
                ind = compute_all(slice_df)
            except Exception:
                continue

            regime_ok, _ = check_regime(ind, vix=None)  # no historical VIX in backtest
            if not regime_ok:
                continue

            conf, direction = score_signal(ind)
            if conf < min_conf or direction is None:
                continue

            sizing = size_position(price, ind["atr"], capital)
            if sizing["shares"] == 0:
                continue

            stop = sizing["stop_long"] if direction == "LONG" else sizing["stop_short"]
            target = sizing["target_long"] if direction == "LONG" else sizing["target_short"]

            cost = sizing["shares"] * price
            if cost > capital:
                continue

            capital -= cost
            position = {
                "direction": direction,
                "entry": price,
                "stop": stop,
                "target": target,
                "shares": sizing["shares"],
                "entry_bar": i,
                "entry_date": bar_date,
            }
            if verbose:
                console.print(
                    f"  {bar_date.date()} OPEN  {direction} {ticker} "
                    f"@ ${price:.2f}  stop=${stop:.2f}  target=${target:.2f}"
                )

    return _summarise(trades, capital)


def _summarise(trades: list[dict], final_capital: float) -> dict:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "total_pnl": 0.0,
            "avg_hold_bars": 0.0,
            "profit_factor": 0.0,
            "final_capital": final_capital,
        }

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1  # avoid div/0

    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "avg_pnl": round(np.mean(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
        "avg_hold_bars": round(np.mean([t["hold_bars"] for t in trades]), 1),
        "profit_factor": round(gross_profit / gross_loss, 2),
        "final_capital": round(final_capital, 2),
        "trades": trades,
    }


def run_universe(tickers: list[str], market_data: dict, capital: float = 100_000.0) -> None:
    """Run backtest across all tickers and print a summary table."""
    from rich.table import Table
    from rich import box

    table = Table(box=box.SIMPLE_HEAD, header_style="bold dim", padding=(0, 1))
    table.add_column("Ticker", width=8)
    table.add_column("Trades", justify="right", width=7)
    table.add_column("Win %", justify="right", width=7)
    table.add_column("Avg PnL", justify="right", width=9)
    table.add_column("Total PnL", justify="right", width=11)
    table.add_column("Prof. factor", justify="right", width=13)
    table.add_column("Avg hold", justify="right", width=9)

    for ticker in tickers:
        df = market_data.get(ticker)
        if df is None:
            continue
        result = run(ticker, df, capital=capital)
        pnl_color = "green" if result["total_pnl"] >= 0 else "red"
        wr = result["win_rate"]
        wr_color = "green" if wr >= 0.5 else "yellow" if wr >= 0.4 else "red"

        table.add_row(
            ticker,
            str(result["total_trades"]),
            f"[{wr_color}]{wr:.0%}[/{wr_color}]",
            f"${result['avg_pnl']:+.0f}",
            f"[{pnl_color}]${result['total_pnl']:+,.0f}[/{pnl_color}]",
            str(result["profit_factor"]),
            f"{result['avg_hold_bars']:.1f}d",
        )

    console.print(table)