from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__version__ = "0.5.0rc1"

DecimalStr = Annotated[str, Field(pattern=r"^-?(0|[1-9]\d*)(\.\d+)?$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DataMode(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    PROSPECTIVE = "PROSPECTIVE"
    RECONSTRUCTED = "RECONSTRUCTED"


class InstrumentType(StrEnum):
    SPOT = "SPOT"
    SWAP = "SWAP"
    FUTURES = "FUTURES"
    OPTION = "OPTION"


class AssetCategory(StrEnum):
    MONETARY = "MONETARY"
    CASH_FLOW = "CASH_FLOW"
    BUYBACK_BURN = "BUYBACK_BURN"
    STAKING = "STAKING"
    GOVERNANCE = "GOVERNANCE"
    STABLECOIN = "STABLECOIN"
    L1_L2 = "L1_L2"
    RWA = "RWA"
    SPECULATIVE = "SPECULATIVE"
    UNKNOWN = "UNKNOWN"


class Decision(StrEnum):
    RESEARCH_ELIGIBLE = "RESEARCH_ELIGIBLE"
    WATCH = "WATCH"
    ABSTAIN = "ABSTAIN"


class Asset(StrictModel):
    asset_id: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    category: AssetCategory = AssetCategory.UNKNOWN
    chain: str | None = Field(default=None, max_length=80)
    contract_address: str | None = Field(default=None, max_length=200)


class OKXInstrument(StrictModel):
    inst_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{1,79}$")
    inst_type: InstrumentType
    state: str = Field(min_length=1, max_length=32)
    base_ccy: str | None = Field(default=None, max_length=32)
    quote_ccy: str | None = Field(default=None, max_length=32)
    settle_ccy: str | None = Field(default=None, max_length=32)
    tick_sz: DecimalStr | None = None
    lot_sz: DecimalStr | None = None
    min_sz: DecimalStr | None = None
    ct_val: DecimalStr | None = None
    ct_val_ccy: str | None = Field(default=None, max_length=32)
    expiry_ms: int | None = Field(default=None, ge=0)


class MarketQuote(StrictModel):
    inst_id: str
    inst_type: InstrumentType
    ts_ms: int = Field(ge=1)
    last: DecimalStr
    bid: DecimalStr | None = None
    ask: DecimalStr | None = None
    bid_sz: DecimalStr | None = None
    ask_sz: DecimalStr | None = None
    vol_24h: DecimalStr | None = None
    vol_ccy_24h: DecimalStr | None = None
    source: Literal["OKX_PUBLIC", "FIXTURE"]

    @model_validator(mode="after")
    def validate_book(self) -> "MarketQuote":
        if (self.bid is None) != (self.ask is None):
            raise ValueError("bid and ask must be supplied together")
        return self


class Candle(StrictModel):
    inst_id: str
    ts_ms: int = Field(ge=1)
    open: DecimalStr
    high: DecimalStr
    low: DecimalStr
    close: DecimalStr
    volume: DecimalStr
    confirm: bool = True


class Evidence(StrictModel):
    evidence_id: str
    asset_id: str
    source_uri: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    method: str = Field(min_length=1, max_length=200)
    mode: DataMode
    admitted: bool = False

    @model_validator(mode="after")
    def validate_time(self) -> "Evidence":
        for value in (self.published_at, self.observed_at, self.ingested_at):
            if value.tzinfo is None:
                raise ValueError("timestamps must be timezone-aware")
        if self.mode == DataMode.PROSPECTIVE and not (
            self.published_at <= self.observed_at <= self.ingested_at
        ):
            raise ValueError("prospective evidence timestamps must be monotonic")
        return self


class MetricObservation(StrictModel):
    observation_id: str
    asset_id: str
    metric: str
    value: DecimalStr
    unit: str
    period_start: datetime
    period_end: datetime
    observed_at: datetime
    evidence_ids: tuple[str, ...] = ()
    methodology: str
    mode: DataMode

    @model_validator(mode="after")
    def validate_period(self) -> "MetricObservation":
        if self.period_start > self.period_end:
            raise ValueError("period_start must not exceed period_end")
        return self


class TokenSupplySnapshot(StrictModel):
    snapshot_id: str
    asset_id: str
    observed_at: datetime
    circulating: DecimalStr | None = None
    total: DecimalStr | None = None
    fully_diluted: DecimalStr | None = None
    maximum: DecimalStr | None = None
    unit: str
    evidence_ids: tuple[str, ...]
    mode: DataMode


class UnlockEvent(StrictModel):
    unlock_id: str
    asset_id: str
    announced_at: datetime
    unlock_at: datetime
    amount: DecimalStr
    unit: str
    category: str
    evidence_ids: tuple[str, ...]
    mode: DataMode

    @model_validator(mode="after")
    def validate_unlock(self) -> "UnlockEvent":
        if self.announced_at > self.unlock_at:
            raise ValueError("unlock cannot precede its announcement")
        return self


class ValueCaptureEdge(StrictModel):
    edge_id: str
    asset_id: str
    source: str
    destination: str
    mechanism: str
    eligible_fraction: DecimalStr = "1"
    evidence_ids: tuple[str, ...]
    active: bool = True


class Scenario(StrictModel):
    name: Literal["bear", "base", "bull"]
    probability: DecimalStr
    annual_holder_flow: DecimalStr | None = None
    terminal_growth: DecimalStr | None = None
    discount_rate: DecimalStr | None = None
    monetary_value: DecimalStr | None = None
    years: int = Field(default=5, ge=1, le=30)


class ValuationInput(StrictModel):
    valuation_id: str
    asset_id: str
    category: AssetCategory
    as_of: datetime
    denominator: DecimalStr | None
    currency: str
    scenarios: tuple[Scenario, Scenario, Scenario]
    evidence_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @field_validator("scenarios")
    @classmethod
    def unique_scenarios(cls, value: tuple[Scenario, Scenario, Scenario]):
        if {x.name for x in value} != {"bear", "base", "bull"}:
            raise ValueError("valuation requires bear/base/bull scenarios")
        return value


class ValuationResult(StrictModel):
    valuation_id: str
    status: Literal["SCENARIO_ONLY", "UNPRICED"]
    scenario_prices: dict[str, str] = Field(default_factory=dict)
    expected_price: str | None = None
    reason_codes: tuple[str, ...] = ()


class DecisionCard(StrictModel):
    card_id: str
    asset_id: str
    created_at: datetime
    valid_until: datetime
    market_price: DecimalStr
    currency: str
    valuation_id: str | None = None
    decision: Decision
    thesis: str
    invalidations: tuple[str, ...]
    key_unknowns: tuple[str, ...] = ()
    expected_round_trip_cost_bps: DecimalStr = "0"

    @model_validator(mode="after")
    def validate_window(self) -> "DecisionCard":
        if self.created_at >= self.valid_until:
            raise ValueError("decision card must have a positive validity window")
        return self


class AgentOpinion(StrictModel):
    opinion_id: str
    asset_id: str
    role: str
    model_family: str
    created_at: datetime
    stance: Literal["BULL", "NEUTRAL", "BEAR", "ABSTAIN"]
    confidence: DecimalStr
    claims: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    blockers: tuple[str, ...] = ()


class ThesisRevision(StrictModel):
    thesis_id: str
    asset_id: str
    revision: int = Field(ge=1)
    adopted_at: datetime
    owner: str
    decision_card_id: str
    assumptions: tuple[str, ...]
    invalidations: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    status: Literal["ACTIVE", "SUPERSEDED", "CLOSED"] = "ACTIVE"


class PaperAction(StrictModel):
    action_id: str
    account_id: str
    idempotency_key: str
    expected_sequence: int = Field(ge=0)
    ts: datetime
    inst_id: str
    side: Literal["BUY", "SELL"]
    quantity: DecimalStr
    price: DecimalStr
    fee: DecimalStr = "0"
    rationale: str


class ProspectiveForecast(StrictModel):
    forecast_id: str
    asset_id: str
    created_at: datetime
    resolves_at: datetime
    probability: DecimalStr
    question: str
    resolution_rule: str
    model_arm: str

    @model_validator(mode="after")
    def validate_resolution(self) -> "ProspectiveForecast":
        if self.created_at >= self.resolves_at:
            raise ValueError("forecast must resolve in the future")
        return self


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
