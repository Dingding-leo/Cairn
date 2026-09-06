"""Durable, long-only SPOT paper bracket ledger. One LOCAL account, many trade lots.

NO NETWORK / NO BROKER ORDERS. A separately running protection process must call
observe continuously. Its heartbeat is an admission gate, not a guarantee of future
uptime. All monetary state and brackets commit atomically. SQLite must be on a
single host's local disk, not synced or copied between independent chat sandboxes.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from fractions import Fraction as F
from hashlib import sha256
from pathlib import Path
from .bracket_policy import (Policy, Instrument, Quote, Bracket, Exposure, Blocked, require,
                             size_bracket, gate, protective_exit, qualifies_for_cycle, entry_id, decimal)

MODE='LOCAL_PAPER_LEDGER'
SCHEMA='''
CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
CREATE TABLE trades(id TEXT PRIMARY KEY,cycle_key TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE cycles(cycle_key TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE fills(id TEXT PRIMARY KEY,trade_id TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE observations(id TEXT PRIMARY KEY,digest TEXT NOT NULL);
CREATE TABLE audit(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,prev_hash TEXT NOT NULL,entry_hash TEXT NOT NULL);
'''

def canon(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def enc(x):
    if isinstance(x,F): return {'n':str(x.numerator),'d':str(x.denominator)}
    if isinstance(x,dict): return {k:enc(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [enc(v) for v in x]
    return x

def dec(x):
    if isinstance(x,dict):
        if set(x)=={'n','d'}: return F(int(x['n']),int(x['d']))
        return {k:dec(v) for k,v in x.items()}
    if isinstance(x,list): return [dec(v) for v in x]
    return x

def dumps(x): return canon(enc(x))
def loads(x): return dec(json.loads(x))

class Ledger:
    def __init__(self,path: str | Path,policy: Policy=Policy()):
        self.path=Path(path).resolve();self.policy=policy
        require(self.path.is_file(),'PERSISTENT_ACCOUNT_MISSING_NO_AUTO_RESET')
        with self.tx() as c:
            require(self.meta(c,'mode')==MODE,'NOT_PAPER_ONLY')
            require(self.meta(c,'policy')==asdict(policy),'POLICY_MIGRATION_REQUIRED')

    @classmethod
    def initialize(cls,path: str | Path,account_id: str,policy: Policy=Policy()):
        path=Path(path).resolve()
        require(not path.exists(),'ACCOUNT_EXISTS_NO_RESET')
        require(bool(account_id),'ACCOUNT_ID_REQUIRED')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb'): pass
        c=sqlite3.connect(path)
        try:
            c.executescript(SCHEMA)
            for k,v in {'mode':MODE,'account_id':account_id,'initial_cash':F(500),'cash':F(500),
                        'fees':F(0),'policy':asdict(policy),'heartbeat_ms':None,
                        'last_quote_ms':None,'recovery_required':False,'day_nav':F(500),
                        'day_key':None}.items():
                c.execute('INSERT INTO meta VALUES(?,?)',(k,dumps(v)))
            cls.append(c,'GENESIS',{'initial_cash':F(500),'account_id':account_id,'mode':MODE,'policy':asdict(policy)})
            c.commit()
        finally: c.close()
        return cls(path,policy)

    @contextmanager
    def tx(self):
        c=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=10)
        c.execute('PRAGMA synchronous=FULL'); c.execute('BEGIN IMMEDIATE')
        try: yield c; c.commit()
        except BaseException: c.rollback(); raise
        finally: c.close()

    @staticmethod
    def meta(c,key):
        row=c.execute('SELECT v FROM meta WHERE k=?',(key,)).fetchone()
        require(row is not None,'METADATA_MISSING')
        return loads(row[0])
    @staticmethod
    def setmeta(c,key,v): c.execute('UPDATE meta SET v=? WHERE k=?',(dumps(v),key))
    @staticmethod
    def append(c,kind,payload):
        row=c.execute('SELECT seq,entry_hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        seq,prev=(row[0]+1,row[1]) if row else (0,'0'*64)
        raw=dumps(payload); digest=sha256(canon([seq,kind,raw,prev]).encode()).hexdigest()
        c.execute('INSERT INTO audit VALUES(?,?,?,?,?)',(seq,kind,raw,prev,digest))
    @staticmethod
    def trades(c,open_only=True):
        items=[loads(x[0]) for x in c.execute('SELECT payload FROM trades ORDER BY rowid')]
        return [t for t in items if t['remaining']>0] if open_only else items

    def state(self,quote: Quote):
        with self.tx() as c:
            ts=self.trades(c);mark=(quote.bid+quote.ask)/2
            cash=self.meta(c,'cash')
            return {'cash':cash,'nav':cash+sum((t['remaining']*mark for t in ts),F(0)),
                    'open_trade_count':len(ts),'open_quantity':sum((t['remaining'] for t in ts),F(0)),
                    'original_open_risk':sum((t['bracket']['planned_risk'] for t in ts),F(0)),
                    'fees':self.meta(c,'fees'),'recovery_required':self.meta(c,'recovery_required')}

    def enter(self,cycle_key:str,cycle_id:str,strategy:str,origin:str,experiment:str,
              stop:F,quote:Quote,instrument:Instrument,now_ms:int,day_key:str):
        require(cycle_key and cycle_id and strategy and day_key,'MISSING_CYCLE_IDENTITY')
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        actual_day=datetime.fromtimestamp(now_ms/1000,timezone.utc).astimezone(ZoneInfo('Australia/Adelaide')).date().isoformat()
        require(day_key==actual_day,'DAY_KEY_MISMATCH')
        require(origin in {'core','exploration'} and (origin!='exploration' or experiment),'INVALID_TRADE_ORIGIN')
        with self.tx() as c:
            old=c.execute('SELECT payload FROM cycles WHERE cycle_key=?',(cycle_key,)).fetchone()
            request=[strategy,origin,experiment,instrument.symbol]
            if old:
                result=loads(old[0]);require(result['request']==request,'CYCLE_INTENT_CONFLICT')
                return result
            require(not self.meta(c,'recovery_required'),'UNRESOLVED_PROTECTION_GAP')
            ts=self.trades(c);mark=(quote.bid+quote.ask)/2;cash=self.meta(c,'cash')
            nav=cash+sum((t['remaining']*mark for t in ts),F(0))
            if self.meta(c,'day_key')!=day_key:
                self.setmeta(c,'day_key',day_key);self.setmeta(c,'day_nav',nav)
            require(not any(t['latched'] for t in ts),'PROTECTIVE_EXIT_PENDING')
            exposure=Exposure(cash,sum((t['remaining']*mark for t in ts),F(0)),
                              sum((t['bracket']['planned_risk'] for t in ts),F(0)),len(ts),self.meta(c,'day_nav'))
            b=size_bracket(nav,quote.ask,stop,instrument,self.policy)
            gate(b,exposure,quote,now_ms,self.meta(c,'heartbeat_ms'),instrument,self.policy)
            prior=[loads(x[0]) for x in c.execute('SELECT payload FROM fills')]
            used=sum((f['qty'] for f in prior if f['quote_id']==quote.quote_id and f['effect']=='OPEN'),F(0))
            require(used+b.quantity<=quote.ask_quantity,'OBSERVED_ASK_LIQUIDITY_ALREADY_USED')
            tradeid=entry_id(cycle_key,strategy,instrument.symbol,origin)
            trade={'id':tradeid,'cycle_id':cycle_id,'cycle_key':cycle_key,'strategy':strategy,'origin':origin,
                   'experiment':experiment,'instrument':instrument.symbol,'lot':instrument.lot,
                   'bracket':asdict(b),'remaining':b.quantity,'latched':None,'status':'ARMED',
                   'opened_at_ms':now_ms,'realized_pnl':F(0)}
            fill={'id':tradeid+':entry','trade_id':tradeid,'quote_id':quote.quote_id,'effect':'OPEN',
                  'qty':b.quantity,'price':b.entry,'fee':b.entry_fee,'cash_delta':-b.notional-b.entry_fee,
                  'cycle_id':cycle_id,'cycle_key':cycle_key,'trade_origin':origin,'position_effect':'OPEN',
                  'entry_order_id':tradeid,'fill_id':tradeid+':entry','quantity':decimal(b.quantity),
                  'filled_planned_risk':decimal(b.planned_risk),'nav_at_entry':decimal(nav),
                  'bracket_armed':True,'simulated_fill':True,'live_order_submitted':False,'execution_mode':MODE}
            result={'cycle_key':cycle_key,'cycle_id':cycle_id,'request':request,'trade_id':tradeid,
                    'status':'ENTRY_RECORDED','new_entry_fill_count':1,'protection_status':'ARMED',
                    'minimum_new_entry_satisfied':qualifies_for_cycle(cycle_key,[fill],self.policy),
                    'fill':fill,'bracket':b.report(),'full_strategy_cycle_completed':False,'scope':'BRACKET_EXECUTION_COMPONENT_ONLY'}
            require(result['minimum_new_entry_satisfied'],'NEW_ENTRY_ACCEPTANCE_FAILURE')
            c.execute('INSERT INTO trades VALUES(?,?,?)',(tradeid,cycle_key,dumps(trade)))
            c.execute('INSERT INTO fills VALUES(?,?,?)',(fill['id'],tradeid,dumps(fill)))
            c.execute('INSERT INTO cycles VALUES(?,?)',(cycle_key,dumps(result)))
            self.setmeta(c,'cash',cash+fill['cash_delta']);self.setmeta(c,'fees',self.meta(c,'fees')+fill['fee'])
            self.append(c,'OPEN_WITH_BRACKET',{'trade':trade,'fill':fill,'cycle':result})
            return result

    def observe(self,quote:Quote,instrument:Instrument,now_ms:int):
        quote.validate(now_ms,self.policy)
        with self.tx() as c:
            ts=self.trades(c)
            last=self.meta(c,'heartbeat_ms')
            if ts and (last is None or now_ms-last>self.policy.watcher_max_age_s*1000):
                if not self.meta(c,'recovery_required'):
                    self.setmeta(c,'recovery_required',True)
                    self.append(c,'PROTECTION_OBSERVATION_GAP',{'at_ms':now_ms,'last_ms':last})
            fingerprint=sha256(dumps(asdict(quote)).encode()).hexdigest()
            prior=c.execute('SELECT digest FROM observations WHERE id=?',(quote.quote_id,)).fetchone()
            if prior:
                require(prior[0]==fingerprint,'QUOTE_ID_PAYLOAD_CONFLICT')
                self.setmeta(c,'heartbeat_ms',now_ms)
                return []
            last_quote=self.meta(c,'last_quote_ms')
            require(last_quote is None or quote.observed_at_ms>=last_quote,'OUT_OF_ORDER_QUOTE')
            available=quote.bid_quantity;exits=[]
            for t in ts:
                b=Bracket(**t['bracket'])
                d=protective_exit(b,t['remaining'],quote,now_ms,instrument,self.policy,t['latched'],available)
                if d.reason is None: continue
                t['latched']=d.reason;t['status']='EXIT_PENDING'
                if d.quantity>0:
                    exitid=sha256((t['id']+'|'+quote.quote_id+'|CLOSE').encode()).hexdigest()[:32]
                    fee=d.quantity*d.fill_price*self.policy.exit_fee_rate
                    delta=d.quantity*d.fill_price-fee
                    pnl=delta-d.quantity*b.entry*(1+self.policy.entry_fee_rate)
                    fill={'id':exitid,'trade_id':t['id'],'quote_id':quote.quote_id,'effect':'CLOSE',
                          'qty':d.quantity,'price':d.fill_price,'fee':fee,'cash_delta':delta,
                          'cycle_id':t['cycle_id'],'cycle_key':t['cycle_key'],'trade_origin':t['origin'],
                          'position_effect':'CLOSE','reason':d.reason,'realized_pnl':pnl,
                          'simulated_fill':True,'live_order_submitted':False,'execution_mode':MODE}
                    c.execute('INSERT INTO fills VALUES(?,?,?)',(exitid,t['id'],dumps(fill)))
                    self.setmeta(c,'cash',self.meta(c,'cash')+delta);self.setmeta(c,'fees',self.meta(c,'fees')+fee)
                    t['remaining']-=d.quantity;t['realized_pnl']+=pnl;available-=d.quantity
                    exits.append(fill)
                if t['remaining']==0:
                    t['status']='CLOSED';t['sibling_exit_cancelled']=True
                c.execute('UPDATE trades SET payload=? WHERE id=?',(dumps(t),t['id']))
                self.append(c,'PROTECTIVE_EXIT',{'trade':t,'fill':exits[-1] if d.quantity>0 else None,
                                              'at_ms':now_ms,'partial_or_pending':t['remaining']>0})
            c.execute('INSERT INTO observations VALUES(?,?)',(quote.quote_id,fingerprint))
            self.setmeta(c,'last_quote_ms',quote.observed_at_ms);self.setmeta(c,'heartbeat_ms',now_ms)
            return exits

    def verify(self):
        with self.tx() as c:
            require(c.execute('PRAGMA quick_check').fetchone()[0]=='ok','SQLITE_CORRUPT')
            prev='0'*64;expected_trades={};expected_fills={};expected_cycles={}
            cash=F(0);fees=F(0)
            for expected_seq,row in enumerate(c.execute('SELECT seq,kind,payload,prev_hash,entry_hash FROM audit ORDER BY seq')):
                seq,kind,raw,old,hashed=row
                require(seq==expected_seq and old==prev and
                        sha256(canon([seq,kind,raw,old]).encode()).hexdigest()==hashed,'AUDIT_CHAIN_INVALID')
                prev=hashed;event=loads(raw)
                if kind=='GENESIS':
                    cash=event['initial_cash']
                    require(event['mode']==self.meta(c,'mode') and event['account_id']==self.meta(c,'account_id')
                            and event['policy']==self.meta(c,'policy') and cash==self.meta(c,'initial_cash'), 'GENESIS_MISMATCH')
                if 'trade' in event: expected_trades[event['trade']['id']]=event['trade']
                if event.get('fill'):
                    f=event['fill'];require(f['id'] not in expected_fills,'DUPLICATE_FILL')
                    expected_fills[f['id']]=f;cash+=f['cash_delta'];fees+=f['fee']
                if event.get('cycle'): expected_cycles[event['cycle']['cycle_key']]=event['cycle']
            require(expected_trades=={t['id']:t for t in self.trades(c,False)},'TRADE_REPLAY_MISMATCH')
            require(expected_fills=={loads(x[0])['id']:loads(x[0]) for x in c.execute('SELECT payload FROM fills')},'FILL_REPLAY_MISMATCH')
            require(expected_cycles=={loads(x[0])['cycle_key']:loads(x[0]) for x in c.execute('SELECT payload FROM cycles')},'CYCLE_REPLAY_MISMATCH')
            require(cash==self.meta(c,'cash') and fees==self.meta(c,'fees'),'CASH_OR_FEE_REPLAY_MISMATCH')
            return {'audit_chain_valid':True,'reconciled':True,'cash':decimal(cash),'fees':decimal(fees),
                    'recorded_entry_cycles':len(expected_cycles),'fills':len(expected_fills),
                    'open_trades':sum(t['remaining']>0 for t in expected_trades.values()),'audit_root':prev}
