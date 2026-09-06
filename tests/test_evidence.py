from datetime import datetime, timedelta, timezone

from cairn.evidence import compare_sources, eligible_for_cutoff, verify_numeric_claim
from cairn.models import DataMode, Evidence, MetricObservation

UTC = timezone.utc
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def evidence(**overrides):
    values = dict(
        evidence_id="e1",
        asset_id="AAVE",
        source_uri="https://example.invalid/source",
        title="fixture",
        content_sha256="0" * 64,
        published_at=T0,
        observed_at=T0 + timedelta(hours=1),
        ingested_at=T0 + timedelta(hours=2),
        method="fixture",
        mode=DataMode.PROSPECTIVE,
        admitted=True,
    )
    values.update(overrides)
    return Evidence(**values)


def observation(value="100", unit="USD", *, source="o1"):
    return MetricObservation(
        observation_id=source,
        asset_id="AAVE",
        metric="holder_revenue",
        value=value,
        unit=unit,
        period_start=T0,
        period_end=T0 + timedelta(days=1),
        observed_at=T0 + timedelta(days=1),
        evidence_ids=("e1",),
        methodology="fixture",
        mode=DataMode.RECONSTRUCTED,
    )


def test_prospective_cutoff_requires_ingestion_before_cutoff():
    e = evidence()
    assert not eligible_for_cutoff(e, T0 + timedelta(hours=1, minutes=30), DataMode.PROSPECTIVE)
    assert eligible_for_cutoff(e, T0 + timedelta(hours=3), DataMode.PROSPECTIVE)


def test_unadmitted_evidence_is_ineligible():
    assert not eligible_for_cutoff(evidence(admitted=False), T0 + timedelta(days=1), DataMode.PROSPECTIVE)


def test_reconstructed_data_is_not_relabelled_prospective():
    e = evidence(mode=DataMode.RECONSTRUCTED, ingested_at=T0 + timedelta(days=100))
    assert not eligible_for_cutoff(e, T0 + timedelta(days=1), DataMode.PROSPECTIVE)
    assert eligible_for_cutoff(e, T0 + timedelta(days=1), DataMode.RECONSTRUCTED)


def test_numeric_claim_rejects_unit_mismatch():
    result = verify_numeric_claim(reported_value="100", reported_unit="TOKEN", observation=observation())
    assert result.status == "INCOMPARABLE"


def test_numeric_claim_zero_values_compare_correctly():
    result = verify_numeric_claim(reported_value="0", reported_unit="USD", observation=observation("0"))
    assert result.status == "MATCH"


def test_source_comparison_exposes_disagreement():
    result = compare_sources([("source-a", observation("100", source="a")), ("source-b", observation("120", source="b"))])
    assert result.status == "DISAGREE"
    assert "DATA_DISAGREEMENT" in result.reason_codes


def test_source_group_overlap_is_visible_even_when_values_agree():
    result = compare_sources([("same-parent", observation("100", source="a")), ("same-parent", observation("100", source="b"))])
    assert result.status == "AGREE"
    assert "SOURCE_GROUP_OVERLAP" in result.reason_codes
