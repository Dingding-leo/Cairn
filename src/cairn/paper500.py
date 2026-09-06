"""Small-capital prospective PAPER ledger. No exchange order capability exists here.

Account epochs are initialized explicitly. Runtime state is cumulative SQLite, never
Git content. Financial values are stored as exact rational pairs; decimal strings
are display/venue-size inputs, not the authority for intermediate calculations.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .exact import decimal_fraction as F, fraction_decimal as D
from .models import PaperAction
from .paper import PaperState, Position, apply_action, create_account, mark_to_market
from .storage import Store, canonical_json, sha256_text

UTC = timezone.utc
ADELAIDE = ZoneInfo('Australia/Adelaide')
EPOCH = 'cairn-500-usdt-20260906-v1'
STATE_ARTIFACT = 'cairn-state-' + EPOCH
MODE = 'LOCAL_PAPER_LEDGER'
INITIAL = '500'
FEE = Fraction(10, 10000)  # Explicit conservative model assumption, NOT a verified account fee.
POSITION_CAP, SLEEVE_CAP = Fraction(25, 10000), Fraction(50, 10000)
STAGES = ('health', 'market_data', 'features', 'signals', 'portfolio', 'risk', 'execution',
          'execution_quality', 'reconciliation', 'accounting', 'attribution', 'monitoring',
          'research', 'validation')
CONFIG = {'epoch': EPOCH, 'initial_capital': INITIAL, 'quote_currency': 'USDT',
          'mode': MODE, 'universe': ['BTC-USDT'], 'fee_rate': '0.001',
          'fee_source': 'ASSUMED_NOT_ACCOUNT_VERIFIED', 'position_cap': '0.0025',
          'exploration_cap': '0.005', 'core_policy': 'UNAVAILABLE_NO_CORE_ORDERS',
          'timezone': 'Australia/Adelaide', 'schedule_mutation_allowed': False}
CONFIG_SHA = sha256_text(canonical_json(CONFIG))


class Halt(RuntimeError):
    """Redacted deterministic reason; ends a cycle, never disables its schedule."""


def now() -> datetime:
    return datetime.now(UTC)


def require(test: bool, reason: str) -> None:
    if not test:
        raise Halt(reason)


def rational(value: Fraction) -> list[str]:
    return [str(value.numerator), str(value.denominator)]


def from_rational(value: list[str]) -> Fraction:
    require(isinstance(value, list) and len(value) == 2, 'INVALID_RATIONAL')
    require(all(isinstance(x, str) and len(x) <= 120 for x in value), 'INVALID_RATIONAL')
    return Fraction(int(value[0]), int(value[1]))


def encode_state(state: PaperState, nav: Fraction, peak: Fraction) -> dict[str, Any]:
    return {'epoch': EPOCH, 'config_sha': CONFIG_SHA, 'sequence': state.sequence,
            'cash': rational(state.cash), 'fees_paid': rational(state.fees_paid),
            'positions': {k: {'quantity': rational(v.quantity), 'cost_basis': rational(v.cost_basis),
                              'trade_origin': 'exploration'} for k, v in state.positions.items()},
            'last_nav': rational(nav), 'peak_nav': rational(peak)}


def decode_state(p: dict[str, Any]) -> PaperState:
    require(p['epoch'] == EPOCH and p['config_sha'] == CONFIG_SHA, 'ACCOUNT_EPOCH_OR_CONFIG_MISMATCH')
    require(type(p['sequence']) is int and p['sequence'] >= 0, 'INVALID_SEQUENCE')
    positions = {}
    for symbol, v in p['positions'].items():
        require(symbol == 'BTC-USDT' and v['trade_origin'] == 'exploration', 'FOREIGN_POSITION')
        positions[symbol] = Position(from_rational(v['quantity']), from_rational(v['cost_basis']))
        require(positions[symbol].quantity > 0 and positions[symbol].cost_basis >= 0, 'INVALID_POSITION')
    state = PaperState(p['sequence'], from_rational(p['cash']), positions,
                       from_rational(p['fees_paid']))
    require(state.cash >= 0 and state.fees_paid >= 0, 'INVALID_CASH_OR_FEES')
    require(from_rational(p['last_nav']) > 0 and from_rational(p['peak_nav']) > 0, 'INVALID_NAV')
    return state


def put(store: Store, conn: sqlite3.Connection, key: str, kind: str, payload: dict[str, Any],
        timestamp: str, actor: str) -> None:
    encoded = canonical_json(payload)
    digest = sha256_text(encoded)
    row = conn.execute('SELECT payload_sha256 FROM records WHERE record_id=?', (key,)).fetchone()
    if row is not None:
        require(row[0] == digest, 'IDEMPOTENCY_CONFLICT')
        return
    conn.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',
                 (key, kind, None, 'PROSPECTIVE', timestamp, encoded, digest))
    store._audit(conn, ts=timestamp, actor=actor, action='PUT_RECORD', object_id=key,
                 details={'record_type': kind, 'payload_sha256': digest})


def verify_database(path: Path) -> dict[str, Any]:
    require(path.is_file(), 'SHARED_STATE_MISSING_NO_AUTO_RESET')
    store = Store(path)
    require(store.verify_audit_chain(), 'AUDIT_CHAIN_INVALID')
    with store.connect() as conn:
        require(conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SQLITE_CORRUPT')
        meta = dict(conn.execute('SELECT key,value FROM meta').fetchall())
        require(meta.get('paper_epoch') == EPOCH and meta.get('config_sha') == CONFIG_SHA,
                'ACCOUNT_EPOCH_OR_CONFIG_MISMATCH')
        records = conn.execute('SELECT record_id,payload_json,payload_sha256 FROM records').fetchall()
        audited = {r['object_id']: json.loads(r['details_json'])['payload_sha256']
                   for r in conn.execute("SELECT * FROM audit_log WHERE action='PUT_RECORD'")}
        require(len(audited) == len(records), 'AUDIT_RECORD_COVERAGE_MISMATCH')
        for r in records:
            require(sha256_text(r['payload_json']) == r['payload_sha256'] == audited.get(r['record_id']),
                    'RECORD_HASH_MISMATCH')
        root = conn.execute('SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1').fetchone()
        states = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM records WHERE record_type='account_state'")]
        require(bool(states), 'ACCOUNT_STATE_MISSING')
        current = max(states, key=lambda s: s['sequence'])
        state = decode_state(current)
        require(sorted(s['sequence'] for s in states) == list(range(state.sequence + 1)),
                'ACCOUNT_SEQUENCE_GAP')
    return {'epoch': EPOCH, 'state': current, 'audit_root': root[0],
            'records': len(records), 'audit_chain_valid': True}


def initialize(path: Path) -> dict[str, Any]:
    """Explicit deployment operation; never called automatically by run_cycle."""
    require(not path.exists(), 'INITIALIZATION_REFUSES_OVERWRITE')
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path)
    store.initialize()
    with store.transaction() as conn:
        conn.execute('INSERT INTO meta VALUES(?,?)', ('paper_epoch', EPOCH))
        conn.execute('INSERT INTO meta VALUES(?,?)', ('config_sha', CONFIG_SHA))
        put(store, conn, EPOCH + ':genesis', 'account_state',
            encode_state(create_account(INITIAL), F(INITIAL), F(INITIAL)), now().isoformat(), 'OWNER_INIT')
    return verify_database(path)


def identity(runner: int, created_at: datetime, kind: str = 'schedule',
             invocation: str = '') -> dict[str, Any]:
    require(type(runner) is int and 1 <= runner <= 15, 'INVALID_RUNNER')
    require(created_at.tzinfo is not None, 'NAIVE_CREATED_AT')
    require(kind in {'schedule', 'commissioning', 'manual'}, 'INVALID_INVOCATION_KIND')
    minute = created_at.astimezone(UTC).replace(second=0, microsecond=0)
    if kind == 'schedule':
        candidates = [minute - timedelta(minutes=i) for i in range(61)]
        minute = next(t for t in candidates if t.astimezone(ADELAIDE).minute == 4 * (runner - 1))
    else:
        require(bool(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', invocation)), 'INVOCATION_ID_REQUIRED')
    cycle_id = minute.astimezone(ADELAIDE).strftime(f'%Y-%m-%dT%H-%M-CAIRN-{runner:02d}')
    key = sha256_text(canonical_json([EPOCH, minute.isoformat(), runner, kind,
                                     '' if kind == 'schedule' else invocation]))
    return {'cycle_id': cycle_id, 'cycle_key': key, 'runner': f'CAIRN-{runner:02d}',
            'scheduled_at_utc': minute.isoformat(), 'trigger_created_at': created_at.astimezone(UTC).isoformat(),
            'invocation_kind': kind, 'epoch': EPOCH,
            'identity_source': 'ORIGINAL_GITHUB_RUN_CREATED_AT_NOT_RETRY_CLOCK'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Halt('PUBLIC_API_REDIRECT_REJECTED')


ALLOWED = {'/api/v5/public/instruments', '/api/v5/market/ticker',
           '/api/v5/market/books', '/api/v5/market/history-candles'}


def public_get(endpoint: str, params: dict[str, str]) -> list[Any]:
    require(endpoint in ALLOWED, 'NON_PUBLIC_ENDPOINT_FORBIDDEN')
    opener = urllib.request.build_opener(NoRedirect)
    for host in ('https://www.okx.com', 'https://openapi.okx.com'):
        try:
            url = host + endpoint + '?' + urllib.parse.urlencode(params)
            request = urllib.request.Request(url, headers={'Accept': 'application/json',
                                                'User-Agent': 'Cairn-PAPER-only/500'}, method='GET')
            with opener.open(request, timeout=10) as response:
                raw = response.read(5_000_001)
            require(len(raw) <= 5_000_000, 'PUBLIC_RESPONSE_TOO_LARGE')
            p = json.loads(raw)
            require(p.get('code') == '0' and isinstance(p.get('data'), list), 'PUBLIC_API_BAD_STATUS')
            return p['data']
        except Exception:
            continue
    raise Halt('OKX_PUBLIC_DATA_UNAVAILABLE')


def acquire() -> dict[str, Any]:
    symbol = {'instId': 'BTC-USDT'}
    inst = public_get('/api/v5/public/instruments', {'instType': 'SPOT', **symbol})[0]
    candles = public_get('/api/v5/market/history-candles', {**symbol, 'bar': '1H', 'limit': '72'})
    ticker = public_get('/api/v5/market/ticker', symbol)[0]
    book = public_get('/api/v5/market/books', {**symbol, 'sz': '5'})[0]
    return {'source': 'OKX_PUBLIC', 'observed_at': now().isoformat(), 'instrument': inst,
            'candles': candles, 'ticker': ticker, 'book': book}


def validate_market(m: dict[str, Any], clock: datetime) -> dict[str, Any]:
    require(m['source'] == 'OKX_PUBLIC', 'WRONG_MARKET_SOURCE')
    i, t, b = m['instrument'], m['ticker'], m['book']
    require(i['instId'] == t['instId'] == 'BTC-USDT' and i['instType'] == 'SPOT'
            and i['state'] == 'live', 'INVALID_INSTRUMENT')
    ms = int(clock.timestamp() * 1000)
    for p in (t, b):
        require(-2000 <= ms - int(p['ts']) <= 120000, 'STALE_OR_FUTURE_MARKET_DATA')
    for key in ('lotSz', 'minSz', 'tickSz'):
        require(F(i[key]) > 0, 'INVALID_INSTRUMENT_SIZES')
    bids = [(F(x[0]), F(x[1])) for x in b['bids']]
    asks = [(F(x[0]), F(x[1])) for x in b['asks']]
    require(bool(bids) and bool(asks), 'EMPTY_ORDER_BOOK')
    require(all(p > 0 and q > 0 for p, q in bids + asks), 'INVALID_BOOK_LEVEL')
    require(all(bids[j][0] > bids[j+1][0] for j in range(len(bids)-1))
            and all(asks[j][0] < asks[j+1][0] for j in range(len(asks)-1)), 'INVALID_BOOK_ORDER')
    bid, ask = bids[0][0], asks[0][0]
    require(bid < ask and bid % F(i['tickSz']) == 0 and ask % F(i['tickSz']) == 0, 'CROSSED_OR_OFFTICK_BOOK')
    require((ask-bid)/((ask+bid)/2) <= Fraction(20,10000), 'SPREAD_TOO_WIDE')
    rows = sorted([x for x in m['candles'] if len(x) >= 9 and x[8] == '1'], key=lambda x: int(x[0]))
    require(len(rows) >= 25, 'INSUFFICIENT_CANDLES')
    stamps = [int(x[0]) for x in rows]
    require(len(set(stamps)) == len(stamps), 'DUPLICATE_CANDLE')
    require(all(t % 3600000 == 0 for t in stamps)
            and all(y-x == 3600000 for x,y in zip(stamps,stamps[1:])), 'CANDLE_GAP_OR_ALIGNMENT')
    require(stamps[-1] == (ms//3600000-1)*3600000, 'LATEST_COMPLETED_CANDLE_MISSING')
    for row in rows:
        o,h,l,c = map(F, row[1:5])
        require(0 < l <= min(o,c) <= max(o,c) <= h and F(row[5]) >= 0, 'INVALID_OHLCV')
    closes = [float(F(x[4])) for x in rows[-25:]]
    returns = [math.log(y/x) for x,y in zip(closes,closes[1:])]
    depth_b,depth_a = sum((q for p,q in bids),Fraction()), sum((q for p,q in asks),Fraction())
    return {'momentum_24h': D(F(rows[-1][4])/F(rows[-25][4])-1),
            'realized_vol_24h': math.sqrt(sum(x*x for x in returns)),
            'spread_bps': D((ask-bid)/((ask+bid)/2)*10000),
            'depth_imbalance': D((depth_b-depth_a)/(depth_b+depth_a)),
            'regime': 'OBSERVED_LIQUID_SPOT_NOT_PREDICTIVE_ALPHA',
            'ticker_age_ms': ms-int(t['ts']), 'book_age_ms': ms-int(b['ts'])}


def plan_exploration(state: PaperState, m: dict[str, Any]) -> dict[str, Any]:
    i,b = m['instrument'], m['book']
    bid,ask,lot,minimum = F(b['bids'][0][0]),F(b['asks'][0][0]),F(i['lotSz']),F(i['minSz'])
    mark = (bid+ask)/2
    nav = mark_to_market(state, {'BTC-USDT':D(mark)})
    held = state.positions.get('BTC-USDT', Position()).quantity
    require(nav > 0, 'INVALID_NAV')
    if held:
        side,qty,price = 'SELL',held,bid
        reason = 'CONTROLLED_OBSERVATION_EXIT'
    else:
        min_lots = -(-minimum//lot)
        target_lots = max(min_lots, (nav*Fraction(10,10000)/ask)//lot)
        side,qty,price = 'BUY', target_lots*lot,ask
        reason = 'MINIMUM_FEASIBLE_TAKER_EXPERIMENT'
    return {'side':side,'quantity':D(qty),'price':D(price),'mark':D(mark),
            'reason':reason,'experiment_id':'EXP-TOPBOOK-ENTRY-OBSERVATION-EXIT-v1',
            'trade_origin':'exploration','pre_nav':D(nav),'fee':D(qty*price*FEE)}


def independent_risk(state: PaperState, order: dict[str, Any], m: dict[str, Any]) -> dict[str, Any]:
    qty,price,mark,fee = map(F, (order['quantity'],order['price'],order['mark'],order['fee']))
    held = state.positions.get('BTC-USDT', Position()).quantity
    nav = mark_to_market(state, {'BTC-USDT':order['mark']})
    side = order['side']
    require(qty > 0 and qty >= F(m['instrument']['minSz']) and qty % F(m['instrument']['lotSz']) == 0,
            'SIZE_BELOW_MINIMUM_OR_OFFLOT')
    level = m['book']['asks'][0] if side == 'BUY' else m['book']['bids'][0]
    require(price == F(level[0]) and qty <= F(level[1]), 'NOT_EXECUTABLE_AT_OBSERVED_TOP')
    require(fee == qty*price*FEE, 'FEE_MISMATCH')
    if side == 'BUY':
        require(state.cash >= qty*price+fee, 'INSUFFICIENT_CASH')
        postnav = nav + qty*(mark-price)-fee
        postgross = (held+qty)*mark
        require(qty*price <= POSITION_CAP*nav and postnav>0
                and postgross <= POSITION_CAP*postnav and postgross <= SLEEVE_CAP*postnav,
                'NO_FEASIBLE_SIZE_WITHIN_500_USDT_CAPS')
    elif side == 'SELL':
        require(0 < qty <= held, 'SHORT_SELL_FORBIDDEN')
        postnav = nav + qty*(price-mark)-fee
        postgross = (held-qty)*mark
        require(postnav>0 and postgross <= POSITION_CAP*postnav, 'REDUCTION_NOT_WITHIN_CAP')
    else:
        raise Halt('INVALID_SIDE')
    return {'approved':True,'engine':'DETERMINISTIC_INDEPENDENT_RECALCULATION',
            'position_cap_usdt':D(nav*POSITION_CAP),'sleeve_cap_usdt':D(nav*SLEEVE_CAP),
            'post_position_nav':D(postgross/postnav),'reduce_only':side=='SELL',
            'minimum_order_notional':D(F(m['instrument']['minSz'])*price)}


def run_cycle(path: Path, ident: dict[str, Any], market: dict[str, Any] | None,
              code_sha: str, clock: datetime | None = None) -> dict[str, Any]:
    live_clock = clock is None
    clock = clock or now()
    require(bool(re.fullmatch('[0-9a-f]{40}', code_sha)), 'UNPINNED_CODE')
    audit = verify_database(path)
    store = Store(path)
    key = ident['cycle_key']
    previous = store.get_record(key+':report')
    if previous is not None:
        return previous  # No new order, no duplicate audit rows, including after >100 cycles.
    r = {**ident, 'code_sha':code_sha,'config_sha':CONFIG_SHA,'configuration':CONFIG,
         'status':'HALTED','execution_mode':MODE,'simulated_fill':True,'live_order_submitted':False,
         'full_strategy_cycle_completed':False,'scope':'EXPLORATION_EXECUTION_ONLY',
         'minimum_paper_trade_per_cycle_satisfied':False,'stages':{},'fills':[],
         'core':{'orders':0,'fills':0,'sharpe':None,'ic':None,'status':'NO_ACTIVE_CORE_MODEL'},
         'incidents':[],'schedule_action':'NONE','schedule_state_required':'ACTIVE'}
    def stage(name: str, body: dict[str, Any]) -> None:
        r['stages'][name] = {**ident, **body}
    before = audit['state']
    state = decode_state(before)
    new = state
    try:
        require(0 <= (clock-datetime.fromisoformat(ident['trigger_created_at'])).total_seconds() <= 1200,
                'INVOCATION_TOO_LATE_OR_FUTURE')
        stage('health', {'status':'PASS','paper_only_verified':True,'prior_audit_root':audit['audit_root'],
                         'shared_state_sequence':state.sequence,'state_reset':False})
        require(market is not None, 'OKX_PUBLIC_DATA_UNAVAILABLE')
        features = validate_market(market, clock)
        stage('market_data', {'status':'PASS','snapshot':market})
        stage('features', {'status':'PASS',**features})
        stage('signals', {'status':'UNAVAILABLE','reason':'NO_ACTIVE_CORE_MODEL', 'invented_signals':False})
        order = plan_exploration(state,market)
        stage('portfolio', {'status':'PASS','core_target':'UNCHANGED','proposal':order})
        risk = independent_risk(state,order,market)
        stage('risk', {'status':'PASS',**risk})
        # Timestamp freshness is checked immediately before applying the local simulated order.
        if live_clock: validate_market(market, now())
        aid = sha256_text(canonical_json([EPOCH,key,'exploration','BTC-USDT',order['side']]))[:32]
        action = PaperAction(action_id=aid,account_id=EPOCH,idempotency_key=aid,
                             expected_sequence=state.sequence,ts=clock,inst_id='BTC-USDT',
                             side=order['side'],quantity=order['quantity'],price=order['price'],
                             fee=order['fee'],rationale=order['reason'])
        new,receipt = apply_action(state,action)
        qty,price,mark,fee = map(F,(order['quantity'],order['price'],order['mark'],order['fee']))
        expected_qty = state.positions.get('BTC-USDT',Position()).quantity + (qty if order['side']=='BUY' else -qty)
        expected_cash = state.cash + (-qty*price if order['side']=='BUY' else qty*price)-fee
        require(new.cash==expected_cash and new.positions.get('BTC-USDT',Position()).quantity==expected_qty
                and new.sequence==state.sequence+1, 'RECONCILIATION_MISMATCH')
        pre = mark_to_market(state,{'BTC-USDT':order['mark']})
        post = mark_to_market(new,{'BTC-USDT':order['mark']})
        last = from_rational(before['last_nav'])
        peak = max(from_rational(before['peak_nav']),post)
        fill = {**ident,**order,'action_id':aid,'client_order_id':aid,'instrument':'BTC-USDT',
                'fill_quantity':order['quantity'],'fill_price':order['price'],'notional':D(qty*price),
                'simulated_fill':True,'live_order_submitted':False,'execution_mode':MODE,
                'receipt':asdict(receipt),'executed_at':clock.isoformat()}
        stage('execution',{'status':'PASS','fill':fill,'order':action.model_dump(mode='json')})
        stage('execution_quality',{'status':'OBSERVATIONAL','classification':'SIMULATED_TAKER',
                                  'spread_cost':D(qty*abs(price-mark)), 'market_impact_modelled':False,
                                  'maker_queue_modelled':False,'fees_source':'ASSUMED_10_BPS'})
        stage('reconciliation',{'status':'MATCH','broker':'NOT_APPLICABLE_LOCAL_PAPER',
                               'pre_sequence':state.sequence,'post_sequence':new.sequence})
        stage('accounting',{'status':'PASS','previous_checkpoint_nav':D(last),'pre_trade_nav':D(pre),
                           'post_trade_nav':D(post),'intercycle_mark_pnl':D(pre-last),
                           'execution_pnl':D(post-pre),'total_cycle_pnl':D(post-last),
                           'core_pnl':'0','exploration_pnl':D(post-last),'fees':D(fee),
                           'funding':'0','cashflows':'0','cumulative_pnl':D(post-F(INITIAL))})
        stage('attribution',{'status':'LIMITED','core_statistics':None,'reason':'NO_CORE_MODEL',
                            'account_drawdown':D(post/peak-1),'core_fill_count':0,'exploration_fill_count':1})
        stage('monitoring',{'status':'OBSERVATIONAL','anomalies':[], 'alpha_drift_assessed':False})
        stage('research',{'status':'REVIEW_ONLY','hypothesis_id':order['experiment_id'],
                          'new_hypotheses':0,'question':'Measure spread and next-cycle markout of tiny top-of-book entries.'})
        stage('validation',{'status':'NO_STRATEGY_PROMOTION','walk_forward_run':False,
                            'production_strategy_changed':False,'risk_and_accounting_checks':'PASS'})
        r['fills']=[fill]
        r['status']='LOCAL_COMMITTED'
        r['minimum_paper_trade_per_cycle_satisfied']=True
        r['account_after']=encode_state(new,post,peak)
    except Exception as exc:
        r['incidents']=[{'code':str(exc) if isinstance(exc,Halt) else type(exc).__name__,
                         'state_mutated':False}]
        r['account_after']=before
        new=state
    for name in STAGES:
        if name not in r['stages']:
            stage(name,{'status':'BLOCKED','reason':r['incidents'][0]['code'] if r['incidents'] else 'NOT_RUN'})
    r['audit_chain_valid']=True
    r['completed_at']=clock.isoformat()
    r['remote_persistence_verified']=False
    # All fill/stage/report/account effects commit atomically in one transaction.
    with store.transaction() as conn:
        current=conn.execute("SELECT payload_json FROM records WHERE record_type='account_state'").fetchall()
        latest=max((json.loads(x[0]) for x in current),key=lambda s:s['sequence'])
        require(latest==before,'ACCOUNT_CHANGED_RETRY_WITH_FRESH_SNAPSHOT')
        require(conn.execute('SELECT 1 FROM records WHERE record_id=?',(key+':report',)).fetchone() is None,
                'CONCURRENT_CYCLE_ALREADY_COMMITTED')
        for name,payload in r['stages'].items():
            put(store,conn,key+':'+name,name,payload,clock.isoformat(),ident['runner'])
        if r['fills']:
            put(store,conn,key+':fill','paper_fill',r['fills'][0],clock.isoformat(),ident['runner'])
            put(store,conn,key+':state','account_state',r['account_after'],clock.isoformat(),ident['runner'])
        put(store,conn,key+':report','cycle_report',r,clock.isoformat(),ident['runner'])
    verify_database(path)
    require(store.get_record(key+':report')==r,'REPORT_READBACK_FAILED')
    return r


def write_report(folder: Path, report: dict[str, Any]) -> None:
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'cycle-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    fill=report['fills'][0] if report.get('fills') else None
    trade=(f"{fill['side']} {fill['fill_quantity']} {fill['instrument']} @ {fill['fill_price']}; "
           f"notional {fill['notional']} USDT; fee {fill['fee']} USDT; ID {fill['action_id']}") if fill else 'None'
    text=(f"# {report['cycle_id']}\n\nStatus: {report['status']}\n\nEpoch: {EPOCH}; initial capital: 500 USDT.\n\n"
          f"Paper trade: {trade}\n\nMinimum satisfied: {report['minimum_paper_trade_per_cycle_satisfied']}\n\n"
          'Execution: explicitly simulated local paper ledger, not an OKX demo-account fill.\n\n'
          'CORE: unavailable; no investment-edge evaluation or full strategy cycle is claimed.\n\n'
          f"Incidents: {json.dumps(report.get('incidents',[]))}\n\n"
          'Recurring schedules: leave active; completing or halting this cycle never disables workers.\n')
    (folder/'cycle-report.md').write_text(text)
