from .. import config
from ..utils.display import get_logger

log = get_logger(__name__)


def size_position(price: float, atr_val: float, capital: float) -> dict:
    """
    Compute shares, stop price, and target price.

    Uses fractional Kelly-based sizing capped at max_position_pct.
    Stop is placed at entry ± stop_loss_atr_mult × ATR.
    Target is placed at entry ∓ take_profit_atr_mult × ATR.
    """
    max_pct = config.get("risk.max_position_pct", 0.10)
    kelly = config.get("risk.kelly_fraction", 0.25)
    stop_mult = config.get("risk.stop_loss_atr_mult", 2.0)
    tp_mult = config.get("risk.take_profit_atr_mult", 3.0)

    stop_distance = atr_val * stop_mult

    # Kelly sizing: risk kelly% of capital per trade, dollar-risk = stop_distance per share
    dollar_risk = capital * kelly * max_pct
    shares = int(dollar_risk / stop_distance) if stop_distance > 0 else 0

    # Hard cap: never exceed max_position_pct of capital in notional value
    max_shares = int((capital * max_pct) / price)
    shares = min(shares, max_shares)

    return {
        "shares": max(shares, 0),
        "stop_long": round(price - stop_distance, 2),
        "stop_short": round(price + stop_distance, 2),
        "target_long": round(price + atr_val * tp_mult, 2),
        "target_short": round(price - atr_val * tp_mult, 2),
        "dollar_risk": round(shares * stop_distance, 2),
    }


def check_portfolio_limits(portfolio: dict) -> tuple[bool, str]:
    """
    Gate checks before any new order is routed.
    Returns (can_trade, reason).
    """
    max_dd = config.get("risk.max_portfolio_dd", 0.08)
    max_pos = config.get("risk.max_open_positions", 6)

    capital = portfolio.get("capital", 0)
    peak = portfolio.get("peak_capital", capital)
    positions = portfolio.get("positions", {})

    if peak > 0:
        drawdown = (peak - capital) / peak
        if drawdown > max_dd:
            return False, f"portfolio drawdown {drawdown:.1%} > limit {max_dd:.1%}"

    if len(positions) >= max_pos:
        return False, f"max open positions ({max_pos}) reached"

    return True, "ok"


def update_peak(portfolio: dict) -> dict:
    """Keep peak capital fresh for drawdown tracking."""
    cap = portfolio.get("capital", 0)
    peak = portfolio.get("peak_capital", 0)
    portfolio["peak_capital"] = max(cap, peak)
    return portfolio