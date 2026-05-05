from ..memory import context
from ..risk.sizer import check_portfolio_limits, update_peak
from ..utils.display import get_logger, print_execution

log = get_logger(__name__)


def route(signal: dict, portfolio: dict, mode: str) -> dict:
    """
    Route a signal to either:
      - SUGGEST: print the trade alert, no state change
      - AUTO: open position, deduct capital, persist state

    Returns updated portfolio dict.
    """
    ticker = signal["ticker"]
    direction = signal["direction"]
    shares = signal["shares"]
    price = signal["price"]
    stop = signal["stop"]
    target = signal["target"]

    # Final portfolio-level gate (drawdown / max positions)
    can_trade, reason = check_portfolio_limits(portfolio)
    if not can_trade:
        log.warning(f"Order blocked — {reason}")
        return portfolio

    print_execution(ticker, direction, shares, price, mode)

    if mode == "auto":
        portfolio = context.open_position(
            portfolio, ticker, direction, shares, price, stop, target
        )
        portfolio = update_peak(portfolio)

    return portfolio


def route_exit(exit_signal: dict, portfolio: dict, mode: str) -> dict:
    """
    Route an exit signal (stop hit, target hit, mean reverted).
    In suggest mode: print the alert.
    In auto mode: close position and update capital.
    """
    ticker = exit_signal["ticker"]
    price = exit_signal["price"]
    reason = exit_signal["reason"]

    pos = portfolio.get("positions", {}).get(ticker)
    if pos is None:
        return portfolio

    action_label = f"EXIT ({reason})"
    print_execution(ticker, action_label, pos["shares"], price, mode)

    if mode == "auto":
        portfolio = context.close_position(portfolio, ticker, price, reason)
        portfolio = update_peak(portfolio)

    return portfolio