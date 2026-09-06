from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from cairn.models import PaperAction
from cairn.paper import Position, apply_action, mark_to_market
from cairn.storage import Store
import run_full_paper_cycle_v2 as r

CYCLE_ID = "2026-09-06T18-52-CAIRN-14"
RUNNER_ID = "CAIRN-14"
STATE_PATH = Path("state/account.json")
TARGET_REDUCTION_WEIGHT = Fraction(45, 10000)  # 0.45% NAV after reduction
BUY_WEIGHT = Fraction(10, 10000)  # 0.10% NAV when safely below cap


def ceil_to_lot(value: Fraction, lot: Fraction) -> Fraction:
    ratio = value / lot
    units = (ratio.numerator + ratio.denominator - 1) // ratio.denominator
    return units * lot


def load_state_and_actions():
    state = r.state_load(STATE_PATH)
    raw = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    actions = raw.get("executed_actions", {})
    if not isinstance(actions, dict):
        raise RuntimeError("CORRUPT_EXECUTED_ACTIONS")
    return state, actions


def persist_state(state, actions):
    r.dump(
        STATE_PATH,
        {
            "sequence": state.sequence,
            "cash": r.D(state.cash),
            "positions": {
                k: {"quantity": r.D(v.quantity), "cost_basis": r.D(v.cost_basis)}
                for k, v in state.positions.items()
            },
            "fees_paid": r.D(state.fees_paid),
            "distributions": r.D(state.distributions),
            "executed_actions": actions,
        },
    )


def main() -> int:
    started = datetime.now(timezone.utc)
    cycle = os.getenv("CAIRN_CYCLE_ID", CYCLE_ID)
    runner = os.getenv("CAIRN_RUNNER_ID", RUNNER_ID)
    if cycle != CYCLE_ID or runner != RUNNER_ID:
        raise RuntimeError("CYCLE_IDENTITY_MISMATCH")

    out = Path("artifacts") / cycle
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / "cairn.sqlite3")
    store.initialize()
    report = {
        "cycle_id": cycle,
        "runner": runner,
        "started_at": started.isoformat(),
        "mode": "LOCAL_PAPER_LEDGER",
        "venue_data": "OKX_PUBLIC",
        "live_order_transport": False,
        "capital_permissions": "NONE",
        "status": "RUNNING",
        "core": {},
        "exploration": {},
        "incidents": [],
        "minimum_paper_trade_per_cycle": 1,
    }

    try:
        inst = r.get("/api/v5/public/instruments", {"instType": "SPOT", "instId": "BTC-USDT"})[0]
        tick = r.get("/api/v5/market/ticker", {"instId": "BTC-USDT"})[0]
        book = r.get("/api/v5/market/books", {"instId": "BTC-USDT", "sz": "5"})[0]
        candles = r.get("/api/v5/market/history-candles", {"instId": "BTC-USDT", "bar": "1H", "limit": "72"})

        now_ms = int(time.time() * 1000)
        ticker_age = now_ms - int(tick["ts"])
        book_age = now_ms - int(book["ts"])
        if ticker_age < -5000 or book_age < -5000 or ticker_age > 120000 or book_age > 120000:
            raise RuntimeError(f"STALE_OKX_DATA ticker_age_ms={ticker_age} book_age_ms={book_age}")
        if inst.get("state") != "live":
            raise RuntimeError("INSTRUMENT_NOT_LIVE")
        if not STATE_PATH.exists():
            raise RuntimeError("SHARED_STATE_NOT_RESTORED")

        report["health"] = {
            "paper_mode_verified": True,
            "verification": "local deterministic paper ledger; no private/order transport exists",
            "okx_public": "OK",
            "shared_state_restored": True,
        }
        market = {
            "instrument": inst,
            "ticker": tick,
            "book": book,
            "ticker_age_ms": ticker_age,
            "book_age_ms": book_age,
        }
        report["market_data"] = market
        store.put_record(
            record_id=f"{cycle}:market",
            record_type="market_snapshot",
            created_at=started.isoformat(),
            payload=market,
            actor=runner,
            asset_id="BTC",
            mode="PROSPECTIVE",
        )

        rows = [x for x in candles if len(x) >= 9 and x[8] == "1"]
        rows.sort(key=lambda x: int(x[0]))
        closes = [float(x[4]) for x in rows]
        if len(closes) < 25:
            raise RuntimeError("INSUFFICIENT_CONFIRMED_CANDLES")
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        last, open24, bid, ask = map(r.F, (tick["last"], tick["open24h"], tick["bidPx"], tick["askPx"]))
        mid = (bid + ask) / 2
        bids = sum((r.F(x[1]) for x in book["bids"]), Fraction())
        asks = sum((r.F(x[1]) for x in book["asks"]), Fraction())
        features = {
            "momentum_24h": r.D(last / open24 - 1),
            "realized_vol_24h_log": f"{math.sqrt(sum(x * x for x in returns[-24:])):.12g}",
            "spread_bps": r.D((ask - bid) / mid * 10000),
            "top5_depth_imbalance": r.D((bids - asks) / (bids + asks) if bids + asks else 0),
        }
        report["features"] = features
        store.put_record(
            record_id=f"{cycle}:features",
            record_type="features",
            created_at=started.isoformat(),
            payload=features,
            actor=runner,
            asset_id="BTC",
            mode="PROSPECTIVE",
        )

        report["core"] = {
            "signal_status": "NO_EXECUTABLE_ACTIVE_ALPHA_MODEL_IN_PUBLICATION_BUILD",
            "orders": 0,
            "fills": 0,
        }

        state, executed_actions = load_state_and_actions()
        pre_nav = mark_to_market(state, {"BTC-USDT": tick["last"]})
        if pre_nav <= 0:
            raise RuntimeError("INVALID_NAV")
        pos = state.positions.get("BTC-USDT", Position())
        existing_notional = pos.quantity * last
        existing_weight = existing_notional / pre_nav
        lot = r.F(inst.get("lotSz") or "0.00000001")
        min_size = r.F(inst.get("minSz") or "0")

        if existing_weight >= r.TOTAL_MAX:
            side = "SELL"
            price = bid
            target_notional = pre_nav * TARGET_REDUCTION_WEIGHT
            required_reduction = existing_notional - target_notional
            raw_qty = required_reduction / price
            qty = ceil_to_lot(raw_qty, lot)
            max_reduction_qty = (pre_nav * r.POSITION_MAX / price // lot) * lot
            qty = min(qty, max_reduction_qty, pos.quantity)
            visible = r.F(book["bids"][0][1])
            reason = "exploration_exposure_reduction_near_shared_cap"
            market_reference = "FRESH_OKX_PUBLIC_TOP_BID"
            classification = "SIMULATED_TAKER_AT_TOP_BID"
        else:
            side = "BUY"
            price = ask
            capacity = pre_nav * r.TOTAL_MAX - existing_notional
            notional = min(pre_nav * BUY_WEIGHT, pre_nav * r.POSITION_MAX, capacity)
            qty = (notional / price // lot) * lot
            visible = r.F(book["asks"][0][1])
            reason = "execution_pipeline_validation"
            market_reference = "FRESH_OKX_PUBLIC_TOP_ASK"
            classification = "SIMULATED_TAKER_AT_TOP_ASK"

        if qty <= 0 or qty < min_size:
            raise RuntimeError("EXPLORATION_SIZE_BELOW_MINIMUM")
        if qty > visible:
            raise RuntimeError("EXPLORATION_SIZE_EXCEEDS_VISIBLE_TOP_BOOK")
        order_notional = qty * price
        if order_notional / pre_nav > r.POSITION_MAX:
            raise RuntimeError("EXPLORATION_ORDER_ABOVE_POSITION_LIMIT")

        action_id = hashlib.sha256(f"{cycle}|exploration|BTC-USDT|{side}".encode()).hexdigest()[:32]
        prior = executed_actions.get(action_id)
        if prior is not None:
            fill = prior["fill"]
            report["exploration"] = {"orders": 1, "fills": 1, "fill": fill, "idempotent_replay": True}
            report["reconciliation"] = prior["reconciliation"]
            report["accounting"] = prior["accounting"]
            report["execution_quality"] = prior["execution_quality"]
            report["performance"] = {"core_statistics": "EXCLUDED_NO_CORE_TRADES", "exploration_fill_count": 1, "total_fill_count": 1}
            report["anomalies"] = []
            report["hypotheses"] = [{"id": f"{cycle}:H1", "hypothesis": "Compare cap-reduction execution cost with alternative slower de-risking policies.", "production_change": False}]
            report["validation"] = {"status": "NOT_PROMOTED", "reason": "execution observation only"}
            report["audit_chain_valid"] = store.verify_audit_chain()
            report["status"] = "COMPLETED"
            report["minimum_paper_trade_per_cycle_satisfied"] = True
        else:
            fee = order_notional * r.FEE_RATE
            action = PaperAction(
                action_id=action_id,
                account_id="cairn-shared-paper",
                idempotency_key=action_id,
                expected_sequence=state.sequence,
                ts=started,
                inst_id="BTC-USDT",
                side=side,
                quantity=r.D(qty),
                price=r.D(price),
                fee=r.D(fee),
                rationale=f"exploration:{reason}",
            )
            new_state, receipt = apply_action(state, action)
            post_position = new_state.positions.get("BTC-USDT", Position())
            post_exposure = post_position.quantity * last
            post_weight = post_exposure / pre_nav
            if post_weight > r.TOTAL_MAX:
                raise RuntimeError("EXPLORATION_EXPOSURE_REMAINS_ABOVE_LIMIT")

            fill = {
                "cycle_id": cycle,
                "action_id": action_id,
                "client_order_id": action_id,
                "instrument": "BTC-USDT",
                "side": side,
                "fill_quantity": r.D(qty),
                "fill_price": r.D(price),
                "notional": r.D(order_notional),
                "fee": r.D(fee),
                "trade_origin": "exploration",
                "exploration_reason": reason,
                "experiment_id": f"{cycle}:EXP-CAP-REDUCTION" if side == "SELL" else f"{cycle}:EXP-PIPELINE",
                "execution_mode": "LOCAL_PAPER_LEDGER",
                "market_reference": market_reference,
                "simulated_fill": True,
                "live_order_submitted": False,
                "receipt": asdict(receipt),
            }
            store.put_record(
                record_id=f"{cycle}:order",
                record_type="paper_order",
                created_at=started.isoformat(),
                payload=action,
                actor=runner,
                asset_id="BTC",
                mode="PROSPECTIVE",
            )
            store.put_record(
                record_id=f"{cycle}:fill",
                record_type="paper_fill",
                created_at=started.isoformat(),
                payload=fill,
                actor=runner,
                asset_id="BTC",
                mode="PROSPECTIVE",
            )

            post_nav = mark_to_market(new_state, {"BTC-USDT": tick["last"]})
            if side == "BUY":
                expected_cash = state.cash - order_notional - fee
            else:
                expected_cash = state.cash + order_notional - fee
            if new_state.cash != expected_cash or new_state.sequence != state.sequence + 1:
                raise RuntimeError("RECONCILIATION_MISMATCH")

            reconciliation = {
                "internal_ledger": "MATCH",
                "broker_demo_position": "NOT_APPLICABLE_LOCAL_PAPER",
                "pre_sequence": state.sequence,
                "post_sequence": new_state.sequence,
                "pre_exploration_weight": r.D(existing_weight),
                "post_exploration_weight": r.D(post_weight),
            }
            accounting = {
                "pre_nav": r.D(pre_nav),
                "post_nav_marked_at_last": r.D(post_nav),
                "core_pnl": "0",
                "exploration_pnl": r.D(post_nav - pre_nav),
                "total_pnl": r.D(post_nav - pre_nav),
                "fees": r.D(fee),
                "funding": "0",
            }
            execution_quality = {
                "requested_price": r.D(price),
                "fill_price": r.D(price),
                "slippage_bps_vs_requested": "0",
                "spread_bps": features["spread_bps"],
                "classification": classification,
                "visible_top_book_qty": r.D(visible),
            }
            executed_actions[action_id] = {
                "fill": fill,
                "reconciliation": reconciliation,
                "accounting": accounting,
                "execution_quality": execution_quality,
            }
            persist_state(new_state, executed_actions)

            report["exploration"] = {"orders": 1, "fills": 1, "fill": fill, "idempotent_replay": False}
            report["execution_quality"] = execution_quality
            report["reconciliation"] = reconciliation
            report["accounting"] = accounting
            report["performance"] = {"core_statistics": "EXCLUDED_NO_CORE_TRADES", "exploration_fill_count": 1, "total_fill_count": 1}
            report["anomalies"] = []
            report["hypotheses"] = [{"id": f"{cycle}:H1", "hypothesis": "Compare cap-reduction execution cost with alternative slower de-risking policies.", "production_change": False}]
            report["validation"] = {"status": "NOT_PROMOTED", "reason": "execution observation only"}
            report["audit_chain_valid"] = store.verify_audit_chain()
            report["status"] = "COMPLETED"
            report["minimum_paper_trade_per_cycle_satisfied"] = True

    except Exception as exc:
        report["status"] = "HALTED"
        report["minimum_paper_trade_per_cycle_satisfied"] = False
        report["incidents"].append({"type": type(exc).__name__, "message": str(exc)})

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    r.dump(out / "cycle-report.json", report)
    lines = [
        f"# Cairn cycle {cycle}",
        "",
        f"Status: **{report['status']}**",
        f"Paper minimum satisfied: **{report.get('minimum_paper_trade_per_cycle_satisfied', False)}**",
        f"Mode: **{report['mode']}**; live order transport disabled.",
    ]
    if report.get("exploration", {}).get("fill"):
        fill = report["exploration"]["fill"]
        lines += [
            "",
            "## Recorded paper trade",
            f"- {fill['side']} {fill['fill_quantity']} {fill['instrument']} @ {fill['fill_price']}",
            f"- notional {fill['notional']} USDT; fee {fill['fee']} USDT",
            f"- origin: {fill['trade_origin']} / {fill['exploration_reason']}",
            f"- experiment: {fill['experiment_id']}",
            "- explicitly simulated local-paper fill referenced to fresh OKX public top-of-book; no live order submitted",
        ]
    if report["incidents"]:
        lines += ["", "## Incidents"] + [f"- {x['type']}: {x['message']}" for x in report["incidents"]]
    (out / "cycle-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
