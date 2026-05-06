import yfinance as yf
import pandas as pd
from ..utils.display import get_logger, console
from .. import config

log = get_logger(__name__)


def screen_stock(ticker: str) -> tuple[bool, str]:
    """
    Momentum breakout screener.
    Returns (passed, reason) so caller knows why a ticker was rejected.

    Conditions (all configurable via config.yaml screener block):
      price_min    — ignore penny stocks / micro caps
      volume_min   — ignore illiquid names (absolute daily volume floor)
      atr_min_pct  — ignore low-volatility stocks that won't move enough
      trend        — MA5 > MA10 > MA20, price above MA20 (aligned uptrend)
      momentum     — price above N-day rolling high (breakout)
      volume_spike — today's volume > multiplier × rolling average
      breakout     — price within pct of N-day high
    """
    cfg = config.get("screener", {})

    period        = cfg.get("lookback_period", "3mo")
    ma_fast       = cfg.get("ma_fast", 5)
    ma_mid        = cfg.get("ma_mid", 10)
    ma_slow       = cfg.get("ma_slow", 20)
    vol_window    = cfg.get("volume_window", 5)
    momentum_win  = cfg.get("momentum_window", 10)
    breakout_win  = cfg.get("breakout_window", 20)
    breakout_pct  = cfg.get("breakout_pct", 0.95)   # within 5% of high
    vol_mult      = cfg.get("volume_spike_mult", 1.5)
    price_min     = cfg.get("min_price", 5.0)
    volume_min    = cfg.get("min_avg_volume", 500_000)
    atr_min_pct   = cfg.get("min_atr_pct", 0.01)    # 1% daily ATR minimum
    min_bars      = cfg.get("min_bars", 30)

    try:
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if len(df) < min_bars:
            return False, f"insufficient data ({len(df)} bars)"

        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        latest_close  = float(close.iloc[-1])
        latest_vol    = float(volume.iloc[-1])

        # ── Minimum price ────────────────────────────────────────────
        if latest_close < price_min:
            return False, f"price ${latest_close:.2f} < min ${price_min}"

        # ── Minimum average volume ───────────────────────────────────
        avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
        if avg_vol_20 < volume_min:
            return False, f"avg vol {avg_vol_20:,.0f} < min {volume_min:,.0f}"

        # ── Minimum ATR (volatility floor) ───────────────────────────
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_val = float(tr.rolling(14).mean().iloc[-1])
        atr_pct = atr_val / latest_close
        if atr_pct < atr_min_pct:
            return False, f"ATR {atr_pct:.2%} < min {atr_min_pct:.2%}"

        # ── MA alignment ─────────────────────────────────────────────
        ma_f = float(close.rolling(ma_fast).mean().iloc[-1])
        ma_m = float(close.rolling(ma_mid).mean().iloc[-1])
        ma_s = float(close.rolling(ma_slow).mean().iloc[-1])
        # trend = latest_close > ma_s and ma_f > ma_m > ma_s
        ma_aligned = ma_f > ma_m > ma_s          # full stack — strong signal
        above_slow  = latest_close > ma_s        # minimum — price above MA20
        trend = above_slow and (ma_aligned or momentum or breakout)

        if not trend:
            return False, "MA alignment failed"

        # ── Momentum: price above N-day rolling high (prior bar) ─────
        # Use shift(1) to get yesterday's rolling max, avoiding look-ahead
        rolling_high = close.rolling(momentum_win).max().shift(1)
        momentum = latest_close > float(rolling_high.iloc[-1])

        # ── Breakout: price within pct of N-day high ─────────────────
        recent_high = float(high.rolling(breakout_win).max().iloc[-1])
        breakout = latest_close >= breakout_pct * recent_high

        if not (momentum or breakout):
            return False, "no momentum or breakout"

        # ── Volume spike ─────────────────────────────────────────────
        avg_vol_fast = float(volume.rolling(vol_window).mean().iloc[-1])
        volume_ok = latest_vol > vol_mult * avg_vol_fast

        if not volume_ok:
            return False, f"volume spike failed ({latest_vol:,.0f} vs {vol_mult}×{avg_vol_fast:,.0f})"

        return True, "passed"

    except Exception as e:
        log.debug(f"{ticker}: screener error — {e}")
        return False, f"error: {e}"


def run(universe: list[str] | None = None, verbose: bool = False) -> list[str]:
    """
    Run screener across universe, return tickers that pass.
    Universe falls back to config.yaml screener.universe if not passed in.
    """
    cfg_universe = config.get("screener.universe", [])
    tickers = universe or cfg_universe
    if not tickers:
        log.warning("Screener universe is empty — add tickers to screener.universe in config.yaml")
        return []

    # Deduplicate preserving order
    seen = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]

    passed = []
    console.print(f"  [dim]Screening {len(tickers)} tickers...[/dim]\n")

    for ticker in tickers:
        result, reason = screen_stock(ticker)
        if result:
            status = "[green]✓[/green]"
            passed.append(ticker)
        else:
            status = "[dim]✗[/dim]"

        if verbose or result:
            console.print(f"    {status} [white]{ticker:<8}[/white] [dim]{reason}[/dim]")

    console.print(
        f"\n  [dim]Screener passed[/dim] [white]{len(passed)}/{len(tickers)}[/white] tickers: "
        f"[white]{', '.join(passed) if passed else 'none'}[/white]\n"
    )
    return passed