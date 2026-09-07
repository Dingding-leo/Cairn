#!/usr/bin/env python3
"""Stateless chat-paper round. GitHub publication is a separate compare-and-swap.

No host service, exchange account, scheduler, keys, paid API or live transport.
Consumes a pinned previous round and recorded public OKX responses. Unknown
account state blocks fills, NOT research/review/recording. Never initializes cash.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

MODE = "GITHUB_CHAT_PAPER_JOURNAL"
VERSION = "chat-paper-round-v2-margin"
ADELAIDE = ZoneInfo("Australia/Adelaide")
D = Decimal
FEE, SLIP = D("0.001"), D("0.0005")
MAX_LEVERAGE = D("100")
BORROW_APR = D("0.10")  # Declared simulation assumption, not an exchange rate.
FINANCING_RESERVE_RATE = D("0.0003")  # 3bp/24h covers modeled APR and financed entry fees.
MAINTENANCE_RATIO = D("0.005")
ALLOWED = {
    "ticker": "/api/v5/market/ticker?instId=BTC-USDT",
    "books": "/api/v5/market/books?instId=BTC-USDT&sz=5",
    "candles": "/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=20",
    "instruments": "/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
    "universe": "/api/v5/market/tickers?instType=SPOT",
}


class Blocked(ValueError):
    """An unmet admission condition, not permission to stop a schedule."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Blocked(reason)


def number(value: str) -> Decimal:
    require(isinstance(value, str) and bool(re.fullmatch(r"-?\d{1,30}(?:\.\d{1,100})?", value)), "INVALID_DECIMAL")
    return D(value)


def text(value: Decimal) -> str:
    return format(value, "f")


def stamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.utcoffset() is not None, "TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def increment(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    require(step > 0, "INVALID_INCREMENT")
    return (value / step).to_integral_value(rounding=rounding) * step


def response(market: dict, key: str, now: datetime, fresh: bool = False) -> list:
    item = market.get(key, {})
    require(item.get("endpoint") == ALLOWED[key], "MISSING_OR_UNAPPROVED_" + key.upper())
    require(item.get("transport") in {"PUBLIC_OKX_GET", "WEB_PUBLIC_OKX_GET"}, "UNVERIFIED_MARKET_TRANSPORT")
    received = stamp(item["retrieved_at_utc"])
    require(received <= now, "FUTURE_RETRIEVAL")
    if fresh:
        require((now - received).total_seconds() <= 5, "STALE_RETRIEVAL")
    body = item.get("body", {})
    require(body.get("code") == "0" and isinstance(body.get("data"), list) and body["data"], "MISSING_OR_FAILED_" + key.upper())
    return body["data"]


def quote(market: dict, now: datetime) -> dict:
    row = response(market, "books", now, fresh=True)[0]
    source_ms = int(row["ts"])
    require(-1000 <= int(now.timestamp() * 1000) - source_ms <= 5000, "STALE_OR_FUTURE_QUOTE")
    require(row["bids"] and row["asks"], "EMPTY_BOOK")
    bid, bid_qty = map(number, row["bids"][0][:2])
    ask, ask_qty = map(number, row["asks"][0][:2])
    require(0 < bid < ask and bid_qty >= 0 and ask_qty >= 0, "INVALID_BOOK")
    return {"bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty, "source_ms": source_ms}


def stop_distance(market: dict, now: datetime, entry: Decimal) -> Decimal:
    rows = response(market, "candles", now)
    confirmed = sorted((r for r in rows if len(r) >= 9 and r[8] == "1"), key=lambda r: int(r[0]))
    require(len(confirmed) >= 15, "INSUFFICIENT_CONFIRMED_1H_CANDLES")
    rows = confirmed[-15:]
    times = [int(r[0]) for r in rows]
    require(len(set(int(r[0]) for r in confirmed)) == len(confirmed), "DUPLICATE_CANDLES")
    require(all(t % 3600000 == 0 for t in times), "OFF_GRID_CANDLES")
    require(all(b - a == 3600000 for a, b in zip(times, times[1:])), "GAPPED_CANDLES")
    require(times[-1] == (int(now.timestamp() * 1000) // 3600000 - 1) * 3600000, "STALE_OR_FUTURE_CANDLES")
    values = []
    for r in rows:
        op, hi, lo, close = map(number, r[1:5])
        require(0 < lo <= min(op, close) <= max(op, close) <= hi, "INVALID_OHLC")
        values.append((hi, lo, close))
    tr = [max(h - l, abs(h - values[i - 1][2]), abs(l - values[i - 1][2])) for i, (h, l, _) in enumerate(values) if i]
    return max(D("1.5") * sum(tr) / D(14), D("0.01") * entry)


def preview(nav: Decimal, entry: Decimal, distance: Decimal, lot: Decimal, tick: Decimal, minimum: Decimal,
            financing_reserve_rate: Decimal = D("0")) -> dict:
    require(nav > 0 and entry > 0 and distance > 0 and lot > 0 and tick > 0 and minimum > 0, "INVALID_SIZING_INPUT")
    require(entry % tick == 0, "OFF_TICK_ENTRY")
    stop = increment(entry - distance, tick, ROUND_FLOOR)
    require(0 < stop < entry, "INVALID_STOP")
    reserve = (entry * financing_reserve_rate).quantize(D("0.000000000000000001"), rounding=ROUND_CEILING)
    unit = entry * (1 + FEE) - stop * (1 - SLIP) * (1 - FEE) + reserve
    qty = increment(max(nav * D("0.005") / unit, minimum), lot, ROUND_CEILING)
    risk = qty * unit
    require(nav * D("0.005") <= risk <= nav * D("0.0051"), "LOT_ROUNDING_EXCEEDS_RISK_BAND")
    tp = increment((entry * (1 + FEE) + reserve + 2 * unit) / ((1 - SLIP) * (1 - FEE)), tick, ROUND_CEILING)
    reward = qty * (tp * (1 - SLIP) * (1 - FEE) - entry * (1 + FEE) - reserve)
    require(reward >= 2 * risk, "INVALID_NET_REWARD")
    return {"quantity": qty, "entry": entry, "stop": stop, "take_profit": tp, "original_risk": risk,
            "notional": qty * entry, "fee": qty * entry * FEE, "net_rr": reward / risk, "nav_at_entry": nav,
            "financing_reserve": qty * reserve}


def mutate_account(account: dict, market: dict, now: datetime, cycle_key: str) -> tuple[dict, list, list]:
    """Operate on a copy of a reconciled journal checkpoint; never adopt an epoch."""
    require(account.get("verification") == "VERIFIED_JOURNAL_CHECKPOINT", "CURRENT_ACCOUNT_CHECKPOINT_NOT_VERIFIED")
    require(account.get("epoch") == "cairn-500-usdt-20260906-v1" and account.get("historical_initial_capital_usdt") == "500", "WRONG_ACCOUNT_EPOCH")
    require(isinstance(account.get("positions"), list) and type(account.get("ledger_sequence")) is int and account["ledger_sequence"] >= 0, "INVALID_CHECKPOINT")
    require(account.get("checkpoint_provenance"), "CHECKPOINT_PROVENANCE_REQUIRED")
    q = quote(market, now)
    state = copy.deepcopy(account)
    cash = number(state["current_cash_usdt"])
    require(cash >= 0, "INVALID_CASH")
    debt = number(state.get("borrowed_usdt", "0"))
    financing = number(state.get("financing_cost_usdt", "0"))
    require(debt >= 0 and financing >= 0, "INVALID_DEBT_OR_FINANCING")
    lots = state["positions"]
    require(len({p["trade_id"] for p in lots}) == len(lots), "DUPLICATE_LOTS")
    for p in lots:
        require(p.get("instrument") == "BTC-USDT" and p.get("origin") in {"CORE", "EXPLORATION", "LEGACY"}, "UNSUPPORTED_EXISTING_LOT")
        require(number(p["quantity"]) > 0 and number(p["cost_basis_usdt"]) > 0 and number(p["original_risk_usdt"]) > 0, "INVALID_LOT_ACCOUNTING")
        require(0 < number(p["stop"]) < number(p["entry"]) < number(p["take_profit"]), "INVALID_EXISTING_BRACKET")
        require(p.get("latched_exit") in {None, "STOP_LOSS", "TAKE_PROFIT", "MARGIN_LIQUIDATION", "TIME_EXIT"}, "INVALID_EXIT_LATCH")
        if p.get("exit_due_at_utc"):
            stamp(p["exit_due_at_utc"])
    totals = state["realized_net_pnl_usdt"]
    realized = {origin: number(totals[origin]) for origin in ("CORE", "EXPLORATION", "LEGACY")}
    fees = number(state["fees_usdt"])
    require(fees >= 0, "INVALID_FEES")
    require(abs(cash + sum((number(p["cost_basis_usdt"]) for p in lots), D(0)) - debt - D("500") - sum(realized.values())) <= D("1e-45"), "CHECKPOINT_ACCOUNTING_MISMATCH")
    interest = D(0)
    if debt:
        require(bool(state.get("financing_observed_at_utc")), "MISSING_FINANCING_TIMESTAMP")
        elapsed = D(str((now - stamp(state["financing_observed_at_utc"])).total_seconds()))
        require(elapsed >= 0, "FUTURE_FINANCING_TIMESTAMP")
        interest = (debt * BORROW_APR * elapsed / D(31536000)).quantize(D("0.000000000000000001"), rounding=ROUND_CEILING)
        debt += interest
        financing += interest
        realized["EXPLORATION"] -= interest
    starting_gross = sum((number(p["quantity"]) * q["bid"] for p in lots), D(0))
    liquidation = debt > 0 and starting_gross > 0 and cash + starting_gross - debt <= starting_gross * MAINTENANCE_RATIO
    fills, remaining = [], []
    bid_depth = q["bid_qty"]
    for p in sorted(lots, key=lambda p: p["trade_id"]):
        qty = number(p["quantity"])
        reason = p.get("latched_exit") or ("MARGIN_LIQUIDATION" if liquidation else "STOP_LOSS" if q["bid"] <= number(p["stop"]) else "TAKE_PROFIT" if q["bid"] >= number(p["take_profit"]) else "TIME_EXIT" if p.get("exit_due_at_utc") and now >= stamp(p["exit_due_at_utc"]) else None)
        if not reason:
            remaining.append(p)
            continue
        p["latched_exit"] = reason
        sold = increment(min(qty, bid_depth), number(p["lot_size"]), ROUND_FLOOR)
        if sold <= 0:
            remaining.append(p)
            continue
        price = q["bid"] * (1 - SLIP)
        fee = sold * price * FEE
        proceeds = sold * price - fee
        basis = number(p["cost_basis_usdt"]) * sold / qty
        cash += proceeds
        fees += fee
        realized[p["origin"]] += proceeds - basis
        bid_depth -= sold
        fills.append({"fill_id": cycle_key + ":exit:" + p["trade_id"], "trade_id": p["trade_id"], "position_effect": "CLOSE",
                      "origin": p["origin"], "reason": reason, "quantity": text(sold), "price": text(price), "fee_usdt": text(fee),
                      "realized_net_pnl_usdt": text(proceeds - basis), "simulated_fill": True, "live_order_submitted": False,
                      "observed_at_utc": now.isoformat(), "unobserved_since": state.get("last_observed_at_utc"), "reduce_only": True})
        if sold < qty:
            p["quantity"] = text(qty - sold)
            p["cost_basis_usdt"] = text(number(p["cost_basis_usdt"]) - basis)
            remaining.append(p)
    gross = sum((number(p["quantity"]) * q["bid"] for p in remaining), D(0))
    repaid = min(cash, debt)
    cash -= repaid
    debt -= repaid
    nav = cash + gross - debt  # Preserve deficits after gaps; never clamp or reset.
    today = now.astimezone(ADELAIDE).date().isoformat()
    day = state.get("day", {})
    day_problem = None
    if not day.get("date") or not day.get("start_nav_usdt"):
        day_problem = "DAY_START_NAV_NOT_RECONCILED"
    elif day["date"] < today:
        day = {"date": today, "start_nav_usdt": text(nav), "basis": "FIRST_OBSERVED_NAV_OF_ADELAIDE_DAY"}
    elif day["date"] > today:
        day_problem = "FUTURE_DAY_CHECKPOINT"
    errors = []
    try:
        require(not liquidation, "MARGIN_LIQUIDATION_OBSERVED")
        require(nav > 0, "ACCOUNT_EQUITY_EXHAUSTED")
        require(day_problem is None, day_problem or "INVALID_DAY")
        require(number(day["start_nav_usdt"]) > 0 and nav > number(day["start_nav_usdt"]) * D("0.95"), "DAILY_LOSS_LIMIT")
        require(all(not p.get("latched_exit") for p in remaining), "EXISTING_EXIT_PENDING")
        info = response(market, "instruments", now, fresh=True)
        info = [i for i in info if i.get("instId") == "BTC-USDT" and i.get("instType") == "SPOT" and i.get("state") == "live"]
        require(len(info) == 1, "INVALID_INSTRUMENT")
        inst = info[0]
        b = preview(nav, q["ask"], stop_distance(market, now, q["ask"]), number(inst["lotSz"]), number(inst["tickSz"]), number(inst["minSz"]), FINANCING_RESERVE_RATE)
        reserved = sum((number(p["original_risk_usdt"]) for p in remaining), D(0))
        post_entry_gross = gross + b["quantity"] * q["bid"]
        post_entry_nav = nav - b["fee"] - b["quantity"] * (q["ask"] - q["bid"])
        require(len(remaining) < 10 and reserved + b["original_risk"] <= nav * D("0.05")
                and b["notional"] <= nav * D("0.5")
                and post_entry_gross <= MAX_LEVERAGE * post_entry_nav, "BLOCKED_CAPITAL_OR_RISK_CAPACITY")
        require(b["quantity"] <= q["ask_qty"], "INSUFFICIENT_OBSERVED_ASK_DEPTH")
        borrowed_now = max(D(0), b["notional"] + b["fee"] - cash)
        debt += borrowed_now
        cash += borrowed_now
        tid = cycle_key + ":exploration:BTC-USDT"
        lot_record = {"trade_id": tid, "entry_cycle_key": cycle_key, "instrument": "BTC-USDT", "origin": "EXPLORATION",
                      "experiment": "BTC_SPOT_ATR14_SAMPLER_V1_NOT_ALPHA", "quantity": text(b["quantity"]), "lot_size": inst["lotSz"],
                      "entry": text(b["entry"]), "stop": text(b["stop"]), "take_profit": text(b["take_profit"]),
                      "original_risk_usdt": text(b["original_risk"]), "cost_basis_usdt": text(b["notional"] + b["fee"]),
                      "protection_state": "OBSERVATION_RULES_ONLY", "latched_exit": None,
                      "exit_due_at_utc": (now + timedelta(hours=24)).isoformat(),
                      "financing_reserve_24h_usdt": text(b["financing_reserve"])}
        remaining.append(lot_record)
        cash -= b["notional"] + b["fee"]
        fees += b["fee"]
        fills.append({**lot_record, "fill_id": tid + ":fill", "order_id": tid + ":order", "position_effect": "OPEN",
                      "notional_usdt": text(b["notional"]), "fee_usdt": text(b["fee"]), "nav_at_entry": text(nav),
                      "planned_risk_pct": text(b["original_risk"] / nav * 100), "net_reward_risk": text(b["net_rr"]),
                      "borrowed_for_entry_usdt": text(borrowed_now),
                      "observed_at_utc": now.isoformat(), "simulated_fill": True, "live_order_submitted": False})
    except (Blocked, KeyError, ValueError, TypeError, IndexError) as exc:
        errors.append(str(exc) if isinstance(exc, Blocked) else "INVALID_OR_MISSING_ENTRY_DATA")
    gross = sum((number(p["quantity"]) * q["bid"] for p in remaining), D(0))
    unrealized = {origin: sum((number(p["quantity"]) * q["bid"] - number(p["cost_basis_usdt"]) for p in remaining if p["origin"] == origin), D(0)) for origin in realized}
    state.update(current_cash_usdt=text(cash), current_nav_usdt=text(cash + gross - debt), positions=remaining,
                 borrowed_usdt=text(debt), financing_cost_usdt=text(financing), financing_observed_at_utc=now.isoformat(),
                 financing_charged_this_round_usdt=text(interest), debt_repaid_this_round_usdt=text(repaid),
                 max_gross_leverage=text(MAX_LEVERAGE), margin_model="SIMULATED_LONG_SPOT_BORROWING",
                 fees_usdt=text(fees), gross_exposure_usdt=text(gross), ledger_sequence=state["ledger_sequence"] + 1,
                 original_open_risk_usdt=text(sum((number(p["original_risk_usdt"]) for p in remaining), D(0))),
                 realized_net_pnl_usdt={k: text(v) for k, v in realized.items()}, unrealized_net_pnl_usdt={k: text(v) for k, v in unrealized.items()},
                 total_net_pnl_usdt=text(sum(realized.values()) + sum(unrealized.values())), day=day, last_observed_at_utc=now.isoformat())
    return state, fills, errors


def build_round(previous: dict, market: dict, *, runner: int, now: datetime, scheduled_at: str | None,
                source_commit: str, previous_path: str, previous_sha: str) -> dict:
    require(type(runner) is int and 1 <= runner <= 15, "INVALID_RUNNER")
    require(now.utcoffset() is not None, "TIMEZONE_REQUIRED")
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "INVALID_SOURCE_COMMIT")
    require(re.fullmatch(r"[0-9a-f]{40}", previous_sha) is not None, "INVALID_PREDECESSOR_BLOB")
    require(previous_path.startswith("paper-journal/rounds/") and ".." not in previous_path, "INVALID_PREDECESSOR_PATH")
    require(previous.get("mode") == MODE, "WRONG_PREDECESSOR_MODE")
    original = stamp(scheduled_at) if scheduled_at else now.astimezone(timezone.utc)
    local = original.astimezone(ADELAIDE)
    if scheduled_at:
        require(local.minute == 4 * (runner - 1) and local.second == 0 and local.microsecond == 0, "WRONG_ORIGINAL_SCHEDULE_SLOT")
        require(original <= now, "FUTURE_SCHEDULE_SLOT")
    cycle_id = local.strftime("%Y-%m-%dT%H-%M") + ("" if scheduled_at else local.strftime("-%S") + "-MANUAL") + f"-CAIRN-{runner:02d}"
    key = original.isoformat() + f"|CAIRN-{runner:02d}|" + ("SCHEDULED" if scheduled_at else "MANUAL")
    cycle_key = hashlib.sha256(key.encode()).hexdigest()
    require(cycle_key not in previous.get("processed_cycle_keys", []) and cycle_key != previous.get("cycle_key"), "CYCLE_ALREADY_RECORDED")
    evidence = copy.deepcopy(market)
    scan = {"full_scan_completed": False, "scope": "BTC-USDT_ONLY", "observed_count": 0, "research_priority_not_alpha": [], "errors": []}
    try:
        rows = response(market, "universe", now)
        require(all(isinstance(r, dict) and r.get("instType") == "SPOT" and r.get("instId") for r in rows), "INVALID_UNIVERSE_ROWS")
        require(len({r["instId"] for r in rows}) == len(rows), "DUPLICATE_UNIVERSE_ROWS")
        eligible = [r for r in rows if r["instId"].endswith("-USDT") and number(r["volCcy24h"]) >= 0]
        scan.update(scope="ALL_RETURNED_OKX_SPOT_TICKERS", observed_count=len(rows), eligible_usdt_count=len(eligible),
                    research_priority_not_alpha=[r["instId"] for r in sorted(eligible, key=lambda r: number(r["volCcy24h"]), reverse=True)[:10]])
        ages = [(int(now.timestamp() * 1000) - int(r["ts"])) / 1000 for r in rows]
        scan["oldest_source_age_seconds"] = max(ages)
        scan["full_scan_completed"] = all(-1 <= age <= 5 for age in ages)
        if not scan["full_scan_completed"]:
            scan["errors"].append("UNIVERSE_QUOTES_NOT_FRESH")
    except (Blocked, KeyError, ValueError, TypeError) as exc:
        scan["errors"].append(str(exc) if isinstance(exc, Blocked) else "INVALID_UNIVERSE_DATA")
        try:
            rows = response(market, "ticker", now)
            require(len(rows) == 1 and rows[0].get("instId") == "BTC-USDT", "INVALID_BTC_TICKER")
            scan.update(observed_count=1, reference_price=rows[0]["last"], source_timestamp_ms=rows[0]["ts"],
                        reference_age_seconds=(int(now.timestamp() * 1000) - int(rows[0]["ts"])) / 1000)
        except (Blocked, KeyError, ValueError, TypeError):
            scan["errors"].append("NO_USABLE_TICKER")
    account = copy.deepcopy(previous.get("account", {}))
    fills, blockers = [], []
    try:
        with localcontext() as ctx:
            ctx.prec = 80
            account, fills, blockers = mutate_account(account, market, now, cycle_key)
    except (Blocked, KeyError, ValueError, TypeError, IndexError) as exc:
        blockers.append(str(exc) if isinstance(exc, Blocked) else "INVALID_OR_MISSING_CHECKPOINT_DATA")
    new_entries = [f for f in fills if f["position_effect"] == "OPEN"]
    exits = [f for f in fills if f["position_effect"] == "CLOSE"]
    return {"schema_version": 2, "mode": MODE, "strategy_version": VERSION, "cycle_id": cycle_id, "cycle_key": cycle_key,
            "record_type": "SCHEDULED_ROUND" if scheduled_at else "MANUAL_ROUND", "scheduled_at": scheduled_at,
            "recorded_at_utc": now.astimezone(timezone.utc).isoformat(), "source_commit": source_commit,
            "previous_round": {"path": previous_path, "blob_sha": previous_sha},
            "processed_cycle_keys": previous.get("processed_cycle_keys", []) + ([previous["cycle_key"]] if previous.get("cycle_key") and previous["cycle_key"] not in previous.get("processed_cycle_keys", []) else []) + [cycle_key],
            "status": "PAPER_ENTRY_RECORDED_LOCALLY_PENDING_PUBLICATION" if new_entries else "DECISION_RECORDED_NO_NEW_ENTRY",
            "scan": scan, "market_evidence": evidence, "account": account, "simulated_fills": fills,
            "new_core_entries": 0, "new_exploration_entries": len(new_entries), "exits": len(exits),
            "minimum_new_entry_satisfied": bool(new_entries), "blockers": blockers,
            "core_status": "CORE_UNAVAILABLE", "full_strategy_cycle_completed": False,
            "decisions": [{"action": "OPEN_EXPLORATION" if new_entries else "NO_NEW_ENTRY",
                           "rationale": "Approved BTC volatility sampler, not an alpha forecast." if new_entries else "Preserve account and risk limits; entry conditions not met.",
                           "evidence": blockers or ["VALIDATED_QUOTE_ATR_AND_RISK_GATES"],
                           "alternative_rejected": "Inventing balances, stale-price fills, or continuous protection."}],
            "review": {"previous_cycle": previous.get("cycle_id"), "previous_status": previous.get("status"),
                       "outcome": "EXITS_OBSERVED" if exits else "NO_NEW_REALIZED_OUTCOME_VERIFIED",
                       "causality": "No attribution of profitability to a single round; open positions have pending outcomes.",
                       "unobserved_interval": {"from": previous.get("recorded_at_utc"), "to": now.isoformat()}},
            "improvement": {"id": "QUOTE_AND_CONTINUITY_AUDIT", "hypothesis": "Separating stale observations and unknown state prevents fabricated paper performance.",
                            "activity": "Validate source timestamps, predecessor identity and admission failures; retain observations for next-round comparison.",
                            "evaluation": {"scan_errors": scan["errors"], "admission_failures": blockers}, "promotion": "NONE", "active_risk_settings_changed": False,
                            "rollback_condition": "Any false acceptance, altered history, or regression requires reverting source; append corrections, never overwrite rounds."},
            "cost_assumptions": {"entry_fee_rate": text(FEE), "exit_fee_rate": text(FEE), "exit_slippage_rate": text(SLIP), "entry_model": "OBSERVED_TOP_ASK_WITH_SUFFICIENT_DEPTH", "fee_tier_claim": "MODELED_NOT_VERIFIED_ACCOUNT_FEE_TIER"},
            "margin_assumptions": {"max_gross_leverage": text(MAX_LEVERAGE), "borrow_apr": text(BORROW_APR),
                                   "maintenance_equity_to_gross_ratio": text(MAINTENANCE_RATIO),
                                   "source": "DECLARED_SIMULATION_ASSUMPTIONS_NOT_EXCHANGE_TERMS",
                                   "planned_financing_horizon_hours": 24,
                                   "planned_financing_reserve_rate": text(FINANCING_RESERVE_RATE),
                                   "exit_model": "OBSERVED_BID_WITH_COSTS_AND_SHARED_DEPTH; delayed observations may exceed planned loss or financing reserve"},
            "continuous_protection": False, "live_order_submitted": False,
            "persistence": "LOCAL_OUTPUT_ONLY_UNTIL_GITHUB_COMMIT_AND_READBACK", "scheduling": {"changes_made": False, "active_state": "UNVERIFIED"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("previous", "previous-path", "previous-blob-sha", "market", "source-commit", "out"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--runner", type=int, required=True)
    parser.add_argument("--scheduled-at")
    args = parser.parse_args()
    raw = Path(args.previous).read_bytes()
    require(git_blob(raw) == args.previous_blob_sha, "PREVIOUS_BLOB_MISMATCH")
    result = build_round(json.loads(raw), json.loads(Path(args.market).read_text()), runner=args.runner,
                         now=datetime.now(timezone.utc), scheduled_at=args.scheduled_at,
                         source_commit=args.source_commit, previous_path=args.previous_path, previous_sha=args.previous_blob_sha)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)
        file.write("\n")
    print(json.dumps({"status": result["status"], "cycle_id": result["cycle_id"], "output": str(output), "blockers": result["blockers"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
