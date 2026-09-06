from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .exact import decimal_fraction, fraction_decimal


@dataclass(frozen=True)
class Holding:
    asset_id: str
    inst_id: str
    quantity: str
    theme: str | None = None
    chain: str | None = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    nav: str | None
    weights: dict[str, str]
    theme_exposure: dict[str, str]
    chain_exposure: dict[str, str]
    missing_marks: tuple[str, ...]
    complete: bool


def analyze_portfolio(
    holdings: list[Holding],
    marks: dict[str, str],
    *,
    cash: str = "0",
) -> PortfolioSnapshot:
    cash_value = decimal_fraction(cash)
    if cash_value < 0:
        raise ValueError("cash cannot be negative in the spot-only analyzer")

    values: dict[str, Fraction] = {}
    missing: list[str] = []
    themes: dict[str, Fraction] = {}
    chains: dict[str, Fraction] = {}

    seen: set[str] = set()
    for holding in holdings:
        if holding.inst_id in seen:
            raise ValueError("duplicate holding instrument; aggregate before analysis")
        seen.add(holding.inst_id)
        quantity = decimal_fraction(holding.quantity)
        if quantity < 0:
            raise ValueError("negative spot holding not supported")
        if holding.inst_id not in marks:
            missing.append(holding.inst_id)
            continue
        mark = decimal_fraction(marks[holding.inst_id])
        if mark <= 0:
            raise ValueError("marks must be positive")
        value = quantity * mark
        values[holding.inst_id] = value
        if holding.theme:
            themes[holding.theme] = themes.get(holding.theme, Fraction()) + value
        if holding.chain:
            chains[holding.chain] = chains.get(holding.chain, Fraction()) + value

    if missing:
        return PortfolioSnapshot(
            nav=None,
            weights={},
            theme_exposure={k: fraction_decimal(v) for k, v in themes.items()},
            chain_exposure={k: fraction_decimal(v) for k, v in chains.items()},
            missing_marks=tuple(sorted(missing)),
            complete=False,
        )

    nav = cash_value + sum(values.values(), Fraction())
    if nav <= 0:
        raise ValueError("portfolio NAV must be positive")
    weights = {inst_id: fraction_decimal(value / nav) for inst_id, value in values.items()}
    return PortfolioSnapshot(
        nav=fraction_decimal(nav),
        weights=weights,
        theme_exposure={k: fraction_decimal(v / nav) for k, v in themes.items()},
        chain_exposure={k: fraction_decimal(v / nav) for k, v in chains.items()},
        missing_marks=(),
        complete=True,
    )


def violated_exposure_limits(
    snapshot: PortfolioSnapshot,
    *,
    max_single_weight: str,
    max_theme_weight: str,
    max_chain_weight: str,
) -> tuple[str, ...]:
    if not snapshot.complete:
        return ("INCOMPLETE_PORTFOLIO_MARKS",)
    single = decimal_fraction(max_single_weight)
    theme = decimal_fraction(max_theme_weight)
    chain = decimal_fraction(max_chain_weight)
    if any(limit < 0 or limit > 1 for limit in (single, theme, chain)):
        raise ValueError("exposure limits must be within [0, 1]")
    reasons: list[str] = []
    for inst_id, weight in snapshot.weights.items():
        if decimal_fraction(weight) > single:
            reasons.append(f"SINGLE_POSITION:{inst_id}")
    for name, weight in snapshot.theme_exposure.items():
        if decimal_fraction(weight) > theme:
            reasons.append(f"THEME:{name}")
    for name, weight in snapshot.chain_exposure.items():
        if decimal_fraction(weight) > chain:
            reasons.append(f"CHAIN:{name}")
    return tuple(reasons)
