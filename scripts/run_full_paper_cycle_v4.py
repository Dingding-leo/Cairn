from __future__ import annotations

import hashlib, json, math, os
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path

from cairn.models import PaperAction
from cairn.paper import Position, apply_action, mark_to_market
from cairn.storage import Store
import run_full_paper_cycle_v2 as b

F,D,get,utcnow,dump,state_load=b.F,b.D,b.get,b.utcnow,b.dump,b.state_load
ADELAIDE,FEE_RATE,POSITION_MAX,TOTAL_MAX=b.ADELAIDE,b.FEE_RATE,b.POSITION_MAX,b.TOTAL_MAX
NEAR_CAP,REDUCE_TARGET,ADD_TARGET=Fraction(45,10000),Fraction(40,10000),Fraction(10,10000)


def _write_state(path,state,history):
    dump(path,{"sequence":state.sequence,"cash":D(state.cash),
      "positions":{k:{"quantity":D(v.quantity),"cost_basis":D(v.cost_basis)} for k,v in state.positions.items()},
      "fees_paid":D(state.fees_paid),"distributions":D(state.distributions),
      "cycle_history":dict(sorted(history.items())[-100:])})


def _human(path,r):
    lines=[f"# Cairn cycle {r['cycle_id']}","",f"Status: **{r['status']}**",
      f"Paper minimum satisfied: **{r.get('minimum_paper_trade_per_cycle_satisfied',False)}**",
      f"Mode: **{r['mode']}**; live order transport disabled."]
    f=r.get("exploration",{}).get("fill")
    if f: lines += ["","## Recorded paper trade",f"- {f['side']} {f['fill_quantity']} {f['instrument']} @ {f['fill_price']}",
      f"- notional {f['notional']} USDT; fee {f['fee']} USDT",f"- origin: {f['trade_origin']} / {f['exploration_reason']}",
      f"- action/client ID: {f['action_id']}","- simulated local-paper fill referenced to fresh OKX public top-of-book; no live order submitted"]
    if r.get("incidents"): lines += ["","## Incidents"]+[f"- {x['type']}: {x['message']}" for x in r["incidents"]]
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    started=utcnow(); runner=os.getenv("CAIRN_RUNNER_ID","CAIRN-15")
    cycle=os.getenv("CAIRN_CYCLE_ID") or started.astimezone(ADELAIDE).strftime(f"%Y-%m-%dT%H-%M-{runner}")
    out=Path("artifacts")/cycle; out.mkdir(parents=True,exist_ok=True)
    store=Store(out/"cairn.sqlite3"); store.initialize(); statepath=Path("state/account.json")
    raw=json.loads(statepath.read_text()) if statepath.exists() else {}; history=raw.get("cycle_history",{}) if isinstance(raw,dict) else {}
    if not isinstance(history,dict): history={}
    prev=history.get(cycle)
    if isinstance(prev,dict) and isinstance(prev.get("report"),dict):
        r=prev["report"]; dump(out/"cycle-report.json",r); _human(out/"cycle-report.md",r)
        store.put_record(record_id=f"{cycle}:replay",record_type="cycle_replay",created_at=started.isoformat(),payload={"cycle_id":cycle,"action_id":prev.get("action_id")},actor=runner,mode="PROSPECTIVE")
        print(json.dumps(r,sort_keys=True)); return 0
    r={"cycle_id":cycle,"runner":runner,"started_at":started.isoformat(),"mode":"LOCAL_PAPER_LEDGER","venue_data":"OKX_PUBLIC",
      "live_order_transport":False,"capital_permissions":"NONE","status":"RUNNING","core":{},"exploration":{},"incidents":[],
      "minimum_paper_trade_per_cycle":1,"code_version":os.getenv("GITHUB_SHA","UNKNOWN"),
      "config":{"position_max_nav":D(POSITION_MAX),"total_exploration_max_nav":D(TOTAL_MAX),"near_cap_nav":D(NEAR_CAP),
                "reduce_target_nav":D(REDUCE_TARGET),"add_target_nav":D(ADD_TARGET),"fee_rate":D(FEE_RATE)}}
    def rec(name,payload,asset=None):
        store.put_record(record_id=f"{cycle}:{name}",record_type=name,created_at=started.isoformat(),payload=payload,actor=runner,asset_id=asset,mode="PROSPECTIVE")
    try:
        health={"paper_mode_verified":True,"verification":"local deterministic paper ledger only; no private/order transport in this execution path",
                "okx_public":"PENDING","shared_state_restored":statepath.exists(),"live_order_transport":False,"capital_permissions":"NONE"}
        r["health"]=health; rec("health",health); rec("code_config",{"code_version":r["code_version"],"config":r["config"]})
        inst=get("/api/v5/public/instruments",{"instType":"SPOT","instId":"BTC-USDT"})[0]
        tick=get("/api/v5/market/ticker",{"instId":"BTC-USDT"})[0]; book=get("/api/v5/market/books",{"instId":"BTC-USDT","sz":"5"})[0]
        candles=get("/api/v5/market/history-candles",{"instId":"BTC-USDT","bar":"1H","limit":"72"})
        nowms=int(utcnow().timestamp()*1000); ta=nowms-int(tick["ts"]); ba=nowms-int(book["ts"])
        if ta < -5000 or ba < -5000 or ta > 120000 or ba > 120000: raise RuntimeError(f"STALE_OKX_DATA ticker_age_ms={ta} book_age_ms={ba}")
        if inst.get("state")!="live" or not tick.get("bidPx") or not tick.get("askPx") or not book.get("bids") or not book.get("asks"): raise RuntimeError("INVALID_OKX_MARKET_STATE")
        health["okx_public"]="OK"; market={"instrument":inst,"ticker":tick,"book":book,"ticker_age_ms":ta,"book_age_ms":ba}; r["market_data"]=market; rec("market_data",market,"BTC")
        rows=sorted((x for x in candles if len(x)>=9 and x[8]=="1"),key=lambda x:int(x[0])); closes=[float(x[4]) for x in rows]
        if len(closes)<25: raise RuntimeError("INSUFFICIENT_CONFIRMED_CANDLES")
        rets=[math.log(closes[i]/closes[i-1]) for i in range(1,len(closes))]; last,open24,bid,ask=map(F,(tick["last"],tick["open24h"],tick["bidPx"],tick["askPx"])); mid=(bid+ask)/2
        if min(last,open24,bid,ask)<=0 or ask<bid: raise RuntimeError("INVALID_MARKET_PRICES")
        bd=sum((F(x[1]) for x in book["bids"]),Fraction()); ad=sum((F(x[1]) for x in book["asks"]),Fraction())
        feat={"momentum_24h":D(last/open24-1),"realized_vol_24h_log":f"{math.sqrt(sum(x*x for x in rets[-24:])):.12g}",
              "spread_bps":D((ask-bid)/mid*10000),"top5_depth_imbalance":D((bd-ad)/(bd+ad) if bd+ad else 0),"market_state":"LIQUID_SPOT_TOP_OF_BOOK"}
        r["features"]=feat; rec("features",feat,"BTC")
        sig={"core_signal_status":"NO_EXECUTABLE_ACTIVE_ALPHA_MODEL_IN_PUBLICATION_BUILD","core_orders":0,"core_fills":0}; r["core"]={"signal_status":sig["core_signal_status"],"orders":0,"fills":0}; rec("signals",sig,"BTC")
        state=state_load(statepath); pre=mark_to_market(state,{"BTC-USDT":tick["last"]}); pos=state.positions.get("BTC-USDT",Position())
        if pre<=0: raise RuntimeError("INVALID_NAV")
        existing=pos.quantity*last; ratio=existing/pre; portfolio={"pre_nav":D(pre),"cash":D(state.cash),"btc_quantity":D(pos.quantity),"btc_mark_value":D(existing),"exploration_exposure_nav":D(ratio),"core_target_change":"NONE"}; r["portfolio"]=portfolio; rec("portfolio_targets",portfolio,"BTC")
        lot=F(inst.get("lotSz") or "0"); minsz=F(inst.get("minSz") or "0")
        if lot<=0 or minsz<=0: raise RuntimeError("INVALID_INSTRUMENT_SIZE_RULES")
        if pos.quantity>0 and ratio>=NEAR_CAP:
            side="SELL"; target=(pre*REDUCE_TARGET/last//lot)*lot; qty=pos.quantity-target; price=bid; visible=F(book["bids"][0][1]); reason="exploration_exposure_reduction_near_shared_cap"; expid="EXP-EXPOSURE-CAP-REDUCE-001"
        else:
            side="BUY"; cap=pre*TOTAL_MAX-existing; target=min(pre*ADD_TARGET,pre*POSITION_MAX,cap); qty=(target/ask//lot)*lot; price=ask; visible=F(book["asks"][0][1]); reason="execution_pipeline_validation"; expid="EXP-TAKER-TOP-OF-BOOK-001"
        if qty<=0 or qty<minsz: raise RuntimeError("EXPLORATION_SIZE_BELOW_MINIMUM")
        if qty>visible: raise RuntimeError("EXPLORATION_SIZE_EXCEEDS_VISIBLE_TOP_LEVEL")
        if side=="SELL" and qty>pos.quantity: raise RuntimeError("EXPLORATION_REDUCTION_EXCEEDS_POSITION")
        notional=qty*price
        if notional>pre*POSITION_MAX: raise RuntimeError("EXPLORATION_TRADE_ABOVE_POSITION_LIMIT")
        remain=pos.quantity-qty if side=="SELL" else pos.quantity+qty; projected=remain*last/pre
        if projected>TOTAL_MAX: raise RuntimeError("EXPLORATION_EXPOSURE_ABOVE_LIMIT_AFTER_ACTION")
        if side=="BUY" and notional*(1+FEE_RATE)>state.cash: raise RuntimeError("INSUFFICIENT_PAPER_CASH")
        risk={"approved":True,"independent_gate":"DETERMINISTIC_RULES","side":side,"quantity":D(qty),"price":D(price),"gross_notional":D(notional),"gross_notional_nav":D(notional/pre),
              "pre_exploration_exposure_nav":D(ratio),"projected_exploration_exposure_nav":D(projected),"single_trade_limit_nav":D(POSITION_MAX),"shared_exploration_limit_nav":D(TOTAL_MAX),"experiment_id":expid}; r["risk"]=risk; rec("risk_decision",risk,"BTC")
        aid=hashlib.sha256(f"{cycle}|exploration|BTC-USDT|{side}".encode()).hexdigest()[:32]; fee=notional*FEE_RATE
        action=PaperAction(action_id=aid,account_id="cairn-shared-paper",idempotency_key=aid,expected_sequence=state.sequence,ts=started,inst_id="BTC-USDT",side=side,quantity=D(qty),price=D(price),fee=D(fee),rationale=f"exploration:{reason}:{expid}")
        new,receipt=apply_action(state,action); fill={"cycle_id":cycle,"action_id":aid,"client_order_id":aid,"instrument":"BTC-USDT","side":side,"fill_quantity":D(qty),"fill_price":D(price),"notional":D(notional),"fee":D(fee),
          "trade_origin":"exploration","exploration_reason":reason,"experiment_id":expid,"execution_mode":"LOCAL_PAPER_LEDGER","market_reference":"FRESH_OKX_PUBLIC_TOP_OF_BOOK","simulated_fill":True,"live_order_submitted":False,"receipt":asdict(receipt)}
        store.put_record(record_id=f"{cycle}:paper_order",record_type="paper_order",created_at=started.isoformat(),payload=action,actor=runner,asset_id="BTC",mode="PROSPECTIVE"); rec("paper_fill",fill,"BTC"); r["exploration"]={"orders":1,"fills":1,"fill":fill}
        exq={"requested_price":D(price),"fill_price":D(price),"slippage_bps_vs_requested":"0","spread_bps":feat["spread_bps"],"classification":"SIMULATED_TAKER_AT_TOP_"+("BID" if side=="SELL" else "ASK"),"visible_top_level_qty":D(visible)}; r["execution_quality"]=exq; rec("execution_quality",exq,"BTC")
        expected_cash=state.cash+qty*price-fee if side=="SELL" else state.cash-qty*price-fee; expected_qty=pos.quantity-qty if side=="SELL" else pos.quantity+qty; actual=new.positions.get("BTC-USDT",Position()).quantity
        if new.cash!=expected_cash or new.sequence!=state.sequence+1 or actual!=expected_qty: raise RuntimeError("RECONCILIATION_MISMATCH")
        post=mark_to_market(new,{"BTC-USDT":tick["last"]}); post_ratio=actual*last/post
        if post_ratio>TOTAL_MAX: raise RuntimeError("POST_TRADE_EXPLORATION_EXPOSURE_ABOVE_LIMIT")
        recon={"internal_ledger":"MATCH","broker_demo_position":"NOT_APPLICABLE_LOCAL_PAPER","pre_sequence":state.sequence,"post_sequence":new.sequence,"expected_quantity":D(expected_qty),"actual_quantity":D(actual),"post_exploration_exposure_nav":D(post_ratio)}; r["reconciliation"]=recon; rec("reconciliation",recon,"BTC")
        acct={"pre_nav":D(pre),"post_nav_marked_at_last":D(post),"core_pnl":"0","exploration_pnl":D(post-pre),"total_pnl":D(post-pre),"fees":D(fee),"funding":"0"}; r["accounting"]=acct; rec("accounting_pnl",acct,"BTC"); rec("positions_nav",{"sequence":new.sequence,"cash":D(new.cash),"btc_quantity":D(actual),"nav":D(post)},"BTC")
        perf={"core_statistics":"EXCLUDED_NO_CORE_TRADES","core_fill_count":0,"exploration_fill_count":1,"total_fill_count":1,"cycle_total_pnl":D(post-pre)}; r["performance"]=perf; rec("performance_attribution",perf,"BTC")
        anomalies=([{"code":"EXPLORATION_CAP_REDUCTION","detail":"Existing exploration exposure was near/above shared cap; reduced instead of accumulating."}] if side=="SELL" else []); r["anomalies"]=anomalies; rec("drift_regime_anomaly",{"anomalies":anomalies,"regime":feat["market_state"]},"BTC")
        hyp=[{"id":f"{cycle}:H1","hypothesis":"Compare taker-at-top paper cost with passive/no-fill execution assumptions.","production_change":False},{"id":f"{cycle}:H2","hypothesis":"A 0.40% exploration target provides buffer below the 0.50% shared cap.","production_change":False}]; r["hypotheses"]=hyp; rec("research_hypotheses",{"hypotheses":hyp},"BTC")
        val={"status":"NOT_PROMOTED","reason":"execution observation only; no core strategy change","checks":{"fresh_data":True,"paper_only":True,"nonzero_fill":qty>0,"risk_caps_respected":True,"reconciliation_match":True,"core_exploration_separated":True,"live_order_submitted":False}}; r["validation"]=val; rec("adversarial_validation",val,"BTC")
        r["audit_chain_valid"]=store.verify_audit_chain()
        if not r["audit_chain_valid"]: raise RuntimeError("AUDIT_CHAIN_INVALID")
        r["status"]="COMPLETED"; r["minimum_paper_trade_per_cycle_satisfied"]=True; r["completed_at"]=utcnow().isoformat()
        history[cycle]={"action_id":aid,"state_sequence":new.sequence,"fill":fill,"report":r}; _write_state(statepath,new,history); rec("final_report",r)
    except Exception as e:
        r["status"]="HALTED"; r["minimum_paper_trade_per_cycle_satisfied"]=False; r["incidents"].append({"type":type(e).__name__,"message":str(e)}); r["completed_at"]=utcnow().isoformat()
        try: rec("incident",r["incidents"][-1]); r["audit_chain_valid"]=store.verify_audit_chain(); rec("final_report",r)
        except Exception: r["audit_chain_valid"]=False
    dump(out/"cycle-report.json",r); _human(out/"cycle-report.md",r); print(json.dumps(r,sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
