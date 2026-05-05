import threading
import time
import yfinance as yf
from datetime import datetime
from ..memory import context
from ..utils.display import get_logger, console

log = get_logger(__name__)

_stop_event = threading.Event()


def _get_live_price(ticker: str) -> float | None:
    """Fetch latest price via yfinance fast_info."""
    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.get("last_price") or t.fast_info.get("regularMarketPrice")
        return float(price) if price else None
    except Exception as e:
        log.debug(f"{ticker}: live price failed — {e}")
        return None


def _check_positions(mode: str):
    """Single pass — check every open position against live price."""
    portfolio = context.load()
    positions = portfolio.get("positions", {})

    if not positions:
        return

    for ticker, pos in list(positions.items()):
        price = _get_live_price(ticker)
        if price is None:
            continue

        direction = pos["direction"]
        stop = pos["stop"]
        target = pos["target"]
        reason = None

        if direction == "LONG":
            if price <= stop:
                reason = "stop_loss"
            elif price >= target:
                reason = "take_profit"
        else:
            if price >= stop:
                reason = "stop_loss"
            elif price <= target:
                reason = "take_profit"

        if reason:
            console.print(
                f"\n  [bold]Monitor:[/bold] {ticker} hit {reason} "
                f"@ ${price:.2f} (stop=${stop:.2f} target=${target:.2f})"
            )
            if mode == "auto":
                # Reload fresh state before writing to avoid race with main loop
                portfolio = context.load()
                portfolio = context.close_position(portfolio, ticker, price, reason)
                log.info(f"Monitor closed {ticker} {reason} @ ${price:.2f}")


def _monitor_loop(interval: int, mode: str):
    log.info(f"Exit monitor started — checking every {interval}s")
    while not _stop_event.is_set():
        try:
            _check_positions(mode)
        except Exception as e:
            log.error(f"Monitor loop error — {e}")
        _stop_event.wait(interval)
    log.info("Exit monitor stopped.")


def start(interval: int = 60, mode: str = "suggest") -> threading.Thread:
    """
    Start the background exit monitor thread.
    interval: seconds between price checks
    mode: 'auto' actually closes positions, 'suggest' just alerts
    """
    _stop_event.clear()
    t = threading.Thread(target=_monitor_loop, args=(interval, mode), daemon=True)
    t.start()
    return t


def stop():
    """Signal the monitor thread to exit cleanly."""
    _stop_event.set()