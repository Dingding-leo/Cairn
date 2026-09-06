from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import log, sqrt
from statistics import mean, pstdev

from .exact import decimal_fraction, pct_change
from .models import Candle, InstrumentType, MarketQuote, OKXInstrument


@dataclass(frozen=True)
class ScreenPolicy:
    quote_currency: str = "USDT"
    min_quote_volume_24h: str = "1000000"
    max_spread_bps: str = "50"
    detail_limit: int = 12
    deep_research_limit: int = 4

    def __post_init__(self) -> None:
        if self.detail_limit < 1 or self.detail_limit > 100:
            raise ValueError("detail_limit must be between 1 and 100")
        if self.deep_research_limit < 1 or self.deep_research_limit > self.detail_limit:
            raise ValueError("deep_research_limit must be within detail_limit")
        if decimal_fraction(self.min_quote_volume_24h) < 0:
            raise ValueError("minimum volume cannot be negative")
        if decimal_fraction(self.max_spread_bps) < 0:
            raise ValueError("spread limit cannot be negative")


@dataclass(frozen=True)
class ScreenedInstrument:
    inst_id: str
    score: Fraction
    research_priority: int
    reasons: tuple[str, ...]
    held: bool = False


@dataclass(frozen=True)
class MarketDiagnostics:
    inst_id: str
    return_24h: Fraction | None
    return_7d: Fraction | None
    max_drawdown: Fraction | None
    annualized_volatility: float | None
    bars: int


def spread_bps(quote: MarketQuote) -> Fraction | None:
    if quote.bid is None or quote.ask is None:
        return None
    bid = decimal_fraction(quote.bid)
    ask = decimal_fraction(quote.ask)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    if mid == 0:
        return None
    return (ask - bid) / mid * 10_000


def _quote_turnover(instrument: OKXInstrument, quote: MarketQuote) -> Fraction | None:
    """Return comparable quote-currency turnover for spot only.

    OKX volume semantics differ across product families. v0.5 intentionally refuses
    to coerce derivative contract/base volume into the spot quote-volume leaderboard.
    """
    if instrument.inst_type is not InstrumentType.SPOT:
        return None
    if quote.vol_ccy_24h is None:
        return None
    value = decimal_fraction(quote.vol_ccy_24h)
    return value if value >= 0 else None


def screen_spot_universe(
    instruments: list[OKXInstrument],
    quotes: list[MarketQuote],
    policy: ScreenPolicy,
    *,
    held_inst_ids: set[str] | None = None,
) -> list[ScreenedInstrument]:
    held_inst_ids = held_inst_ids or set()
    quote_by_id = {q.inst_id: q for q in quotes if q.inst_type is InstrumentType.SPOT}
    minimum = decimal_fraction(policy.min_quote_volume_24h)
    max_spread = decimal_fraction(policy.max_spread_bps)
    rows: list[tuple[str, Fraction, tuple[str, ...], bool]] = []

    for instrument in instruments:
        if instrument.inst_type is not InstrumentType.SPOT:
            continue
        if instrument.quote_ccy != policy.quote_currency:
            continue
        quote = quote_by_id.get(instrument.inst_id)
        held = instrument.inst_id in held_inst_ids
        reasons: list[str] = []

        if instrument.state != "live":
            if held:
                reasons.append("HELD_NON_LIVE_REVIEW_REQUIRED")
                rows.append((instrument.inst_id, Fraction(10**9), tuple(reasons), True))
            continue
        if quote is None:
            if held:
                reasons.append("HELD_MISSING_QUOTE_REVIEW_REQUIRED")
                rows.append((instrument.inst_id, Fraction(10**9), tuple(reasons), True))
            continue

        turnover = _quote_turnover(instrument, quote)
        spread = spread_bps(quote)
        if turnover is None or spread is None:
            if held:
                reasons.append("HELD_INCOMPLETE_MARKET_DATA")
                rows.append((instrument.inst_id, Fraction(10**9), tuple(reasons), True))
            continue

        if turnover < minimum and not held:
            continue
        if spread > max_spread and not held:
            continue

        # Research-priority score: liquidity quality, not expected return.
        # log10-style compression avoids one giant venue dominating every shortlist.
        liquidity_points = Fraction(max(0, int(log(float(turnover + 1), 10) * 10)), 1)
        spread_penalty = min(spread, Fraction(1_000, 1)) / 10
        score = liquidity_points - spread_penalty
        if held:
            score += 10_000
            reasons.append("HELD_POSITION_PRIORITY")
        if turnover >= minimum:
            reasons.append("MINIMUM_TURNOVER_PASSED")
        if spread <= max_spread:
            reasons.append("SPREAD_PASSED")
        rows.append((instrument.inst_id, score, tuple(reasons), held))

    rows.sort(key=lambda row: (not row[3], -row[1], row[0]))
    result: list[ScreenedInstrument] = []
    for rank, (inst_id, score, reasons, held) in enumerate(rows, start=1):
        result.append(
            ScreenedInstrument(
                inst_id=inst_id,
                score=score,
                research_priority=rank,
                reasons=reasons,
                held=held,
            )
        )
    return result


def market_diagnostics(candles: list[Candle]) -> MarketDiagnostics:
    if not candles:
        raise ValueError("at least one candle is required")
    ordered = sorted(candles, key=lambda c: c.ts_ms)
    if any(a.ts_ms >= b.ts_ms for a, b in zip(ordered, ordered[1:])):
        raise ValueError("candle timestamps must be strictly increasing")
    inst_id = ordered[0].inst_id
    if any(c.inst_id != inst_id for c in ordered):
        raise ValueError("diagnostic set mixes instruments")

    closes = [decimal_fraction(c.close) for c in ordered]
    if any(value <= 0 for value in closes):
        raise ValueError("close prices must be positive")

    def horizon_return(hours: int) -> Fraction | None:
        if len(closes) <= hours:
            return None
        return (closes[-1] - closes[-hours - 1]) / closes[-hours - 1]

    peak = closes[0]
    max_dd = Fraction(0, 1)
    for value in closes:
        peak = max(peak, value)
        drawdown = (value - peak) / peak
        max_dd = min(max_dd, drawdown)

    log_returns: list[float] = []
    for old, new in zip(closes, closes[1:]):
        log_returns.append(log(float(new / old)))
    annualized_vol = None
    if len(log_returns) >= 2:
        annualized_vol = pstdev(log_returns) * sqrt(24 * 365)

    return MarketDiagnostics(
        inst_id=inst_id,
        return_24h=horizon_return(24),
        return_7d=horizon_return(24 * 7),
        max_drawdown=max_dd,
        annualized_volatility=annualized_vol,
        bars=len(closes),
    )


def aligned_correlation(left: list[Candle], right: list[Candle]) -> float | None:
    left_map = {c.ts_ms: decimal_fraction(c.close) for c in left}
    right_map = {c.ts_ms: decimal_fraction(c.close) for c in right}
    timestamps = sorted(left_map.keys() & right_map.keys())
    if len(timestamps) < 4:
        return None
    lx: list[float] = []
    rx: list[float] = []
    for a, b in zip(timestamps, timestamps[1:]):
        lx.append(float((left_map[b] - left_map[a]) / left_map[a]))
        rx.append(float((right_map[b] - right_map[a]) / right_map[a]))
    if len(lx) < 3:
        return None
    lmean, rmean = mean(lx), mean(rx)
    numerator = sum((a - lmean) * (b - rmean) for a, b in zip(lx, rx))
    lden = sum((a - lmean) ** 2 for a in lx)
    rden = sum((b - rmean) ** 2 for b in rx)
    if lden == 0 or rden == 0:
        return None
    return numerator / sqrt(lden * rden)
