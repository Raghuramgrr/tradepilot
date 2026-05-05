import numpy as np
import pandas as pd
from ..signals.indicators import zscore, atr


def simulate_reversion(close: pd.Series, entry_price: float,
                       direction: str, n_paths: int = 500,
                       horizon: int = 10) -> dict:
    """
    Monte Carlo simulation of a mean reversion trade.
    Uses historical volatility to project N price paths forward.

    Returns probability estimates for hitting target before stop,
    expected hold time, and median outcome.
    """
    returns = close.pct_change().dropna()
    mu = float(returns.mean())
    sigma = float(returns.std())

    if sigma == 0:
        return {"error": "zero volatility"}

    hit_target = 0
    hit_stop = 0
    hold_times = []

    # Rough target/stop as % from entry — caller should pass these
    # We infer a ±3 std move as the reversion range
    std_price = float(close.rolling(20).std().iloc[-1])
    target_dist = std_price * 2.0
    stop_dist = std_price * 1.0

    target = entry_price + target_dist if direction == "LONG" else entry_price - target_dist
    stop = entry_price - stop_dist if direction == "LONG" else entry_price + stop_dist

    for _ in range(n_paths):
        price = entry_price
        hit = None
        for day in range(1, horizon + 1):
            r = np.random.normal(mu, sigma)
            price *= (1 + r)

            if direction == "LONG":
                if price >= target:
                    hit = "target"
                    break
                elif price <= stop:
                    hit = "stop"
                    break
            else:
                if price <= target:
                    hit = "target"
                    break
                elif price >= stop:
                    hit = "stop"
                    break

        if hit == "target":
            hit_target += 1
            hold_times.append(day)
        elif hit == "stop":
            hit_stop += 1
            hold_times.append(day)
        else:
            hold_times.append(horizon)

    prob_target = hit_target / n_paths
    prob_stop = hit_stop / n_paths
    prob_neither = 1 - prob_target - prob_stop
    avg_hold = float(np.mean(hold_times))

    return {
        "prob_target": round(prob_target, 3),
        "prob_stop": round(prob_stop, 3),
        "prob_open_at_horizon": round(prob_neither, 3),
        "avg_hold_days": round(avg_hold, 1),
        "simulated_target": round(target, 2),
        "simulated_stop": round(stop, 2),
        "n_paths": n_paths,
        "horizon_days": horizon,
    }


def what_if_capital(signal: dict, capital_scenarios: list[float]) -> list[dict]:
    """
    Show how position size changes across different capital levels.
    Useful for scaling in / out decisions.
    """
    from ..risk.sizer import size_position
    results = []
    for cap in capital_scenarios:
        sizing = size_position(signal["price"], signal["atr"], cap)
        results.append({
            "capital": cap,
            "shares": sizing["shares"],
            "notional": round(sizing["shares"] * signal["price"], 2),
            "dollar_risk": sizing["dollar_risk"],
        })
    return results