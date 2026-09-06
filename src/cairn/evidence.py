from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from .exact import decimal_fraction
from .models import DataMode, Evidence, MetricObservation


@dataclass(frozen=True)
class NumericClaimCheck:
    status: str
    reported: Fraction | None
    observed: Fraction | None
    deviation: Fraction | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class SourceComparison:
    status: str
    values: tuple[tuple[str, Fraction], ...]
    reason_codes: tuple[str, ...]


def eligible_for_cutoff(evidence: Evidence, cutoff: datetime, mode: DataMode) -> bool:
    if evidence.mode != mode or not evidence.admitted:
        return False
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    if mode is DataMode.PROSPECTIVE:
        return max(evidence.published_at, evidence.observed_at, evidence.ingested_at) <= cutoff
    if mode is DataMode.RECONSTRUCTED:
        # Reconstructed data is useful for research replay, but it is never relabelled
        # as something the system prospectively possessed at that historical cutoff.
        return evidence.published_at <= cutoff
    return evidence.observed_at <= cutoff


def verify_numeric_claim(
    *,
    reported_value: str,
    reported_unit: str,
    observation: MetricObservation,
    tolerance_bps: str = "0",
) -> NumericClaimCheck:
    if observation.unit != reported_unit:
        return NumericClaimCheck(
            status="INCOMPARABLE",
            reported=None,
            observed=None,
            deviation=None,
            reason_codes=("UNIT_MISMATCH",),
        )
    reported = decimal_fraction(reported_value)
    observed = decimal_fraction(observation.value)
    tolerance = decimal_fraction(tolerance_bps) / 10_000
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    if reported == observed:
        return NumericClaimCheck("MATCH", reported, observed, Fraction(0, 1), ())
    scale = max(abs(reported), abs(observed))
    if scale == 0:
        deviation = Fraction(0, 1)
    else:
        deviation = abs(reported - observed) / scale
    return NumericClaimCheck(
        status="WITHIN_TOLERANCE" if deviation <= tolerance else "MISMATCH",
        reported=reported,
        observed=observed,
        deviation=deviation,
        reason_codes=() if deviation <= tolerance else ("NUMERIC_DISAGREEMENT",),
    )


def compare_sources(
    observations: list[tuple[str, MetricObservation]],
    *,
    tolerance_bps: str = "0",
) -> SourceComparison:
    """Expose disagreement rather than averaging incompatible sources.

    `source_group` should identify genuinely shared upstream methodology where known.
    The function does not claim that different labels prove source independence.
    """
    if len(observations) < 2:
        return SourceComparison("INSUFFICIENT", (), ("NEED_AT_LEAST_TWO_SOURCES",))
    first = observations[0][1]
    comparable: list[tuple[str, Fraction]] = []
    for source_group, observation in observations:
        if observation.metric != first.metric or observation.unit != first.unit:
            return SourceComparison("INCOMPARABLE", (), ("METHOD_OR_UNIT_MISMATCH",))
        if observation.period_start != first.period_start or observation.period_end != first.period_end:
            return SourceComparison("INCOMPARABLE", (), ("PERIOD_MISMATCH",))
        comparable.append((source_group, decimal_fraction(observation.value)))
    tolerance = decimal_fraction(tolerance_bps) / 10_000
    values = [value for _, value in comparable]
    scale = max(abs(value) for value in values)
    spread = max(values) - min(values)
    if scale == 0:
        agrees = spread == 0
    else:
        agrees = spread / scale <= tolerance
    groups = [group for group, _ in comparable]
    duplicate_group = len(set(groups)) != len(groups)
    reasons: list[str] = []
    if duplicate_group:
        reasons.append("SOURCE_GROUP_OVERLAP")
    if not agrees:
        reasons.append("DATA_DISAGREEMENT")
    return SourceComparison(
        "AGREE" if agrees else "DISAGREE",
        tuple(comparable),
        tuple(reasons),
    )
