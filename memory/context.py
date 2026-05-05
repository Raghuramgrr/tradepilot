import json
from pathlib import Path
from datetime import datetime
from .. import config
from ..utils.display import get_logger

log = get_logger(__name__)

STATE_FILE = Path(__file__).parent.parent / ".agent_state.json"


def _default_state() -> dict:
    return {
        "capital": config.get("portfolio.initial_capital", 100_000.0),
        "peak_capital": config.get("portfolio.initial_capital", 100_000.0),
        "positions": {},   # {ticker: {shares, entry, stop, target, direction}}
        "trade_log": [],   # list of closed trades
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


def load() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.error(f"State load failed, resetting — {e}")
    state = _default_state()
    save(state)
    return state


def save(state: dict):
    state["updated_at"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def open_position(state: dict, ticker: str, direction: str,
                  shares: int, entry: float, stop: float, target: float) -> dict:
    cost = shares * entry
    if direction == "LONG":
        state["capital"] -= cost
    state["positions"][ticker] = {
        "direction": direction,
        "shares": shares,
        "entry": entry,
        "stop": stop,
        "target": target,
        "opened_at": datetime.now().isoformat(),
    }
    save(state)
    return state


def close_position(state: dict, ticker: str, exit_price: float, reason: str = "signal") -> dict:
    pos = state["positions"].pop(ticker, None)
    if pos is None:
        return state

    shares = pos["shares"]
    entry = pos["entry"]
    direction = pos["direction"]

    if direction == "LONG":
        pnl = (exit_price - entry) * shares
        state["capital"] += shares * exit_price
    else:
        pnl = (entry - exit_price) * shares
        state["capital"] += (entry - exit_price + entry) * shares

    record = {
        "ticker": ticker,
        "direction": direction,
        "shares": shares,
        "entry": entry,
        "exit": exit_price,
        "pnl": round(pnl, 2),
        "reason": reason,
        "opened_at": pos["opened_at"],
        "closed_at": datetime.now().isoformat(),
    }
    state["trade_log"].append(record)
    save(state)
    log.info(f"Closed {ticker} {direction} PnL=${pnl:+.2f} ({reason})")
    return state


def reset(confirm: bool = False) -> dict:
    if not confirm:
        raise ValueError("Pass confirm=True to reset state.")
    state = _default_state()
    save(state)
    log.warning("Agent state reset to defaults.")
    return state