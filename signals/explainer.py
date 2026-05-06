"""
explainer.py — per-ticker diagnostic log

Analogy: think of each ticker going through airport security.
Every gate is a check. This module prints exactly which gate
rejected it and how close it came to passing.

Gates in order:
  1. Data quality      — do we have enough history?
  2. Regime filter     — is market condition suitable?
  3. Earnings filter   — is there a catalyst event nearby?
  4. Correlation       — are we already exposed to this?
  5. Signal threshold  — is the setup extreme enough?
  6. MTF confirmation  — does weekly trend agree?
  7. Confidence floor  — is the total score high enough?
  8. Position check    — are we already in this trade?
"""

import pandas as pd
from dataclasses import dataclass, field
from .. import config
from ..signals.indicators import compute_all
from ..signals.regime import check_regime
from ..signals.scorer import score_signal
from ..signals.mtf import confirm as mtf_confirm
from ..data.calendar import is_near_earnings
from ..signals.correlation import is_too_correlated
from ..utils.display import get_logger, console

log = get_logger(__name__)

# How close to threshold before we flag "near miss"
NEAR_MISS_PCT = 0.15   # within 15% of threshold = near miss


@dataclass
class GateResult:
    name: str
    passed: bool
    value: float | str | None = None
    threshold: float | str | None = None
    note: str = ""

    def is_near_miss(self) -> bool:
        """Was this a close call? Only meaningful for numeric gates."""
        if self.passed or not isinstance(self.value, float) or not isinstance(self.threshold, float):
            return False
        if self.threshold == 0:
            return False
        gap = abs(self.value - self.threshold) / abs(self.threshold)
        return gap <= NEAR_MISS_PCT


@dataclass
class TickerExplain:
    ticker: str
    strategy: str = "mean_reversion"
    gates: list[GateResult] = field(default_factory=list)
    final: str = "pending"   # "signal", "skipped", "no_setup", "error"
    confidence: float = 0.0
    direction: str | None = None

    def first_failure(self) -> GateResult | None:
        for g in self.gates:
            if not g.passed:
                return g
        return None

    def near_misses(self) -> list[GateResult]:
        return [g for g in self.gates if g.is_near_miss()]


def explain_ticker(
    ticker: str,
    df: pd.DataFrame,
    vix: float | None,
    portfolio: dict,
    market_data: dict,
) -> TickerExplain:
    """
    Run every gate explicitly and record results.
    Returns a TickerExplain with full audit trail.
    """
    ex = TickerExplain(ticker=ticker)
    min_conf  = config.get("signals.min_confidence", 60)
    z_entry   = config.get("signals.zscore_entry", 2.0)
    earn_buf  = config.get("earnings.buffer_days", 5)
    corr_max  = config.get("correlation.max_r", 0.75)

    # ── Gate 1: Data quality ─────────────────────────────────────────
    n_bars = len(df)
    min_bars = 30
    ex.gates.append(GateResult(
        name="data_quality",
        passed=n_bars >= min_bars,
        value=float(n_bars),
        threshold=float(min_bars),
        note=f"{n_bars} bars available",
    ))
    if not ex.gates[-1].passed:
        ex.final = "error"
        return ex

    # ── Compute indicators ───────────────────────────────────────────
    try:
        ind = compute_all(df)
    except Exception as e:
        ex.gates.append(GateResult("indicators", False, note=str(e)))
        ex.final = "error"
        return ex

    z       = ind["zscore"]
    rsi     = ind["rsi"]
    adx     = ind["adx"]
    slope   = ind["trend_slope"]
    price   = ind["price"]

    # ── Gate 2: Regime ───────────────────────────────────────────────
    regime_ok, regime_reason = check_regime(ind, vix)
    vix_max  = config.get("regime.vix_max", 35.0)
    adx_max  = config.get("regime.adx_max", 31.0)

    ex.gates.append(GateResult(
        name="regime_adx",
        passed=regime_ok or "ADX" not in regime_reason,
        value=round(adx, 2),
        threshold=adx_max,
        note=f"ADX={adx:.1f} (want <{adx_max})",
    ))
    ex.gates.append(GateResult(
        name="regime_vix",
        passed=vix is None or vix <= vix_max,
        value=round(vix, 1) if vix else None,
        threshold=vix_max,
        note=f"VIX={vix:.1f}" if vix else "VIX unavailable",
    ))
    ex.gates.append(GateResult(
        name="regime_slope",
        passed=regime_ok or "slope" not in regime_reason,
        value=round(slope, 4),
        threshold=0.015,
        note=f"slope={slope:.4f} (want |slope|<0.015)",
    ))

    if not regime_ok:
        ex.final = "skipped"
        ex.gates.append(GateResult("regime_overall", False, note=regime_reason))
        return ex

    # ── Gate 3: Earnings proximity ───────────────────────────────────
    near_earn, earn_reason = is_near_earnings(ticker, earn_buf)
    ex.gates.append(GateResult(
        name="earnings_filter",
        passed=not near_earn,
        note=earn_reason,
    ))
    if near_earn:
        ex.final = "skipped"
        return ex

    # ── Gate 4: Z-score threshold ────────────────────────────────────
    z_abs = abs(z)
    z_ok  = z_abs >= z_entry
    ex.gates.append(GateResult(
        name="zscore_threshold",
        passed=z_ok,
        value=round(z_abs, 3),
        threshold=z_entry,
        note=(
            f"|Z|={z_abs:.2f} needs >{z_entry} — "
            f"{'LONG candidate' if z < 0 else 'SHORT candidate'} "
            f"({'near miss!' if not z_ok and z_abs >= z_entry * (1 - NEAR_MISS_PCT) else 'not stretched enough'})"
        ),
    ))

    # ── Gate 5: RSI confirmation ─────────────────────────────────────
    rsi_os = config.get("signals.rsi_oversold", 30)
    rsi_ob = config.get("signals.rsi_overbought", 70)
    # Determine expected direction from Z
    expected_dir = "LONG" if z < 0 else "SHORT" if z > 0 else None
    rsi_aligned = (
        (expected_dir == "LONG"  and rsi <= rsi_ob) or
        (expected_dir == "SHORT" and rsi >= rsi_os) or
        expected_dir is None
    )
    ex.gates.append(GateResult(
        name="rsi_check",
        passed=rsi_aligned,
        value=round(rsi, 1),
        threshold=rsi_os if expected_dir == "LONG" else rsi_ob,
        note=f"RSI={rsi:.1f} direction={expected_dir}",
    ))

    # ── Gate 6: Score / confidence ───────────────────────────────────
    news = {"positive": 0, "negative": 0}  # skip live news fetch in explain mode
    confidence, direction = score_signal(ind, news)
    ex.confidence  = confidence
    ex.direction   = direction

    ex.gates.append(GateResult(
        name="confidence_score",
        passed=confidence >= min_conf and direction is not None,
        value=round(confidence, 1),
        threshold=float(min_conf),
        note=(
            f"score={confidence:.0f}/{min_conf} needed  "
            f"direction={direction}  "
            f"{'PASS' if confidence >= min_conf else 'FAIL'}"
        ),
    ))

    if confidence < min_conf or direction is None:
        ex.final = "no_setup"
        return ex

    # ── Gate 7: MTF confirmation ─────────────────────────────────────
    mtf_ok, mtf_reason = mtf_confirm(ticker, direction)
    ex.gates.append(GateResult(
        name="mtf_weekly",
        passed=mtf_ok,
        note=mtf_reason,
    ))
    if not mtf_ok:
        ex.final = "skipped"
        return ex

    # ── Gate 8: Correlation with open positions ──────────────────────
    too_corr, corr_reason = is_too_correlated(
        ticker, portfolio.get("positions", {}), market_data, corr_max
    )
    ex.gates.append(GateResult(
        name="correlation",
        passed=not too_corr,
        note=corr_reason,
    ))
    if too_corr:
        ex.final = "skipped"
        return ex

    # ── Gate 9: Already in position ──────────────────────────────────
    already_in = ticker in portfolio.get("positions", {})
    ex.gates.append(GateResult(
        name="position_check",
        passed=not already_in,
        note="already open" if already_in else "no existing position",
    ))
    if already_in:
        ex.final = "skipped"
        return ex

    ex.final = "signal"
    return ex


def print_explain(results: list[TickerExplain]):
    """Print a readable explain report for all tickers."""
    from rich.table import Table
    from rich import box

    # Summary table
    table = Table(box=box.SIMPLE_HEAD, header_style="bold dim", padding=(0, 1))
    table.add_column("Ticker",    width=8)
    table.add_column("Result",    width=10)
    table.add_column("Failed at", width=20)
    table.add_column("Z",         justify="right", width=7)
    table.add_column("RSI",       justify="right", width=7)
    table.add_column("ADX",       justify="right", width=7)
    table.add_column("Conf",      justify="right", width=7)
    table.add_column("Note",      width=35)

    for ex in results:
        failure = ex.first_failure()
        near    = ex.near_misses()

        result_color = {
            "signal":   "green",
            "skipped":  "yellow",
            "no_setup": "dim",
            "error":    "red",
            "pending":  "dim",
        }.get(ex.final, "dim")

        # Find gate values
        z_val   = next((g.value for g in ex.gates if g.name == "zscore_threshold"), "—")
        rsi_val = next((g.value for g in ex.gates if g.name == "rsi_check"), "—")
        adx_val = next((g.value for g in ex.gates if g.name == "regime_adx"), "—")

        z_str   = f"{z_val:.2f}"   if isinstance(z_val, float)   else "—"
        rsi_str = f"{rsi_val:.1f}" if isinstance(rsi_val, float) else "—"
        adx_str = f"{adx_val:.1f}" if isinstance(adx_val, float) else "—"
        conf_str = f"{ex.confidence:.0f}" if ex.confidence > 0 else "—"

        failed_at = failure.name if failure else "—"
        note      = failure.note if failure else ("✓ signal fired" if ex.final == "signal" else "")

        # Flag near misses
        if near and ex.final != "signal":
            near_names = ", ".join(g.name for g in near)
            note = f"⚡ near miss on: {near_names}"

        table.add_row(
            ex.ticker,
            f"[{result_color}]{ex.final}[/{result_color}]",
            f"[dim]{failed_at}[/dim]",
            z_str,
            rsi_str,
            adx_str,
            conf_str,
            f"[dim]{note[:35]}[/dim]",
        )

    console.print(table)

    # Detail for near misses
    near_miss_tickers = [ex for ex in results if ex.near_misses() and ex.final != "signal"]
    if near_miss_tickers:
        console.print("  [dim]Near misses — almost triggered:[/dim]")
        for ex in near_miss_tickers:
            for g in ex.near_misses():
                gap_pct = abs(g.value - g.threshold) / g.threshold * 100
                console.print(
                    f"    [yellow]⚡[/yellow] [white]{ex.ticker}[/white] "
                    f"[dim]{g.name}:[/dim] "
                    f"value={g.value} threshold={g.threshold} "
                    f"[yellow]({gap_pct:.1f}% away)[/yellow]"
                )
        console.print()