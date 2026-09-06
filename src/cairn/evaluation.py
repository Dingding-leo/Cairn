from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from random import Random

from .exact import decimal_fraction, fraction_decimal


@dataclass(frozen=True)
class ForecastOutcome:
    case_id: str
    cluster_id: str
    baseline_probability: str
    candidate_probability: str
    outcome: int
    baseline_cost_usd: str = "0"
    candidate_cost_usd: str = "0"
    baseline_latency_ms: int = 0
    candidate_latency_ms: int = 0
    baseline_critical_error: bool = False
    candidate_critical_error: bool = False


@dataclass(frozen=True)
class TrialReport:
    cases: int
    clusters: int
    baseline_brier: str
    candidate_brier: str
    brier_improvement: str
    critical_error_delta: int
    cost_ratio: str | None
    latency_ratio: str | None
    advantage_proven: bool
    reason_codes: tuple[str, ...]


def _brier(probability: str, outcome: int) -> Fraction:
    if outcome not in {0, 1}:
        raise ValueError("binary outcome must be 0 or 1")
    p = decimal_fraction(probability)
    if not 0 <= p <= 1:
        raise ValueError("probability must be in [0, 1]")
    return (p - outcome) ** 2


def evaluate_trial(
    outcomes: list[ForecastOutcome],
    *,
    min_cases: int = 50,
    min_clusters: int = 20,
    required_brier_improvement: str = "0.02",
    max_cost_ratio: str = "2",
    max_latency_ratio: str = "3",
) -> TrialReport:
    if len(outcomes) < 1:
        raise ValueError("trial contains no outcomes")
    baseline = sum((_brier(x.baseline_probability, x.outcome) for x in outcomes), Fraction(0, 1)) / len(outcomes)
    candidate = sum((_brier(x.candidate_probability, x.outcome) for x in outcomes), Fraction(0, 1)) / len(outcomes)
    improvement = baseline - candidate
    clusters = len({x.cluster_id for x in outcomes})
    baseline_critical = sum(x.baseline_critical_error for x in outcomes)
    candidate_critical = sum(x.candidate_critical_error for x in outcomes)

    base_cost = sum((decimal_fraction(x.baseline_cost_usd) for x in outcomes), Fraction(0, 1))
    cand_cost = sum((decimal_fraction(x.candidate_cost_usd) for x in outcomes), Fraction(0, 1))
    cost_ratio = None if base_cost == 0 else cand_cost / base_cost
    base_latency = sum(x.baseline_latency_ms for x in outcomes)
    cand_latency = sum(x.candidate_latency_ms for x in outcomes)
    latency_ratio = None if base_latency == 0 else Fraction(cand_latency, base_latency)

    reasons: list[str] = []
    if len(outcomes) < min_cases:
        reasons.append("INSUFFICIENT_CASES")
    if clusters < min_clusters:
        reasons.append("INSUFFICIENT_CLUSTERS")
    if improvement < decimal_fraction(required_brier_improvement):
        reasons.append("BRIER_IMPROVEMENT_TOO_SMALL")
    if candidate_critical > baseline_critical:
        reasons.append("CRITICAL_ERRORS_INCREASED")
    if cost_ratio is not None and cost_ratio > decimal_fraction(max_cost_ratio):
        reasons.append("COST_RATIO_EXCEEDED")
    if latency_ratio is not None and latency_ratio > decimal_fraction(max_latency_ratio):
        reasons.append("LATENCY_RATIO_EXCEEDED")

    return TrialReport(
        cases=len(outcomes),
        clusters=clusters,
        baseline_brier=fraction_decimal(baseline),
        candidate_brier=fraction_decimal(candidate),
        brier_improvement=fraction_decimal(improvement),
        critical_error_delta=candidate_critical - baseline_critical,
        cost_ratio=None if cost_ratio is None else fraction_decimal(cost_ratio),
        latency_ratio=None if latency_ratio is None else fraction_decimal(latency_ratio),
        advantage_proven=not reasons,
        reason_codes=tuple(reasons),
    )


def cluster_bootstrap_brier_delta(
    outcomes: list[ForecastOutcome], *, seed: int = 42, samples: int = 2_000
) -> tuple[float, float]:
    """Cluster bootstrap interval for candidate-minus-baseline Brier score.

    This statistical helper intentionally uses floating point. It is an uncertainty
    estimate, not an accounting or authorization calculation.
    """
    if samples < 100 or samples > 100_000:
        raise ValueError("bootstrap sample count outside allowed range")
    grouped: dict[str, list[ForecastOutcome]] = {}
    for row in outcomes:
        grouped.setdefault(row.cluster_id, []).append(row)
    clusters = sorted(grouped)
    if len(clusters) < 2:
        raise ValueError("need at least two clusters")
    rng = Random(seed)
    draws: list[float] = []
    for _ in range(samples):
        selected = [rng.choice(clusters) for _ in clusters]
        rows = [row for cluster in selected for row in grouped[cluster]]
        baseline = sum(float(_brier(x.baseline_probability, x.outcome)) for x in rows) / len(rows)
        candidate = sum(float(_brier(x.candidate_probability, x.outcome)) for x in rows) / len(rows)
        draws.append(candidate - baseline)
    draws.sort()
    lo = draws[int(samples * 0.025)]
    hi = draws[min(samples - 1, int(samples * 0.975))]
    return lo, hi
