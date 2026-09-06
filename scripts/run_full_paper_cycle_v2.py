from __future__ import annotations

import hashlib, json, math, os, time, urllib.parse, urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

from cairn.models import PaperAction
from cairn.paper import PaperState, Position, apply_action, create_account, mark_to_market
from cairn.storage import Store

ADELAIDE=ZoneInfo("Australia/Adelaide")
HOSTS=("https://openapi.okx.com","https://www.okx.com")
FEE_RATE=Fraction(1,10000)
POSITION_MAX=Fraction(25,10000)
TOTAL_MAX=Fraction(50,10000)
INITIAL_CASH="100000"

def utcnow(): return datetime.now(timezone.utc)
def F(v): return Fraction(str(v))
def D(v,places=12): return (f"{float(v):.{places}f}".rstrip("0").rstrip(".") or "0")
def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,indent=2,sort_keys=True,default=str),encoding="utf-8")

def get(path,params):
    errors=[]
    for host in HOSTS:
        try:
            url=host+path+"?"+urllib.parse.urlencode(params)
            req=urllib.request.Request(url,headers={"Accept":"application/json","Accept-Encoding":"identity","User-Agent":"Cairn/0.5 paper-research"})
            with urllib.request.urlopen(req,timeout=10) as r: raw=r.read(5_000_001)
            if len(raw)>5_000_000: raise RuntimeError("response too large")
            p=json.loads(raw.decode())
            if p.get("code")!="0" or not isinstance(p.get("data"),list): raise RuntimeError(f"OKX code={p.get('code')}")
            return p["data"]
        except Exception as e: errors.append(f"{host}:{type(e).__name__}:{e}")
    raise RuntimeError("OKX_PUBLIC_UNAVAILABLE "+" | ".join(errors))

def state_load(path):
    if not path.exists(): return create_account(INITIAL_CASH)
    p=json.loads(path.read_text())
    return PaperState(sequence=int(p["sequence"]),cash=F(p["cash"]),positions={k:Position(F(v["quantity"]),F(v["cost_basis"])) for k,v in p["positions"].items()},fees_paid=F(p.get("fees_paid","0")),distributions=F(p.get("distributions","0")))

def state_dump(path,s):
    dump(path,{"sequence":s.sequence,"cash":D(s.cash),"positions":{k:{"quantity":D(v.quantity),"cost_basis":D(v.cost_basis)} for k,v in s.positions.items()},"fees_paid":D(s.fees_paid),"distributions":D(s.distributions)})

def main():
    started=utcnow(); runner=os.getenv("CAIRN_RUNNER_ID","CAIRN-07"); cycle=os.getenv("CAIRN_CYCLE_ID") or started.astimezone(ADELAIDE).strftime(f"%Y-%m-%dT%H-%M-{runner}")
    out=Path("artifacts")/cycle; out.mkdir(parents=True,exist_ok=True)
    store=Store(out/"cairn.sqlite3"); store.initialize()
    report={"cycle_id":cycle,"runner":runner,"started_at":started.isoformat(),"mode":"LOCAL_PAPER_LEDGER","venue_data":"OKX_PUBLIC","live_order_transport":False,"capital_permissions":"NONE","status":"RUNNING","core":{},"exploration":{},"incidents":[],"minimum_paper_trade_per_cycle":1}
    try:
        inst=get("/api/v5/public/instruments",{"instType":"SPOT","instId":"BTC-USDT"})[0]
        tick=get("/api/v5/market/ticker",{"instId":"BTC-USDT"})[0]
        book=get("/api/v5/market/books",{"instId":"BTC-USDT","sz":"5"})[0]
        candles=get("/api/v5/market/history-candles",{"instId":"BTC-USDT","bar":"1H","limit":"72"})
        nowms=int(time.time()*1000); ta=nowms-int(tick["ts"]); ba=nowms-int(book["ts"])
        if ta < -5000 or ba < -5000 or ta > 120000 or ba > 120000: raise RuntimeError(f"STALE_OKX_DATA ticker_age_ms={ta} book_age_ms={ba}")
        if inst.get("state")!="live": raise RuntimeError("INSTRUMENT_NOT_LIVE")
        report["health"]={"paper_mode_verified":True,"verification":"no private/order transport exists; execution is local paper ledger only","okx_public":"OK","shared_state_restored":Path("state/account.json").exists()}
        market={"instrument":inst,"ticker":tick,"book":book,"ticker_age_ms":ta,"book_age_ms":ba}; report["market_data"]=market
        store.put_record(record_id=f"{cycle}:market",record_type="market_snapshot",created_at=started.isoformat(),payload=market,actor=runner,asset_id="BTC",mode="PROSPECTIVE")

        rows=[r for r in candles if len(r)>=9 and r[8]=="1"]; rows.sort(key=lambda r:int(r[0])); closes=[float(r[4]) for r in rows]
        if len(closes)<25: raise RuntimeError("INSUFFICIENT_CONFIRMED_CANDLES")
        rets=[math.log(closes[i]/closes[i-1]) for i in range(1,len(closes))]
        last,open24,bid,ask=map(F,(tick["last"],tick["open24h"],tick["bidPx"],tick["askPx"])); mid=(bid+ask)/2
        bids=sum((F(x[1]) for x in book["bids"]),Fraction()); asks=sum((F(x[1]) for x in book["asks"]),Fraction())
        feat={"momentum_24h":D(last/open24-1),"realized_vol_24h_log":f"{math.sqrt(sum(x*x for x in rets[-24:])):.12g}","spread_bps":D((ask-bid)/mid*10000),"top5_depth_imbalance":D((bids-asks)/(bids+asks) if bids+asks else 0)}
        report["features"]=feat; store.put_record(record_id=f"{cycle}:features",record_type="features",created_at=started.isoformat(),payload=feat,actor=runner,asset_id="BTC",mode="PROSPECTIVE")
        report["core"]={"signal_status":"NO_EXECUTABLE_ACTIVE_ALPHA_MODEL_IN_PUBLICATION_BUILD","orders":0,"fills":0}

        statepath=Path("state/account.json"); state=state_load(statepath); pre_nav=mark_to_market(state,{"BTC-USDT":tick["last"]})
        pos=state.positions.get("BTC-USDT",Position()); existing=pos.quantity*last
        if existing/pre_nav > TOTAL_MAX: raise RuntimeError("EXPLORATION_EXPOSURE_ABOVE_LIMIT")
        capacity=pre_nav*TOTAL_MAX-existing; notional=min(pre_nav*Fraction(10,10000),pre_nav*POSITION_MAX,capacity)
        lot=F(inst.get("lotSz") or "0.00000001"); minsz=F(inst.get("minSz") or "0"); qty=(notional/ask//lot)*lot
        if qty<=0 or qty<minsz: raise RuntimeError("EXPLORATION_SIZE_BELOW_MINIMUM")
        visible=F(book["asks"][0][1]);
        if qty>visible: raise RuntimeError("EXPLORATION_SIZE_EXCEEDS_VISIBLE_ASK")
        fee=qty*ask*FEE_RATE; aid=hashlib.sha256(f"{cycle}|exploration|BTC-USDT|BUY".encode()).hexdigest()[:32]
        action=PaperAction(action_id=aid,account_id="cairn-shared-paper",idempotency_key=aid,expected_sequence=state.sequence,ts=started,inst_id="BTC-USDT",side="BUY",quantity=D(qty),price=D(ask),fee=D(fee),rationale="exploration:execution_pipeline_validation")
        if store.get_record(f"{cycle}:fill") is not None: raise RuntimeError("DUPLICATE_FILL")
        newstate,receipt=apply_action(state,action)
        fill={"cycle_id":cycle,"action_id":aid,"client_order_id":aid,"instrument":"BTC-USDT","side":"BUY","fill_quantity":D(qty),"fill_price":D(ask),"notional":D(qty*ask),"fee":D(fee),"trade_origin":"exploration","exploration_reason":"execution_pipeline_validation","execution_mode":"LOCAL_PAPER_LEDGER","market_reference":"FRESH_OKX_PUBLIC_TOP_ASK","simulated_fill":True,"live_order_submitted":False,"receipt":asdict(receipt)}
        store.put_record(record_id=f"{cycle}:order",record_type="paper_order",created_at=started.isoformat(),payload=action,actor=runner,asset_id="BTC",mode="PROSPECTIVE")
        store.put_record(record_id=f"{cycle}:fill",record_type="paper_fill",created_at=started.isoformat(),payload=fill,actor=runner,asset_id="BTC",mode="PROSPECTIVE")
        state_dump(statepath,newstate); report["exploration"]={"orders":1,"fills":1,"fill":fill}

        execution={"requested_price":D(ask),"fill_price":D(ask),"slippage_bps_vs_requested":"0","spread_bps":feat["spread_bps"],"classification":"SIMULATED_TAKER_AT_TOP_ASK","visible_top_ask_qty":D(visible)}; report["execution_quality"]=execution
        store.put_record(record_id=f"{cycle}:execution",record_type="execution_quality",created_at=started.isoformat(),payload=execution,actor=runner,asset_id="BTC",mode="PROSPECTIVE")
        post_nav=mark_to_market(newstate,{"BTC-USDT":tick["last"]}); expected=state.cash-qty*ask-fee
        if newstate.cash!=expected or newstate.sequence!=state.sequence+1: raise RuntimeError("RECONCILIATION_MISMATCH")
        report["reconciliation"]={"internal_ledger":"MATCH","broker_demo_position":"NOT_APPLICABLE_LOCAL_PAPER","pre_sequence":state.sequence,"post_sequence":newstate.sequence}
        accounting={"pre_nav":D(pre_nav),"post_nav_marked_at_last":D(post_nav),"core_pnl":"0","exploration_pnl":D(post_nav-pre_nav),"total_pnl":D(post_nav-pre_nav),"fees":D(fee),"funding":"0"}; report["accounting"]=accounting
        report["performance"]={"core_statistics":"EXCLUDED_NO_CORE_TRADES","exploration_fill_count":1,"total_fill_count":1}
        report["anomalies"]=[]; report["hypotheses"]=[{"id":f"{cycle}:H1","hypothesis":"Compare taker-at-ask paper cost with maker/no-fill policy on future public-book snapshots.","production_change":False}]; report["validation"]={"status":"NOT_PROMOTED","reason":"execution observation only"}
        report["audit_chain_valid"]=store.verify_audit_chain(); report["status"]="COMPLETED"; report["minimum_paper_trade_per_cycle_satisfied"]=True
    except Exception as e:
        report["status"]="HALTED"; report["minimum_paper_trade_per_cycle_satisfied"]=False; report["incidents"].append({"type":type(e).__name__,"message":str(e)})
    report["completed_at"]=utcnow().isoformat(); dump(out/"cycle-report.json",report)
    lines=[f"# Cairn cycle {cycle}","",f"Status: **{report['status']}**",f"Paper minimum satisfied: **{report.get('minimum_paper_trade_per_cycle_satisfied',False)}**",f"Mode: **{report['mode']}**; live order transport disabled."]
    if report.get("exploration",{}).get("fill"):
        f=report["exploration"]["fill"]; lines += ["","## Recorded paper trade",f"- {f['side']} {f['fill_quantity']} {f['instrument']} @ {f['fill_price']}",f"- notional {f['notional']} USDT; fee {f['fee']} USDT",f"- origin: {f['trade_origin']} / {f['exploration_reason']}","- explicitly simulated local-paper fill referenced to fresh OKX public top-of-book; no live order submitted"]
    if report["incidents"]: lines += ["","## Incidents"]+[f"- {x['type']}: {x['message']}" for x in report["incidents"]]
    (out/"cycle-report.md").write_text("\n".join(lines)+"\n"); print(json.dumps(report,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
