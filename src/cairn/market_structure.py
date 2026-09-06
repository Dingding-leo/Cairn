from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .exact import decimal_fraction, fraction_decimal


@dataclass(frozen=True)
class ExecutionEstimate:
    side: str
    requested_base: str
    executable_base: str
    average_price: str | None
    slippage_bps: str | None
    complete: bool
    reason_codes: tuple[str, ...]


def _levels(raw: Any) -> list[tuple[Fraction, Fraction]]:
    if not isinstance(raw, list):
        raise ValueError("order-book side must be a list")
    levels: list[tuple[Fraction, Fraction]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            raise ValueError("malformed order-book level")
        price = decimal_fraction(str(item[0]))
        size = decimal_fraction(str(item[1]))
        if price <= 0 or size < 0:
            raise ValueError("invalid price/size in order book")
        if size:
            levels.append((price, size))
    return levels


def estimate_market_cost(
    book: dict[str, Any],
    *,
    side: str,
    base_quantity: str,
    usable_depth_fraction: str = "0.5",
) -> ExecutionEstimate:
    """Estimate adverse book walk without pretending it is a fill simulation.

    `usable_depth_fraction` applies a conservative haircut to displayed top-of-book
    quantities. Queue position, hidden liquidity, latency, and market impact are not
    modelled here and remain reasons shadow execution is a separate gate.
    """
    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    target = decimal_fraction(base_quantity)
    haircut = decimal_fraction(usable_depth_fraction)
    if target <= 0 or not 0 < haircut <= 1:
        raise ValueError("invalid quantity or depth haircut")

    raw = book.get("asks") if side == "BUY" else book.get("bids")
    levels = _levels(raw)
    if not levels:
        return ExecutionEstimate(side, base_quantity, "0", None, None, False, ("EMPTY_BOOK",))

    best = levels[0][0]
    remaining = target
    executable = Fraction(0, 1)
    total_quote = Fraction(0, 1)
    for price, displayed_size in levels:
        available = displayed_size * haircut
        take = min(remaining, available)
        total_quote += take * price
        executable += take
        remaining -= take
        if remaining <= 0:
            break

    if executable == 0:
        return ExecutionEstimate(side, base_quantity, "0", None, None, False, ("NO_USABLE_DEPTH",))
    average = total_quote / executable
    slippage = (average - best) / best if side == "BUY" else (best - average) / best
    return ExecutionEstimate(
        side=side,
        requested_base=base_quantity,
        executable_base=fraction_decimal(executable),
        average_price=fraction_decimal(average),
        slippage_bps=fraction_decimal(slippage * 10_000),
        complete=remaining <= 0,
        reason_codes=() if remaining <= 0 else ("INSUFFICIENT_DISPLAYED_DEPTH",),
    )
