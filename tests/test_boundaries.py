import pytest

from cairn.market_structure import estimate_market_cost
from cairn.okx import OKXPolicy
from cairn.portfolio import Holding, analyze_portfolio, violated_exposure_limits


def test_okx_host_allowlist_rejects_arbitrary_host():
    with pytest.raises(ValueError):
        OKXPolicy(host="evil.example")


def test_okx_timeout_is_bounded():
    with pytest.raises(ValueError):
        OKXPolicy(timeout_seconds=60)


def test_market_cost_requires_valid_side():
    with pytest.raises(ValueError):
        estimate_market_cost({"asks": [], "bids": []}, side="HOLD", base_quantity="1")


def test_market_cost_refuses_negative_size():
    with pytest.raises(ValueError):
        estimate_market_cost(
            {"asks": [["100", "-1"]], "bids": [["99", "1"]]},
            side="BUY",
            base_quantity="1",
        )


def test_complete_portfolio_weights_and_exposure():
    snapshot = analyze_portfolio(
        [
            Holding("BTC", "BTC-USDT", "1", theme="monetary", chain="bitcoin"),
            Holding("ETH", "ETH-USDT", "10", theme="smart-contract", chain="ethereum"),
        ],
        {"BTC-USDT": "50000", "ETH-USDT": "2500"},
        cash="25000",
    )
    assert snapshot.complete
    assert snapshot.nav is not None
    reasons = violated_exposure_limits(
        snapshot,
        max_single_weight="0.4",
        max_theme_weight="0.5",
        max_chain_weight="0.5",
    )
    assert "SINGLE_POSITION:BTC-USDT" in reasons


def test_incomplete_marks_block_limit_analysis():
    snapshot = analyze_portfolio([Holding("BTC", "BTC-USDT", "1")], {}, cash="100")
    assert violated_exposure_limits(
        snapshot,
        max_single_weight="0.5",
        max_theme_weight="0.5",
        max_chain_weight="0.5",
    ) == ("INCOMPLETE_PORTFOLIO_MARKS",)
