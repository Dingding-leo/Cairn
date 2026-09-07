"""All data in this test module are synthetic, never forward paper observations."""
import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, localcontext
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("chat_round", ROOT / "scripts/cairn_chat_round.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = datetime(2026, 9, 7, 8, 26, 2, tzinfo=timezone.utc)


def fixture():
    account = {"epoch": "cairn-500-usdt-20260906-v1", "historical_initial_capital_usdt": "500",
               "current_cash_usdt": "500", "current_nav_usdt": "500", "positions": [], "ledger_sequence": 0,
               "verification": "VERIFIED_JOURNAL_CHECKPOINT", "checkpoint_provenance": "SYNTHETIC_TEST_ONLY",
               "realized_net_pnl_usdt": {"CORE": "0", "EXPLORATION": "0", "LEGACY": "0"}, "fees_usdt": "0",
               "day": {"date": "2026-09-07", "start_nav_usdt": "500"}}
    previous = {"mode": m.MODE, "cycle_id": "synthetic-prior", "account": account, "status": "SYNTHETIC_TEST_ONLY"}
    market = {}
    def add(key, rows):
        market[key] = {"endpoint": m.ALLOWED[key], "retrieved_at_utc": NOW.isoformat(),
                       "transport": "PUBLIC_OKX_GET", "body": {"code": "0", "data": rows}}
    add("books", [{"ts": str(int(NOW.timestamp() * 1000)), "bids": [["99.99", "1000", "0", "1"]], "asks": [["100.00", "1000", "0", "1"]]}])
    last = (int(NOW.timestamp() * 1000) // 3600000 - 1) * 3600000
    add("candles", [[str(last - i * 3600000), "100", "100.2", "99.8", "100", "1", "1", "1", "1"] for i in range(15)])
    add("instruments", [{"instId": "BTC-USDT", "instType": "SPOT", "state": "live", "lotSz": "0.001", "tickSz": "0.01", "minSz": "0.001"}])
    add("ticker", [{"instId": "BTC-USDT", "last": "100", "ts": str(int(NOW.timestamp() * 1000))}])
    return previous, market


def run(previous=None, market=None, **overrides):
    default_prev, default_market = fixture()
    args = dict(runner=15, now=NOW, scheduled_at="2026-09-07T17:56:00+09:30", source_commit="a" * 40,
                previous_path="paper-journal/rounds/synthetic.json", previous_sha="b" * 40)
    args.update(overrides)
    return m.build_round(previous or default_prev, market if market is not None else default_market, **args)


class JournalTests(unittest.TestCase):
    def test_new_entry(self):
        result = run()
        self.assertEqual(result["new_exploration_entries"], 1)
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["continuous_protection"])
        self.assertFalse(result["full_strategy_cycle_completed"])
        self.assertEqual(result["new_core_entries"], 0)

    def test_risk_band_and_reward(self):
        fill = run()["simulated_fills"][0]
        self.assertTrue(D("0.5") <= D(fill["planned_risk_pct"]) <= D("0.51"))
        self.assertGreaterEqual(D(fill["net_reward_risk"]), 2)
        self.assertEqual(fill["protection_state"], "OBSERVATION_RULES_ONLY")
        self.assertTrue(fill["simulated_fill"])
        self.assertFalse(fill["live_order_submitted"])

    def test_unknown_account_records_research(self):
        prev, market = fixture()
        prev["account"].update(verification="NO_CURRENT_CHECKPOINT_VERIFIED", current_cash_usdt=None, positions=None)
        result = run(prev, market)
        self.assertEqual(result["account"], prev["account"])
        self.assertIn("CURRENT_ACCOUNT_CHECKPOINT_NOT_VERIFIED", result["blockers"])
        self.assertEqual(result["scan"]["observed_count"], 1)
        self.assertFalse(result["minimum_new_entry_satisfied"])

    def test_missing_market_still_records(self):
        result = run(market={})
        self.assertFalse(result["minimum_new_entry_satisfied"])
        self.assertIn("NO_USABLE_TICKER", result["scan"]["errors"])

    def test_input_not_mutated(self):
        prev, market = fixture()
        saved = copy.deepcopy((prev, market))
        run(prev, market)
        self.assertEqual((prev, market), saved)

    def test_duplicate_cycle_rejected(self):
        first = run()
        with self.assertRaisesRegex(m.Blocked, "CYCLE_ALREADY_RECORDED"):
            run(first)

    def test_non_latest_duplicate_rejected(self):
        first = run()
        second = run(first, now=NOW + timedelta(hours=1), scheduled_at="2026-09-07T18:56:00+09:30")
        with self.assertRaisesRegex(m.Blocked, "CYCLE_ALREADY_RECORDED"):
            run(second)

    def test_stale_quote(self):
        prev, market = fixture()
        market["books"]["body"]["data"][0]["ts"] = str(int(NOW.timestamp() * 1000) - 6000)
        self.assertIn("STALE_OR_FUTURE_QUOTE", run(prev, market)["blockers"])

    def test_stale_retrieval(self):
        prev, market = fixture()
        market["books"]["retrieved_at_utc"] = (NOW - timedelta(seconds=6)).isoformat()
        self.assertIn("STALE_RETRIEVAL", run(prev, market)["blockers"])

    def test_future_source_quote(self):
        prev, market = fixture()
        market["books"]["body"]["data"][0]["ts"] = str(int(NOW.timestamp() * 1000) + 2000)
        self.assertIn("STALE_OR_FUTURE_QUOTE", run(prev, market)["blockers"])

    def test_empty_depth(self):
        prev, market = fixture()
        market["books"]["body"]["data"][0]["asks"][0][1] = "0"
        self.assertIn("INSUFFICIENT_OBSERVED_ASK_DEPTH", run(prev, market)["blockers"])

    def test_private_endpoint_not_accepted(self):
        prev, market = fixture()
        market["books"]["endpoint"] = "/api/v5/trade/order"
        self.assertIn("MISSING_OR_UNAPPROVED_BOOKS", run(prev, market)["blockers"])

    def test_untrusted_transport(self):
        prev, market = fixture()
        market["books"]["transport"] = "SYNTHETIC"
        self.assertIn("UNVERIFIED_MARKET_TRANSPORT", run(prev, market)["blockers"])

    def test_lot_rounding_rejected(self):
        with self.assertRaisesRegex(m.Blocked, "LOT_ROUNDING"):
            m.preview(D("500"), D("100"), D("1"), D("1"), D("0.01"), D("1"))

    def test_missing_candles(self):
        prev, market = fixture()
        del market["candles"]
        self.assertIn("MISSING_OR_UNAPPROVED_CANDLES", run(prev, market)["blockers"])

    def test_unconfirmed_candle_not_used(self):
        prev, market = fixture()
        market["candles"]["body"]["data"][0][8] = "0"
        self.assertIn("INSUFFICIENT_CONFIRMED_1H_CANDLES", run(prev, market)["blockers"])

    def test_duplicate_candles(self):
        prev, market = fixture()
        rows = market["candles"]["body"]["data"]
        rows.append(rows[0])
        self.assertIn("DUPLICATE_CANDLES", run(prev, market)["blockers"])

    def test_gapped_candles(self):
        prev, market = fixture()
        market["candles"]["body"]["data"][-1][0] = str(int(market["candles"]["body"]["data"][-1][0]) - 3600000)
        self.assertIn("GAPPED_CANDLES", run(prev, market)["blockers"])

    def test_missing_day_does_not_reset(self):
        prev, market = fixture()
        del prev["account"]["day"]
        result = run(prev, market)
        self.assertIn("DAY_START_NAV_NOT_RECONCILED", result["blockers"])
        self.assertEqual(result["account"]["day"], {})

    def test_daily_loss(self):
        prev, market = fixture()
        prev["account"]["current_cash_usdt"] = "474"
        prev["account"]["realized_net_pnl_usdt"]["EXPLORATION"] = "-26"
        self.assertIn("DAILY_LOSS_LIMIT", run(prev, market)["blockers"])

    def test_accounting_mismatch(self):
        prev, market = fixture()
        prev["account"]["current_cash_usdt"] = "1000"
        self.assertIn("CHECKPOINT_ACCOUNTING_MISMATCH", run(prev, market)["blockers"])

    def test_wrong_epoch(self):
        prev, market = fixture()
        prev["account"]["epoch"] = "cairn-100000"
        self.assertIn("WRONG_ACCOUNT_EPOCH", run(prev, market)["blockers"])

    def test_manual_identity_not_scheduled(self):
        result = run(scheduled_at=None)
        self.assertEqual(result["record_type"], "MANUAL_ROUND")
        self.assertIn("MANUAL", result["cycle_id"])
        self.assertIsNone(result["scheduled_at"])

    def test_wrong_slot(self):
        with self.assertRaisesRegex(m.Blocked, "WRONG_ORIGINAL_SCHEDULE_SLOT"):
            run(scheduled_at="2026-09-07T17:52:00+09:30")

    def test_future_slot(self):
        with self.assertRaisesRegex(m.Blocked, "FUTURE_SCHEDULE_SLOT"):
            run(scheduled_at="2026-09-07T18:56:00+09:30")

    def test_timezone_required(self):
        with self.assertRaisesRegex(m.Blocked, "TIMEZONE_REQUIRED"):
            run(scheduled_at="2026-09-07T17:56:00")

    def test_dst_identity_includes_utc(self):
        base = dict(scheduled_at=None)
        a = run(now=datetime(2026, 4, 4, 16, 0, tzinfo=timezone.utc), **base)
        b = run(now=datetime(2026, 4, 4, 17, 0, tzinfo=timezone.utc), **base)
        self.assertNotEqual(a["cycle_key"], b["cycle_key"])

    def test_partial_exit_shared_depth(self):
        first = run()
        prev, market = fixture()
        prev["account"] = first["account"]
        market["books"]["body"]["data"][0]["bids"][0] = ["98", "0.5"]
        result = run(prev, market)
        self.assertEqual(result["exits"], 1)
        self.assertEqual(result["simulated_fills"][0]["quantity"], "0.5")
        self.assertIn("EXISTING_EXIT_PENDING", result["blockers"])
        lot = result["account"]["positions"][0]
        self.assertEqual(lot["latched_exit"], "STOP_LOSS")
        self.assertEqual(lot["original_risk_usdt"], first["account"]["positions"][0]["original_risk_usdt"])

    def test_exit_not_counted_as_new_entry(self):
        first = run()
        prev, market = fixture()
        prev["account"] = first["account"]
        market["books"]["body"]["data"][0]["bids"][0][0] = "98"
        del market["candles"]
        result = run(prev, market)
        self.assertEqual(result["exits"], 1)
        self.assertFalse(result["minimum_new_entry_satisfied"])
        self.assertEqual(result["account"]["positions"], [])

    def test_latched_target_not_changed_to_stop(self):
        first = run()
        prev, market = fixture()
        prev["account"] = first["account"]
        prev["account"]["positions"][0]["latched_exit"] = "TAKE_PROFIT"
        market["books"]["body"]["data"][0]["bids"][0][0] = "98"
        result = run(prev, market)
        self.assertEqual(result["simulated_fills"][0]["reason"], "TAKE_PROFIT")
        self.assertEqual(result["simulated_fills"][0]["price"], "97.9510")

    def test_exit_allowed_at_daily_loss_limit(self):
        first = run()
        prev, market = fixture()
        prev["account"] = first["account"]
        market["books"]["body"]["data"][0]["bids"][0][0] = "70"
        result = run(prev, market)
        self.assertEqual(result["exits"], 1)
        self.assertIn("DAILY_LOSS_LIMIT", result["blockers"])

    def test_fees_and_balance_identity(self):
        result = run()
        state = result["account"]
        with localcontext() as ctx:
            ctx.prec = 80
            total = D(state["current_cash_usdt"]) + sum(D(p["cost_basis_usdt"]) for p in state["positions"])
            self.assertEqual(total, D("500"))
            self.assertGreater(D(state["fees_usdt"]), 0)
            self.assertEqual(D(state["current_nav_usdt"]) - 500, D(state["total_net_pnl_usdt"]))

    def test_nonfinite_number_rejected(self):
        for value in ("NaN", "Infinity", "1e100", 2.0):
            with self.assertRaises(m.Blocked):
                m.number(value)

    def test_no_fabricated_full_scan(self):
        self.assertFalse(run()["scan"]["full_scan_completed"])
        self.assertEqual(run()["scan"]["scope"], "BTC-USDT_ONLY")

    def test_git_blob_identity(self):
        self.assertEqual(m.git_blob(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")


class MarginTests(unittest.TestCase):
    def margin_checkpoint(self, bid="99.99", depth="1000"):
        prev, market = fixture()
        prev["account"].update(current_cash_usdt="0", borrowed_usdt="500", financing_cost_usdt="0",
                               financing_observed_at_utc=NOW.isoformat(), positions=[{
            "trade_id": "synthetic-margin", "instrument": "BTC-USDT", "origin": "EXPLORATION",
            "quantity": "10", "entry": "100", "cost_basis_usdt": "1000", "original_risk_usdt": "5",
            "stop": "90", "take_profit": "120", "lot_size": "0.001", "latched_exit": None}])
        market["books"]["body"]["data"][0]["bids"][0] = [bid, depth]
        del market["instruments"]
        return prev, market

    def test_third_entry_borrows_without_creating_equity(self):
        prev, market = fixture()
        for n in range(3):
            prev = run(prev, market, now=NOW + timedelta(seconds=n), scheduled_at=None)
        self.assertEqual(prev["new_exploration_entries"], 1)
        a = prev["account"]
        self.assertGreater(D(a["borrowed_usdt"]), 0)
        self.assertEqual(D(a["current_cash_usdt"]), 0)
        self.assertEqual(a["max_gross_leverage"], "100")
        with localcontext() as ctx:
            ctx.prec = 80
            self.assertEqual(D(a["current_nav_usdt"]), D(a["gross_exposure_usdt"]) - D(a["borrowed_usdt"]))
            self.assertEqual(sum(D(p["cost_basis_usdt"]) for p in a["positions"]) - D(a["borrowed_usdt"]), D("500"))

    def test_financing_accrues_and_next_round_reconciles(self):
        prev, market = self.margin_checkpoint()
        prev["account"]["financing_observed_at_utc"] = (NOW - timedelta(days=1)).isoformat()
        result = run(prev, market)
        a = result["account"]
        self.assertGreater(D(a["financing_cost_usdt"]), 0)
        with localcontext() as ctx:
            ctx.prec = 80
            self.assertEqual(D(a["borrowed_usdt"]), D("500") + D(a["financing_cost_usdt"]))
            self.assertEqual(D(a["realized_net_pnl_usdt"]["EXPLORATION"]), -D(a["financing_cost_usdt"]))
        again = run(result, market, now=NOW + timedelta(seconds=1), scheduled_at=None)
        self.assertNotIn("CHECKPOINT_ACCOUNTING_MISMATCH", again["blockers"])
        self.assertGreater(D(again["account"]["financing_cost_usdt"]), D(a["financing_cost_usdt"]))

    def test_missing_debt_timestamp_blocks_without_mutation(self):
        prev, market = self.margin_checkpoint()
        del prev["account"]["financing_observed_at_utc"]
        result = run(prev, market)
        self.assertIn("MISSING_FINANCING_TIMESTAMP", result["blockers"])
        self.assertEqual(result["account"], prev["account"])

    def test_stop_exit_repays_debt(self):
        prev, market = self.margin_checkpoint(bid="89")
        result = run(prev, market)
        self.assertEqual(result["exits"], 1)
        self.assertEqual(D(result["account"]["borrowed_usdt"]), 0)
        self.assertEqual(D(result["account"]["debt_repaid_this_round_usdt"]), 500)
        self.assertGreater(D(result["account"]["current_cash_usdt"]), 0)

    def test_gap_liquidation_preserves_negative_equity(self):
        prev, market = self.margin_checkpoint(bid="49")
        result = run(prev, market)
        self.assertEqual(result["simulated_fills"][0]["reason"], "MARGIN_LIQUIDATION")
        self.assertIn("MARGIN_LIQUIDATION_OBSERVED", result["blockers"])
        self.assertEqual(result["account"]["positions"], [])
        self.assertLess(D(result["account"]["current_nav_usdt"]), 0)
        self.assertGreater(D(result["account"]["borrowed_usdt"]), 0)

    def test_partial_liquidation_latches_remainder(self):
        prev, market = self.margin_checkpoint(bid="49", depth="1")
        result = run(prev, market)
        lot = result["account"]["positions"][0]
        self.assertEqual(lot["quantity"], "9")
        self.assertEqual(lot["latched_exit"], "MARGIN_LIQUIDATION")
        self.assertFalse(result["minimum_new_entry_satisfied"])

    def test_post_fee_leverage_cap(self):
        from unittest.mock import patch
        prev, market = fixture()
        with patch.object(m, "MAX_LEVERAGE", D("1")):
            for n in range(3):
                prev = run(prev, market, now=NOW + timedelta(seconds=n), scheduled_at=None)
        self.assertIn("BLOCKED_CAPITAL_OR_RISK_CAPACITY", prev["blockers"])
        self.assertEqual(D(prev["account"]["borrowed_usdt"]), 0)

    def test_time_exit_uses_current_bid(self):
        first = run()
        first["account"]["positions"][0]["exit_due_at_utc"] = NOW.isoformat()
        _, market = fixture()
        del market["instruments"]
        result = run(first, market, scheduled_at=None)
        self.assertEqual(result["simulated_fills"][0]["reason"], "TIME_EXIT")
        self.assertEqual(D(result["simulated_fills"][0]["price"]), D("99.99") * D("0.9995"))

    def test_financing_reserve_in_planned_risk(self):
        fill = run()["simulated_fills"][0]
        self.assertGreater(D(fill["financing_reserve_24h_usdt"]), 0)
        with localcontext() as ctx:
            ctx.prec = 80
            risk = D(fill["quantity"]) * (D(fill["entry"]) * D("1.001") - D(fill["stop"]) * D("0.9995") * D("0.999")) + D(fill["financing_reserve_24h_usdt"])
            self.assertEqual(risk, D(fill["original_risk_usdt"]))


if __name__ == "__main__":
    unittest.main()
