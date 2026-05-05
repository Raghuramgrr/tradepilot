#!/usr/bin/env python3
"""
Trader Agent — mean reversion agent for equities.

Usage:
  python -m tradepilot.main                  # run once, suggest mode
  python -m tradepilot.main --mode auto      # run once, auto mode
  python -m tradepilot.main --loop 300       # run every 300s
  python -m tradepilot.main --sim AAPL       # run scenario sim on one ticker
  python -m tradepilot.main --reset          # wipe state and start fresh
  python -m tradepilot.main --status         # show portfolio state
"""

import argparse
import time
import sys

from . import config as cfg
from .data.fetcher import fetch_all, fetch_vix
from .strategy.mean_reversion import evaluate, check_exits
from .strategy.simulator import simulate_reversion, what_if_capital
from .execution.router import route, route_exit
from .memory import context
from .risk import monitor as exit_monitor
from .strategy import backtest
from .utils.display import (
    console, print_header, print_signals,
    print_portfolio, print_skipped, get_logger
)

log = get_logger(__name__)


def run_once(mode: str):
    config = cfg.load()
    tickers = config["watchlist"]

    print_header(mode)

    # Load persistent state
    portfolio = context.load()
    print_portfolio(portfolio)

    # Fetch market data
    console.print("[dim]  Fetching market data...[/dim]")
    market_data = fetch_all(tickers)
    vix = fetch_vix()
    if vix:
        console.print(f"  [dim]VIX[/dim] [white]{vix:.1f}[/white]\n")

    # Check exits on open positions first
    exits = check_exits(portfolio, market_data)
    if exits:
        console.print("[dim]  Exit signals:[/dim]")
        for ex in exits:
            portfolio = route_exit(ex, portfolio, mode)
        console.print()

    # Evaluate each ticker for new entries
    signals = []
    skipped = []

    for ticker in tickers:
        if ticker not in market_data:
            continue
        result = evaluate(ticker, market_data[ticker], vix, portfolio)
        if result is None:
            continue
        if result.get("skipped"):
            skipped.append((ticker, result["reason"]))
        else:
            signals.append(result)

    # Sort by confidence descending
    signals.sort(key=lambda s: s["confidence"], reverse=True)

    print_skipped(skipped)
    console.print("[dim]  Entry signals:[/dim]")
    print_signals(signals)

    # Route signals
    for sig in signals:
        # Skip if already in this ticker
        if sig["ticker"] in portfolio.get("positions", {}):
            continue
        portfolio = route(sig, portfolio, mode)

    console.print()


def run_sim(ticker: str):
    """Scenario simulation for a single ticker."""
    from .data.fetcher import fetch_ohlcv
    from .signals.indicators import compute_all

    console.print(f"\n[bold]Scenario simulation — {ticker}[/bold]\n")
    df = fetch_ohlcv(ticker)
    if df is None:
        console.print(f"[red]Could not fetch data for {ticker}[/red]")
        return

    ind = compute_all(df)
    close = ind["close_series"]
    price = ind["price"]

    for direction in ("LONG", "SHORT"):
        result = simulate_reversion(close, price, direction, n_paths=1000, horizon=15)
        console.print(
            f"  {direction:5s}  "
            f"P(target)=[green]{result['prob_target']:.1%}[/green]  "
            f"P(stop)=[red]{result['prob_stop']:.1%}[/red]  "
            f"avg hold=[white]{result['avg_hold_days']:.1f}d[/white]"
        )

    console.print("\n  Capital scaling:")
    dummy_signal = {"price": price, "atr": ind["atr"]}
    rows = what_if_capital(dummy_signal, [50_000, 100_000, 250_000, 500_000])
    for r in rows:
        console.print(
            f"    ${r['capital']:>9,.0f}  →  {r['shares']:>4}sh  "
            f"notional=${r['notional']:>9,.0f}  risk=${r['dollar_risk']:>7,.0f}"
        )
    console.print()


def show_status():
    portfolio = context.load()
    print_portfolio(portfolio)
    positions = portfolio.get("positions", {})
    if positions:
        console.print("  [dim]Open positions:[/dim]")
        for ticker, pos in positions.items():
            pnl_est = "—"
            console.print(
                f"    [white]{ticker}[/white] {pos['direction']} "
                f"{pos['shares']}sh @ ${pos['entry']:.2f}  "
                f"stop=${pos['stop']:.2f}  target=${pos['target']:.2f}"
            )
    else:
        console.print("  [dim]No open positions.[/dim]")

    log = portfolio.get("trade_log", [])
    if log:
        total_pnl = sum(t["pnl"] for t in log)
        wins = sum(1 for t in log if t["pnl"] > 0)
        console.print(
            f"\n  [dim]Closed trades:[/dim] {len(log)}  "
            f"win rate=[white]{wins/len(log):.0%}[/white]  "
            f"total PnL=[{'green' if total_pnl >= 0 else 'red'}]${total_pnl:+,.0f}[/{'green' if total_pnl >= 0 else 'red'}]"
        )
    console.print()


def main():
    parser = argparse.ArgumentParser(description="Trader Agent — mean reversion")
    parser.add_argument("--mode", choices=["suggest", "auto"],
                        default=cfg.get("mode", "suggest"))
    parser.add_argument("--backtest", action="store_true",
                        help="Run backtest across full watchlist")
    parser.add_argument("--loop", type=int, default=0,
                        help="Run every N seconds (0 = run once)")
    parser.add_argument("--sim", type=str, metavar="TICKER",
                        help="Run scenario simulation on a ticker")
    parser.add_argument("--reset", action="store_true",
                        help="Reset agent state to defaults")
    parser.add_argument("--status", action="store_true",
                        help="Show portfolio status and exit")
    args = parser.parse_args()

    if args.reset:
        context.reset(confirm=True)
        console.print("[green]State reset.[/green]")
        return
    if args.backtest:
        config = cfg.load()
        tickers = config["watchlist"]
        console.print("[dim]  Fetching data for backtest...[/dim]")
        from .data.fetcher import fetch_all
        market_data = fetch_all(tickers)
        backtest.run_universe(tickers, market_data)
        return

    if args.status:
        show_status()
        return

    if args.sim:
        run_sim(args.sim.upper())
        return

    if args.loop > 0:
        exit_monitor.start(interval=60, mode=args.mode)   # ADD THIS LINE
        console.print(f"[dim]Running every {args.loop}s — Ctrl+C to stop[/dim]\n")
        try:
            while True:
                run_once(args.mode)
                time.sleep(args.loop)
        except KeyboardInterrupt:
            exit_monitor.stop()                            # ADD THIS LINE
            console.print("\n[dim]Agent stopped.[/dim]")
    else:
        run_once(args.mode)


if __name__ == "__main__":
    main()