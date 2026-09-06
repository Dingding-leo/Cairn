from __future__ import annotations

from fractions import Fraction

from .exact import decimal_fraction, fraction_decimal
from .models import AssetCategory, Scenario, ValuationInput, ValuationResult


def _probabilities(value: ValuationInput) -> dict[str, Fraction]:
    probs = {s.name: decimal_fraction(s.probability) for s in value.scenarios}
    if any(p < 0 or p > 1 for p in probs.values()):
        raise ValueError("scenario probabilities must be in [0, 1]")
    if sum(probs.values(), Fraction(0, 1)) != 1:
        raise ValueError("scenario probabilities must sum exactly to 1")
    return probs


def _cash_flow_price(scenario: Scenario, denominator: Fraction) -> Fraction:
    if scenario.annual_holder_flow is None:
        raise ValueError("holder cash-flow scenario requires annual_holder_flow")
    if scenario.discount_rate is None or scenario.terminal_growth is None:
        raise ValueError("holder cash-flow scenario requires discount and terminal growth")
    flow = decimal_fraction(scenario.annual_holder_flow)
    r = decimal_fraction(scenario.discount_rate)
    g = decimal_fraction(scenario.terminal_growth)
    if flow < 0:
        raise ValueError("negative holder flow requires a separate loss model")
    if r <= g:
        raise ValueError("discount rate must exceed terminal growth")
    if denominator <= 0:
        raise ValueError("valuation denominator must be positive")

    pv = Fraction(0, 1)
    current = flow
    one = Fraction(1, 1)
    for year in range(1, scenario.years + 1):
        pv += current / ((one + r) ** year)
        current *= one + g
    terminal = current / (r - g)
    pv += terminal / ((one + r) ** scenario.years)
    return pv / denominator


def _monetary_price(scenario: Scenario, denominator: Fraction) -> Fraction:
    if scenario.monetary_value is None:
        raise ValueError("monetary scenario requires monetary_value")
    value = decimal_fraction(scenario.monetary_value)
    if value < 0 or denominator <= 0:
        raise ValueError("invalid monetary valuation inputs")
    return value / denominator


def value_asset(value: ValuationInput) -> ValuationResult:
    """Compute an auditable scenario valuation or explicitly refuse to price.

    The function intentionally has no branch that maps generic protocol revenue to
    token value. Economic rights must already be represented by category-appropriate
    inputs and an explicit denominator.
    """
    probs = _probabilities(value)
    if value.denominator is None:
        return ValuationResult(
            valuation_id=value.valuation_id,
            status="UNPRICED",
            reason_codes=("MISSING_DENOMINATOR",),
        )
    denominator = decimal_fraction(value.denominator)
    if denominator <= 0:
        return ValuationResult(
            valuation_id=value.valuation_id,
            status="UNPRICED",
            reason_codes=("INVALID_DENOMINATOR",),
        )

    prices: dict[str, Fraction] = {}
    try:
        for scenario in value.scenarios:
            if value.category is AssetCategory.MONETARY:
                prices[scenario.name] = _monetary_price(scenario, denominator)
            elif value.category in {
                AssetCategory.CASH_FLOW,
                AssetCategory.BUYBACK_BURN,
                AssetCategory.STAKING,
                AssetCategory.STABLECOIN,
                AssetCategory.RWA,
            }:
                prices[scenario.name] = _cash_flow_price(scenario, denominator)
            else:
                return ValuationResult(
                    valuation_id=value.valuation_id,
                    status="UNPRICED",
                    reason_codes=("CATEGORY_HAS_NO_VALIDATED_NUMERICAL_MODEL",),
                )
    except ValueError as exc:
        return ValuationResult(
            valuation_id=value.valuation_id,
            status="UNPRICED",
            reason_codes=(f"INVALID_MODEL_INPUT:{exc}",),
        )

    expected = sum(prices[name] * probs[name] for name in prices)
    return ValuationResult(
        valuation_id=value.valuation_id,
        status="SCENARIO_ONLY",
        scenario_prices={name: fraction_decimal(price) for name, price in prices.items()},
        expected_price=fraction_decimal(expected),
    )


def price_gap(expected_price: str, market_price: str, round_trip_cost_bps: str = "0") -> Fraction:
    expected = decimal_fraction(expected_price)
    market = decimal_fraction(market_price)
    cost = decimal_fraction(round_trip_cost_bps) / 10_000
    if expected < 0 or market <= 0 or cost < 0:
        raise ValueError("invalid price-gap input")
    friction_adjusted_entry = market * (1 + cost)
    return (expected - friction_adjusted_entry) / friction_adjusted_entry


def reverse_price_grid(
    *,
    market_price: str,
    denominator: str,
    discount_rates: tuple[str, ...],
    terminal_growth_rates: tuple[str, ...],
) -> dict[str, str]:
    """Return the holder flow required to support price under each r/g pair.

    This is a conditional grid, not a claim that the market has one unique implied
    growth rate.
    """
    p = decimal_fraction(market_price)
    n = decimal_fraction(denominator)
    if p <= 0 or n <= 0:
        raise ValueError("market price and denominator must be positive")
    result: dict[str, str] = {}
    for r_text in discount_rates:
        r = decimal_fraction(r_text)
        for g_text in terminal_growth_rates:
            g = decimal_fraction(g_text)
            if r <= g:
                continue
            required_flow = p * n * (r - g)
            result[f"r={r_text}|g={g_text}"] = fraction_decimal(required_flow)
    if not result:
        raise ValueError("no valid reverse-valuation cells")
    return result
