"""Synthetic regression fixtures ONLY. These are never forward paper observations."""
import copy
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest

from cairn import paper500 as p
from cairn.paper import PaperState, Position

T = datetime(2026,9,6,13,0,tzinfo=timezone.utc)
SHA = 'a'*40

@pytest.fixture
def market():
    ms=int(T.timestamp()*1000)
    candles=[[str(ms-j*3600000),'80000','80001','79999','80000','100','100','100','1']
             for j in range(1,30)]
    return {'source':'OKX_PUBLIC','instrument':{'instId':'BTC-USDT','instType':'SPOT','state':'live',
             'lotSz':'0.00000001','minSz':'0.00001','tickSz':'0.1'},
            'ticker':{'instId':'BTC-USDT','ts':str(ms-100)},
            'book':{'ts':str(ms-100),'bids':[['79999.9','1'],['79999.8','2']],
                    'asks':[['80000.1','1'],['80000.2','2']]},'candles':candles}

@pytest.fixture
def db(tmp_path):
    path=tmp_path/'state.sqlite3'
    p.initialize(path)
    return path


def ident(n=1, label='test'):
    return p.identity(n,T,'commissioning',label)


def test_capital_epoch_and_no_implicit_reset(db,tmp_path):
    s=p.decode_state(p.verify_database(db)['state'])
    assert s.cash==500 and s.sequence==0 and not s.positions
    with pytest.raises(p.Halt,match='REFUSES_OVERWRITE'): p.initialize(db)
    with pytest.raises(p.Halt,match='NO_AUTO_RESET'): p.run_cycle(tmp_path/'missing',ident(),None,SHA,T)
    assert not (tmp_path/'missing').exists()


def test_forward_local_cycle_then_exit(db,market):
    first=p.run_cycle(db,ident(),market,SHA,T)
    assert first['status']=='LOCAL_COMMITTED'
    fill=first['fills'][0]
    assert fill['side']=='BUY' and Fraction(fill['notional'])<=Fraction('1.25')
    assert Fraction(fill['fill_quantity'])>=Fraction('0.00001')
    assert first['full_strategy_cycle_completed'] is False
    second=p.run_cycle(db,ident(2),market,SHA,T)
    assert second['fills'][0]['side']=='SELL'
    assert p.decode_state(second['account_after']).positions=={}
    assert p.decode_state(second['account_after']).cash<500
    assert p.verify_database(db)['audit_chain_valid']
    assert first['remote_persistence_verified'] is False


@pytest.mark.parametrize('n',range(1,16))
def test_all_worker_identities_have_correct_hourly_offset(n):
    value=p.identity(n,T)
    local=datetime.fromisoformat(value['scheduled_at_utc']).astimezone(p.ADELAIDE)
    assert local.minute==4*(n-1)
    assert value['runner']==f'CAIRN-{n:02d}'
    assert value==p.identity(n,T.astimezone(p.ADELAIDE))


def test_retry_does_not_retrade_or_duplicate_records(db,market):
    one=p.run_cycle(db,ident(),market,SHA,T)
    raw=db.read_bytes()
    assert p.run_cycle(db,ident(),None,SHA,T+timedelta(hours=5))==one
    assert db.read_bytes()==raw


def test_all_15_workers_share_one_account(db,market):
    for i in range(1,16):
        r=p.run_cycle(db,ident(i),market,SHA,T)
        assert r['minimum_paper_trade_per_cycle_satisfied']
        assert p.decode_state(r['account_after']).sequence==i
    assert p.verify_database(db)['state']['sequence']==15


@pytest.mark.parametrize('attack', ['stale','future','gaps','duplicate','partial','offtick',
                                  'negative','wide','unordered','minsize','book_size','wrong_symbol'])
def test_invalid_market_or_order_halts_without_mutating_account(db,market,attack):
    if attack=='stale': market['ticker']['ts']=str(int(T.timestamp()*1000)-120001)
    if attack=='future': market['book']['ts']=str(int(T.timestamp()*1000)+2001)
    if attack=='gaps': market['candles'].pop(4)
    if attack=='duplicate': market['candles'].append(copy.deepcopy(market['candles'][5]))
    if attack=='partial': market['candles'][0][8]='0'
    if attack=='offtick': market['book']['asks'][0][0]='80000.11'
    if attack=='negative': market['book']['bids'][0][1]='-1'
    if attack=='wide': market['book']['asks']=[['82000','1']]
    if attack=='unordered': market['book']['asks'].reverse()
    if attack=='minsize': market['instrument']['minSz']='0.0001'
    if attack=='book_size': market['book']['asks'][0][1]='0.000001'
    if attack=='wrong_symbol': market['ticker']['instId']='ETH-USDT'
    old=p.verify_database(db)['state']
    r=p.run_cycle(db,ident(),market,SHA,T)
    assert r['status']=='HALTED' and not r['fills']
    assert p.verify_database(db)['state']==old
    assert r['schedule_action']=='NONE' and r['schedule_state_required']=='ACTIVE'
    assert p.run_cycle(db,ident(),market,SHA,T)==r


def test_intracycle_and_intercycle_pnl_accounted(db,market):
    a=p.run_cycle(db,ident(),market,SHA,T)
    market['book']['bids']=[['80999.9','1']]
    market['book']['asks']=[['81000.1','1']]
    b=p.run_cycle(db,ident(2),market,SHA,T)
    acct=b['stages']['accounting']
    assert Fraction(acct['intercycle_mark_pnl'])>0
    assert Fraction(acct['total_cycle_pnl'])==Fraction(acct['intercycle_mark_pnl'])+Fraction(acct['execution_pnl'])
    assert Fraction(acct['previous_checkpoint_nav'])==Fraction(a['stages']['accounting']['post_trade_nav'])


def test_record_tamper_detected_even_when_chain_itself_unchanged(db):
    with sqlite3.connect(db) as conn:
        row=conn.execute("SELECT payload_json FROM records WHERE record_type='account_state'").fetchone()
        value=json.loads(row[0]); value['cash']=['100000','1']
        conn.execute('UPDATE records SET payload_json=?',(json.dumps(value),))
    with pytest.raises(p.Halt,match='RECORD_HASH_MISMATCH'): p.verify_database(db)


def test_wrong_epoch_and_config_rejected(db):
    with sqlite3.connect(db) as conn: conn.execute("UPDATE meta SET value='old-100k' WHERE key='paper_epoch'")
    with pytest.raises(p.Halt,match='EPOCH_OR_CONFIG'): p.verify_database(db)


def test_sequence_and_rational_exactness(db,market):
    state=p.PaperState(0,Fraction(1,3),{'BTC-USDT':Position(Fraction(1,7),Fraction(1,11))})
    encoded=p.encode_state(state,Fraction(3,7),Fraction(4,7))
    assert p.decode_state(encoded)==state
    assert p.from_rational(encoded['last_nav'])==Fraction(3,7)


def test_shared_cap_and_per_position_cap_are_different(market):
    state=p.create_account('500')
    order=p.plan_exploration(state,market)
    risk=p.independent_risk(state,order,market)
    assert risk['position_cap_usdt']=='1.250000000000000000'
    assert risk['sleeve_cap_usdt']=='2.500000000000000000'
    order['quantity']='0.00002'; order['fee']=p.D(Fraction(order['quantity'])*Fraction(order['price'])*p.FEE)
    with pytest.raises(p.Halt,match='NO_FEASIBLE_SIZE'): p.independent_risk(state,order,market)


def test_private_order_endpoint_never_contacted():
    with pytest.raises(p.Halt,match='FORBIDDEN'): p.public_get('/api/v5/trade/order',{})


def test_wrong_origin_no_silent_exploration_conversion(db):
    value=p.verify_database(db)['state']
    value['positions']={'BTC-USDT':{'quantity':['1','1'],'cost_basis':['1','1'],'trade_origin':'core'}}
    with pytest.raises(p.Halt,match='FOREIGN_POSITION'): p.decode_state(value)


def test_old_invocation_is_not_backfilled_with_current_market(db,market):
    r=p.run_cycle(db,ident(),market,SHA,T+timedelta(minutes=21))
    assert r['status']=='HALTED' and r['incidents'][0]['code']=='INVOCATION_TOO_LATE_OR_FUTURE'


def test_dst_fold_disambiguation():
    a=datetime(2026,4,5,2,0,tzinfo=p.ADELAIDE,fold=0)
    b=datetime(2026,4,5,2,0,tzinfo=p.ADELAIDE,fold=1)
    assert p.identity(1,a)['cycle_id']==p.identity(1,b)['cycle_id']
    assert p.identity(1,a)['cycle_key']!=p.identity(1,b)['cycle_key']


def test_atomic_rollback_on_report_commit_failure(db,market,monkeypatch):
    original=p.put
    def broken(store,conn,key,kind,*args):
        if kind=='cycle_report': raise sqlite3.OperationalError('test disk failure')
        return original(store,conn,key,kind,*args)
    monkeypatch.setattr(p,'put',broken)
    with pytest.raises(sqlite3.OperationalError): p.run_cycle(db,ident(),market,SHA,T)
    assert p.verify_database(db)['state']['sequence']==0
    assert p.Store(db).records('paper_fill')==[]


def test_new_capital_not_scaled_historical_pnl(db):
    s=p.verify_database(db)['state']
    assert p.from_rational(s['last_nav'])==500
    assert p.from_rational(s['cash'])==500 and s['sequence']==0


def test_idempotency_survives_more_than_100_cycles(db,market):
    old=p.run_cycle(db,ident(1,'original'),market,SHA,T)
    for i in range(101): p.run_cycle(db,ident(1,'later'+str(i)),market,SHA,T)
    before=p.verify_database(db)
    assert p.run_cycle(db,ident(1,'original'),None,SHA,T)==old
    assert p.verify_database(db)==before


def test_two_simultaneous_invocations_cannot_double_fill(db,market):
    from concurrent.futures import ThreadPoolExecutor
    def execute():
        try: return p.run_cycle(db,ident(),market,SHA,T)
        except p.Halt as error: return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:execute(),range(2)))
    assert any(isinstance(x,dict) and x['status']=='LOCAL_COMMITTED' for x in outcomes)
    assert p.verify_database(db)['state']['sequence']==1
    assert len(p.Store(db).records('paper_fill'))==1


def test_machine_and_human_reports_match_saved_evidence(db,market,tmp_path):
    r=p.run_cycle(db,ident(),market,SHA,T)
    p.write_report(tmp_path/'report',r)
    assert json.loads((tmp_path/'report/cycle-report.json').read_text())==r
    assert r['fills'][0]['action_id'] in (tmp_path/'report/cycle-report.md').read_text()
    halted=p.run_cycle(db,ident(2),None,SHA,T)
    p.write_report(tmp_path/'halted',halted)
    assert 'HALTED' in (tmp_path/'halted/cycle-report.md').read_text()


def test_public_reader_uses_only_get_and_bounded_responses(monkeypatch):
    import io
    requests=[]
    class Opener:
        def open(self,request,timeout):
            requests.append(request)
            return io.BytesIO(b'{"code":"0","data":[{"ok":true}]}')
    monkeypatch.setattr(p.urllib.request,'build_opener',lambda _:Opener())
    assert p.public_get('/api/v5/market/ticker',{'instId':'BTC-USDT'})==[{'ok':True}]
    assert all(r.get_method()=='GET' and r.data is None for r in requests)


def test_public_reader_failure_does_not_invent_data(monkeypatch):
    class Opener:
        def open(self,*args,**kwargs): raise TimeoutError('fixture')
    monkeypatch.setattr(p.urllib.request,'build_opener',lambda _:Opener())
    with pytest.raises(p.Halt,match='UNAVAILABLE'):p.public_get('/api/v5/market/ticker',{})


def test_redirects_rejected():
    with pytest.raises(p.Halt,match='REDIRECT_REJECTED'):
        p.NoRedirect().redirect_request(None,None,302,'',{},'https://invalid.test')


def test_acquisition_is_public_only(monkeypatch):
    calls=[]
    def get(endpoint,params):
        calls.append(endpoint)
        return [{'endpoint':endpoint}]
    monkeypatch.setattr(p,'public_get',get)
    result=p.acquire()
    assert result['source']=='OKX_PUBLIC'
    assert len(calls)==4 and all(x in p.ALLOWED for x in calls)
