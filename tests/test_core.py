from datetime import datetime, timezone
from fractions import Fraction

import pytest

from cairn.evaluation import ForecastOutcome, evaluate_trial
from cairn.exact import decimal_fraction
from cairn.market_structure import estimate_market_cost
from cairn.models import (
    AssetCategory,
    Candle,
    Decision,
    DecisionCard,
    InstrumentType,
    MarketQuote,
    OKXInstrument,
    PaperAction,
    Scenario,
    ValuationInput,
)
from cairn.paper import apply_action, create_account, mark_to_market
from cairn.portfolio import Holding, analyze_portfolio
from cairn.universe import ScreenPolicy, market_diagnostics, screen_spot_universe
from cairn.valuation import reverse_price_grid, value_asset
from cairn.workflow import ResearchRun, RunState, blind_peer_visible, record_first_pass, transition

UTC = timezone.utc
NOW = datetime(2026, 9, 6, 5, 0, tzinfo=UTC)


def test_decimal_fraction_is_exact():
    assert decimal_fraction("0.1") + decimal_fraction("0.2") == Fraction(3, 10)


def test_monetary_valuation_is_not_equity_dcf():
    value = ValuationInput(
        valuation_id="btc-v1",
        asset_id="BTC",
        category=AssetCategory.MONETARY,
        as_of=NOW,
        denominator="21000000",
        currency="USD",
        evidence_ids=("e1",),
        scenarios=(
            Scenario(name="bear", probability="0.25", monetary_value="500000000000"),
            Scenario(name="base", probability="0.5", monetary_value="2000000000000"),
            Scenario(name="bull", probability="0.25", monetary_value="5000000000000"),
        ),
    )
    result = value_asset(value)
    assert result.status == "SCENARIO_ONLY"
    assert set(result.scenario_prices) == {"bear", "base", "bull"}


def test_governance_only_asset_refuses_fake_valuation():
    value = ValuationInput(
        valuation_id="gov-v1",
        asset_id="GOV",
        category=AssetCategory.GOVERNANCE,
        as_of=NOW,
        denominator="1000000",
        currency="USD",
        evidence_ids=("e1",),
        scenarios=(
            Scenario(name="bear", probability="0.3"),
            Scenario(name="base", probability="0.4"),
            Scenario(name="bull", probability="0.3"),
        ),
    )
    assert value_asset(value).status == "UNPRICED"


def test_reverse_valuation_returns_condition_grid():
    grid = reverse_price_grid(
        market_price="10",
        denominator="1000000",
        discount_rates=("0.15", "0.20"),
        terminal_growth_rates=("0.02", "0.05"),
    )
    assert len(grid) == 4
    assert "r=0.15|g=0.02" in grid


def test_held_position_is_not_dropped_by_screen():
    inst = OKXInstrument(
        inst_id="AAA-USDT",
        inst_type=InstrumentType.SPOT,
        state="live",
        base_ccy="AAA",
        quote_ccy="USDT",
    )
    quote = MarketQuote(
        inst_id="AAA-USDT",
        inst_type=InstrumentType.SPOT,
        ts_ms=1,
        last="1",
        bid="0.9",
        ask="1.1",
        bid_sz="1",
        ask_sz="1",
        vol_24h="1",
        vol_ccy_24h="100",
        source="FIXTURE",
    )
    ranked = screen_spot_universe(
        [inst], [quote], ScreenPolicy(min_quote_volume_24h="1000000", max_spread_bps="10"),
        held_inst_ids={"AAA-USDT"},
    )
    assert ranked and ranked[0].held


def test_market_diagnostics_do_not_invent_long_history():
    candles = [
        Candle(inst_id="BTC-USDT", ts_ms=i * 3_600_000 + 1, open="1", high="1", low="1", close=str(100+i), volume="1")
        for i in range(25)
    ]
    report = market_diagnostics(candles)
    assert report.return_24h is not None
    assert report.return_7d is None


def test_book_estimator_reports_insufficient_depth():
    estimate = estimate_market_cost(
        {"asks": [["100", "1", "0", "1"]], "bids": [["99", "1", "0", "1"]]},
        side="BUY",
        base_quantity="2",
        usable_depth_fraction="0.5",
    )
    assert not estimate.complete
    assert "INSUFFICIENT_DISPLAYED_DEPTH" in estimate.reason_codes


def test_paper_ledger_forbids_margin_and_shorting():
    state = create_account("100")
    with pytest.raises(ValueError):
        apply_action(
            state,
            PaperAction(
                action_id="a1", account_id="p", idempotency_key="x", expected_sequence=0,
                ts=NOW, inst_id="BTC-USDT", side="BUY", quantity="2", price="100", rationale="fixture"
            ),
        )
    with pytest.raises(ValueError):
        apply_action(
            state,
            PaperAction(
                action_id="a2", account_id="p", idempotency_key="y", expected_sequence=0,
                ts=NOW, inst_id="BTC-USDT", side="SELL", quantity="1", price="100", rationale="fixture"
            ),
        )


def test_paper_nav_requires_all_marks():
    state = create_account("1000")
    state, _ = apply_action(
        state,
        PaperAction(
            action_id="a1", account_id="p", idempotency_key="x", expected_sequence=0,
            ts=NOW, inst_id="BTC-USDT", side="BUY", quantity="1", price="100", rationale="fixture"
        ),
    )
    with pytest.raises(ValueError):
        mark_to_market(state, {})


def test_portfolio_refuses_partial_nav():
    snapshot = analyze_portfolio([Holding("BTC", "BTC-USDT", "1")], {}, cash="10")
    assert not snapshot.complete
    assert snapshot.nav is None


def test_blind_first_pass_barrier():
    run = ResearchRun("r1", RunState.INPUTS_FROZEN, "abc", analyst_count=2)
    run = transition(run, RunState.RUNNING)
    run = record_first_pass(run)
    assert not blind_peer_visible(run)
    with pytest.raises(ValueError):
        transition(run, RunState.READY_FOR_REVIEW)
    run = record_first_pass(run)
    run = transition(run, RunState.READY_FOR_REVIEW)
    run = transition(run, RunState.CROSS_EXAMINING)
    assert blind_peer_visible(run)


def test_terminal_research_run_cannot_reopen():
    run = ResearchRun("r1", RunState.RUNNING, "abc", analyst_count=1, completed_first_passes=1)
    run = transition(run, RunState.READY_FOR_REVIEW)
    run = transition(run, RunState.ACCEPTED)
    with pytest.raises(ValueError):
        transition(run, RunState.RUNNING)


def test_trial_gate_rejects_small_sample_even_if_score_is_better():
    rows = [
        ForecastOutcome(str(i), str(i), "0.5", "0.9", 1, baseline_cost_usd="1", candidate_cost_usd="1")
        for i in range(10)
    ]
    report = evaluate_trial(rows)
    assert not report.advantage_proven
    assert "INSUFFICIENT_CASES" in report.reason_codes
