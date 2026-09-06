from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

from cairn.models import PaperAction
from cairn.paper import PaperState, Position, apply_action, create_account, mark_to_market
from cairn.storage import Store

ADELAIDE = ZoneInfo("Australia/Adelaide")
OKX = "https://www.okx.com"
FEE_RATE = Fraction(1, 10_000)  # 1 bp paper execution fee assumption, reported explicitly
INITIAL_CASH = "100000"
EXPLORATION_POSITION_MAX = Fraction(25, 10_000)  # 0.25% NAV
EXPLORATION_TOTAL_MAX = Fraction(50, 10_000)  # 0.50% NAV


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_json(path: str, params: dict[str, str]) -> dict:
    url = OKX + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Cairn-paper-cycle/1"})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise RuntimeError("OKX response too large")
    payload = json.loads(raw)
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"OKX error: {payload.get('code')}")
    return payload


def frac(v: str) -> Fraction:
    return Fraction(v)


def dec(v: Fraction, places: int = 12) -> str:
    return f"{float(v):.{places}f}".rstrip("0").rstrip(".") or "0"


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def load_state(path: Path) -> PaperState:
    if not path.exists():
        return create_account(INITIAL_CASH)
    p = json.loads(path.read_text(encoding="utf-8"))
    return PaperState(
        sequence=int(p["sequence"]),
        cash=frac(p["cash"]),
        positions={k: Position(frac(v["quantity"]), frac(v["cost_basis"])) for k, v in p["positions"].items()},
        fees_paid=frac(p.get("fees_paid", "0")),
        distributions=frac(p.get("distributions", "0")),
    )


def state_json(state: PaperState) -> dict:
    return {
        "sequence": state.sequence,
        "cash": dec(state.cash),
        "positions": {k: {"quantity": dec(v.quantity), "cost_basis": dec(v.cost_basis)} for k, v in state.positions.items()},
        "fees_paid": dec(state.fees_paid),
        "distributions": dec(state.distributions),
    }


def main() -> int:
    run_at = now_utc()
    slot = run_at.astimezone(ADELAIDE)
    runner = os.environ.get("CAIRN_RUNNER_ID", "CAIRN-07")
    cycle_id = os.environ.get("CAIRN_CYCLE_ID") or slot.strftime(f"%Y-%m-%dT%H-%M-{runner}")
    out = Path("artifacts") / cycle_id
    out.mkdir(parents=True, exist_ok=True)
    db = Store(out / "cairn.sqlite3")
    db.initialize()
    actor = runner

    report: dict = {
        "cycle_id": cycle_id,
        "runner": runner,
        "started_at": run_at.isoformat(),
        "mode": "LOCAL_PAPER_LEDGER",
        "venue_data": "OKX_PUBLIC",
        "live_order_transport": False,
        "capital_permissions": "NONE",
        "status": "RUNNING",
        "minimum_paper_trade_per_cycle": 1,
        "core": {},
        "exploration": {},
        "incidents": [],
    }

    try:
        # 1-2 health + validated market data
        instrument = get_json("/api/v5/public/instruments", {"instType": "SPOT", "instId": "BTC-USDT"})["data"][0]
        ticker = get_json("/api/v5/market/ticker", {"instId": "BTC-USDT"})["data"][0]
        book = get_json("/api/v5/market/books", {"instId": "BTC-USDT", "sz": "5"})["data"][0]
        candles = get_json("/api/v5/market/history-candles", {"instId": "BTC-USDT", "bar": "1H", "limit": "72"})["data"]
        now_ms = int(time.time() * 1000)
        ticker_age = now_ms - int(ticker["ts"])
        book_age = now_ms - int(book["ts"])
        if ticker_age < -5000 or book_age < -5000 or ticker_age > 120_000 or book_age > 120_000:
            raise RuntimeError(f"STALE_OKX_MARKET_DATA ticker_age_ms={ticker_age} book_age_ms={book_age}")
        if instrument.get("state") != "live":
            raise RuntimeError("BTC-USDT instrument not live")
        report["health"] = {"okx_public": "OK", "paper_mode_verified": True, "shared_state_restored": Path("state/account.json").exists()}
        report["market_data"] = {"ticker": ticker, "book": book, "instrument": instrument, "ticker_age_ms": ticker_age, "book_age_ms": book_age}
        db.put_record(record_id=f"{cycle_id}:market", record_type="market_snapshot", created_at=run_at.isoformat(), payload=report["market_data"], actor=actor, asset_id="BTC", mode="PROSPECTIVE")

        # 3 deterministic features
        confirmed = [r for r in candles if len(r) >= 9 and r[8] == "1"]
        confirmed.sort(key=lambda r: int(r[0]))
        closes = [float(r[4]) for r in confirmed]
        if len(closes) < 25:
            raise RuntimeError("INSUFFICIENT_CONFIRMED_1H_CANDLES")
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        rv24 = math.sqrt(sum(x * x for x in returns[-24:]))
        last = frac(ticker["last"])
        open24 = frac(ticker["open24h"])
        bid = frac(ticker["bidPx"])
        ask = frac(ticker["askPx"])
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10_000
        bid_depth = sum(frac(x[1]) for x in book["bids"])
        ask_depth = sum(frac(x[1]) for x in book["asks"])
        imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth) if bid_depth + ask_depth else Fraction(0)
        features = {
            "momentum_24h": dec(last / open24 - 1),
            "realized_vol_24h_log": f"{rv24:.12g}",
            "spread_bps": dec(spread_bps),
            "top5_depth_imbalance": dec(imbalance),
        }
        report["features"] = features
        db.put_record(record_id=f"{cycle_id}:features", record_type="features", created_at=run_at.isoformat(), payload=features, actor=actor, asset_id="BTC", mode="PROSPECTIVE")

        # 4 active alpha status: publication build has no executable production alpha model.
        report["core"] = {"signal_status": "NO_EXECUTABLE_ACTIVE_ALPHA_MODEL", "orders": 0, "fills": 0}

        # 5-6 portfolio + independent risk gate using shared paper state
        state_path = Path("state/account.json")
        state = load_state(state_path)
        marks = {"BTC-USDT": ticker["last"]}
        pre_nav = mark_to_market(state, marks)
        btc_pos = state.positions.get("BTC-USDT", Position())
        exploration_notional_existing = btc_pos.quantity * last
        exploration_exposure = exploration_notional_existing / pre_nav
        if exploration_exposure > EXPLORATION_TOTAL_MAX:
            raise RuntimeError("EXPLORATION_EXPOSURE_ALREADY_ABOVE_LIMIT")

        # 7 controlled exploration paper fill when no core fill exists.
        # Target 0.10% NAV, never above 0.25%, and keep total <=0.50%.
        target_notional = min(pre_nav * Fraction(10, 10_000), pre_nav * EXPLORATION_POSITION_MAX)
        remaining_capacity = pre_nav * EXPLORATION_TOTAL_MAX - exploration_notional_existing
        notional = min(target_notional, remaining_capacity)
        min_sz = frac(instrument.get("minSz") or "0")
        lot_sz = frac(instrument.get("lotSz") or "0.00000001")
        raw_qty = notional / ask
        lots = raw_qty // lot_sz
        qty = lots * lot_sz
        if qty <= 0 or qty < min_sz:
            raise RuntimeError("EXPLORATION_SIZE_BELOW_OKX_MINIMUM")
        visible_ask = frac(book["asks"][0][1])
        if qty > visible_ask:
            raise RuntimeError("EXPLORATION_SIZE_EXCEEDS_VISIBLE_TOP_BOOK")
        fee = qty * ask * FEE_RATE
        action_id = hashlib.sha256(f"{cycle_id}|exploration|BTC-USDT|BUY".encode()).hexdigest()[:32]
        action = PaperAction(
            action_id=action_id,
            account_id="cairn-shared-paper",
            idempotency_key=action_id,
            expected_sequence=state.sequence,
            ts=run_at,
            inst_id="BTC-USDT",
            side="BUY",
            quantity=dec(qty),
            price=dec(ask),
            fee=dec(fee),
            rationale="exploration:execution_pipeline_validation",
        )
        existing = db.get_record(f"{cycle_id}:fill")
        if existing is not None:
            raise RuntimeError("DUPLICATE_CYCLE_FILL_RECORD")
        new_state, receipt = apply_action(state, action)
        fill = {
            "cycle_id": cycle_id,
            "action_id": action_id,
            "client_order_id": action_id,
            "instrument": "BTC-USDT",
            "side": "BUY",
            "fill_quantity": dec(qty),
            "fill_price": dec(ask),
            "notional": dec(qty * ask),
            "fee": dec(fee),
            "trade_origin": "exploration",
            "exploration_reason": "execution_pipeline_validation",
            "execution_mode": "LOCAL_PAPER_LEDGER",
            "market_reference": "OKX_PUBLIC_TOP_ASK",
            "simulated_fill": True,
            "live_order_submitted": False,
            "receipt": asdict(receipt),
        }
        db.put_record(record_id=f"{cycle_id}:order", record_type="paper_order", created_at=run_at.isoformat(), payload=action, actor=actor, asset_id="BTC", mode="PROSPECTIVE")
        db.put_record(record_id=f"{cycle_id}:fill", record_type="paper_fill", created_at=run_at.isoformat(), payload=fill, actor=actor, asset_id="BTC", mode="PROSPECTIVE")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        save_json(state_path, state_json(new_state))
        report["exploration"] = {"orders": 1, "fills": 1, "fill": fill}

        # 8 execution quality
        execution = {
            "requested_price": dec(ask),
            "fill_price": dec(ask),
            "slippage_bps_vs_requested": "0",
            "spread_bps": dec(spread_bps),
            "maker_taker": "SIMULATED_TAKER_AT_TOP_ASK",
            "visible_top_ask_qty": dec(visible_ask),
            "fill_qty_to_visible_ask_ratio": dec(qty / visible_ask),
        }
        report["execution_quality"] = execution
        db.put_record(record_id=f"{cycle_id}:execution", record_type="execution_quality", created_at=run_at.isoformat(), payload=execution, actor=actor, asset_id="BTC", mode="PROSPECTIVE")

        # 9 reconciliation is internal paper ledger vs action/receipt; no broker account exists by design.
        post_nav = mark_to_market(new_state, marks)
        expected_cash = state.cash - qty * ask - fee
        reconciled = new_state.cash == expected_cash and new_state.sequence == state.sequence + 1
        if not reconciled:
            raise RuntimeError("PAPER_LEDGER_RECONCILIATION_MISMATCH")
        reconciliation = {"internal_ledger": "MATCH", "broker_demo_position": "NOT_APPLICABLE_LOCAL_PAPER", "pre_sequence": state.sequence, "post_sequence": new_state.sequence}
        report["reconciliation"] = reconciliation
        db.put_record(record_id=f"{cycle_id}:reconciliation", record_type="reconciliation", created_at=run_at.isoformat(), payload=reconciliation, actor=actor, mode="PROSPECTIVE")

        # 10-11 accounting / attribution
        accounting = {
            "pre_nav": dec(pre_nav),
            "post_nav_marked_at_trade_price": dec(post_nav),
            "core_pnl": "0",
            "exploration_pnl": dec(post_nav - pre_nav),
            "total_pnl": dec(post_nav - pre_nav),
            "fees": dec(fee),
            "funding": "0",
            "note": "Immediate post-fill NAV at the same last mark reflects fee/spread mechanics only; no core alpha attribution is claimed.",
        }
        report["accounting"] = accounting
        report["performance"] = {"core_statistics": "NO_CORE_TRADES_THIS_CYCLE", "exploration_fill_count": 1, "total_fill_count": 1}
        db.put_record(record_id=f"{cycle_id}:accounting", record_type="accounting", created_at=run_at.isoformat(), payload=accounting, actor=actor, mode="PROSPECTIVE")

        # 12-14 monitoring/research/validation
        report["anomalies"] = []
        report["hypotheses"] = [{"id": f"{cycle_id}:H1", "hypothesis": "Compare paper taker-at-ask execution cost with maker/no-fill policy under the same public-book snapshots.", "production_change": False}]
        report["validation"] = {"status": "NOT_PROMOTED", "reason": "single execution observation; no strategy modification authorized"}

        # 15 report persistence
        report["audit_chain_valid"] = db.verify_audit_chain()
        report["status"] = "COMPLETED"
        report["minimum_paper_trade_per_cycle_satisfied"] = True
        report["completed_at"] = now_utc().isoformat()
    except Exception as exc:
        report["status"] = "HALTED"
        report["minimum_paper_trade_per_cycle_satisfied"] = False
        report["incidents"].append({"type": type(exc).__name__, "message": str(exc)})
        report["completed_at"] = now_utc().isoformat()

    save_json(out / "cycle-report.json", report)
    summary = [
        f"# Cairn cycle {cycle_id}",
        "",
        f"Status: **{report['status']}**",
        f"Mode: **{report['mode']}** (live order transport disabled)",
        f"Minimum paper trade satisfied: **{report.get('minimum_paper_trade_per_cycle_satisfied', False)}**",
    ]
    if report.get("exploration", {}).get("fill"):
        f = report["exploration"]["fill"]
        summary += ["", "## Paper fill", f"- {f['side']} {f['fill_quantity']} {f['instrument']} @ {f['fill_price']}", f"- notional {f['notional']} USDT; fee {f['fee']} USDT", f"- origin: {f['trade_origin']} / {f['exploration_reason']}", "- execution: simulated paper fill against a fresh OKX public top-of-book reference; no live order was submitted"]
    if report["incidents"]:
        summary += ["", "## Incidents"] + [f"- {x['message']}" for x in report["incidents"]]
    (out / "cycle-report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
