from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction


def decimal_fraction(value: str) -> Fraction:
    """Parse a finite decimal string into an exact Fraction.

    Financial comparisons in Cairn use rational arithmetic. Display formatting may
    round; the stored / compared value does not.
    """
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc
    if not d.is_finite():
        raise ValueError("non-finite values are not allowed")
    sign, digits, exponent = d.as_tuple()
    integer = 0
    for digit in digits:
        integer = integer * 10 + digit
    if sign:
        integer = -integer
    if exponent >= 0:
        return Fraction(integer * (10**exponent), 1)
    return Fraction(integer, 10 ** (-exponent))


def fraction_decimal(value: Fraction, places: int = 18) -> str:
    if places < 0 or places > 30:
        raise ValueError("places must be between 0 and 30")
    scale = 10**places
    scaled = value * scale
    # banker-style precision is not needed for comparisons; display is conservative.
    q = scaled.numerator // scaled.denominator
    negative = q < 0
    q = abs(q)
    whole, frac = divmod(q, scale)
    body = f"{whole}.{frac:0{places}d}" if places else str(whole)
    return f"-{body}" if negative else body


def pct_change(old: str, new: str) -> Fraction:
    base = decimal_fraction(old)
    if base == 0:
        raise ValueError("percentage change has a zero denominator")
    return (decimal_fraction(new) - base) / abs(base)


def bps(value: Fraction) -> Fraction:
    return value * 10_000
