from .. import config
from ..utils.display import get_logger

log = get_logger(__name__)


def check_regime(indicators: dict, vix: float | None) -> tuple[bool, str]:
    """
    Returns (is_ok, reason).
    Mean reversion works in ranging, low-vol markets.
    We bail out when the market is trending hard or VIX is spiking.
    """
    vix_max = config.get("regime.vix_max", 35.0)
    adx_max = config.get("regime.adx_max", 25.0)
    slope_max = 0.015  # 1.5% normalised slope threshold

    adx_val = indicators.get("adx", 0.0)
    slope = indicators.get("trend_slope", 0.0)

    # VIX check — extreme fear means gaps and slippage kill mean reversion
    if vix is not None and vix > vix_max:
        return False, f"VIX={vix:.1f}>{vix_max}"

    # ADX check — strong trend means price may not revert
    if adx_val > adx_max:
        return False, f"ADX={adx_val:.1f}>{adx_max} (trending)"

    # Slope check — steep linear trend, skip
    if abs(slope) > slope_max:
        direction = "up" if slope > 0 else "down"
        return False, f"slope={slope:.3f} (trending {direction})"

    return True, "ok"