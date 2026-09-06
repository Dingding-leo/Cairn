"""Opt-in LOCAL runtime: public OKX data + resident guardian + bracketed PAPER entries.

Not an authenticated OKX demo account; not a live broker; not a CORE alpha model.
No remote-control endpoint is exposed. A scheduled task must genuinely be able to
invoke this CLI on the SAME host and directory. No GitHub Actions or paid API.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path
from zoneinfo import ZoneInfo
from .bracket_policy import Instrument, Quote, Blocked, require, number, decimal
from .bracket_ledger import Ledger, dumps, loads

UTC=timezone.utc
ADELAIDE=ZoneInfo('Australia/Adelaide')
ALLOWED={'/api/v5/public/instruments','/api/v5/market/books','/api/v5/market/history-candles'}
EXPERIMENT='EXP-LONG-BRACKET-ATR14-SAMPLING-v1'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise Blocked('HTTP_REDIRECT_FORBIDDEN')

def public_get(path,params):
    require(path in ALLOWED,'PRIVATE_OR_UNAPPROVED_ENDPOINT_FORBIDDEN')
    url='https://www.okx.com'+path+'?'+urllib.parse.urlencode(params)
    request=urllib.request.Request(url,method='GET',headers={'Accept':'application/json','User-Agent':'Cairn-local-paper/1'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=3) as response:
        raw=response.read(2_000_001)
    require(len(raw)<=2_000_000,'OVERSIZE_PUBLIC_RESPONSE')
    data=json.loads(raw)
    require(data.get('code')=='0' and isinstance(data.get('data'),list),'PUBLIC_API_ERROR')
    return data['data']

def instrument():
    rows=public_get('/api/v5/public/instruments',{'instType':'SPOT','instId':'BTC-USDT'})
    require(len(rows)==1 and rows[0]['state']=='live' and rows[0]['instId']=='BTC-USDT','INVALID_INSTRUMENT')
    r=rows[0]
    return Instrument('BTC-USDT',number(r['lotSz']),number(r['tickSz']),number(r['minSz'])),r

def quote():
    rows=public_get('/api/v5/market/books',{'instId':'BTC-USDT','sz':'5'})
    require(len(rows)==1,'BOOK_MISSING')
    b=rows[0];require(b.get('bids') and b.get('asks'),'EMPTY_BOOK')
    q=Quote(number(b['bids'][0][0]),number(b['asks'][0][0]),number(b['bids'][0][1]),number(b['asks'][0][1]),
            int(b['ts']),hashlib.sha256(json.dumps(b,sort_keys=True).encode()).hexdigest())
    return q,b

def features(rows,now_ms):
    confirmed=sorted((r for r in rows if len(r)>=9 and r[8]=='1'),key=lambda r:int(r[0]))
    require(len(confirmed)>=25,'INSUFFICIENT_CONFIRMED_1H_BARS')
    stamps=[int(r[0]) for r in confirmed]
    require(len(set(stamps))==len(stamps) and all(b-a==3600000 for a,b in zip(stamps,stamps[1:])), 'CANDLE_GAP_OR_DUPLICATE')
    require(all(s%3600000==0 for s in stamps) and stamps[-1]==(now_ms//3600000-1)*3600000,'CANDLE_ALIGNMENT_OR_FRESHNESS')
    true_ranges=[];prev=None
    for r in confirmed:
        o,h,l,c=map(number,r[1:5])
        require(0<l<=min(o,c)<=max(o,c)<=h and number(r[5])>=0,'INVALID_CANDLE')
        if prev is not None:true_ranges.append(max(h-l,abs(h-prev),abs(l-prev)))
        prev=c
    atr=sum(true_ranges[-14:],F(0))/14
    return {'atr14_arithmetic_mean':atr,'momentum_24h':number(confirmed[-1][4])/number(confirmed[-25][4])-1,
            'latest_confirmed_bar_ms':stamps[-1],'source':'VALIDATED_1H_OHLCV','predictive_alpha_claimed':False}

def cycle_identity(runner,scheduled_at):
    require(1<=runner<=15,'INVALID_RUNNER')
    dt=datetime.fromisoformat(scheduled_at.replace('Z','+00:00'))
    require(dt.tzinfo is not None,'TIMEZONE_REQUIRED')
    local=dt.astimezone(ADELAIDE)
    require(local.minute==4*(runner-1) and local.second==0 and local.microsecond==0,'WRONG_HOURLY_SLOT')
    cid=local.strftime(f'%Y-%m-%dT%H-%M-CAIRN-{runner:02d}')
    key=hashlib.sha256((dt.astimezone(UTC).isoformat()+f'|CAIRN-{runner:02d}|bracket-v1').encode()).hexdigest()
    return cid,key,dt

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    with temp.open('w') as f:
        f.write(dumps(data)+'\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    require(loads(path.read_text())==data,'REPORT_READBACK_FAILURE')

def execute(home:Path,runner:int,scheduled_at:str):
    cid,key,scheduled=cycle_identity(runner,scheduled_at)
    home=home.expanduser().resolve();db=home/'ledger.sqlite3';out=home/'reports'/key
    ledger=Ledger(db)
    cached=out/'cycle-report.json'
    if cached.is_file():
        ledger.verify()
        return loads(cached.read_text())
    report={'cycle_id':cid,'cycle_key':key,'runner':runner,'scheduled_at_utc':scheduled.astimezone(UTC).isoformat(),
            'mode':'LOCAL_PAPER_LEDGER','simulated_fill':True,'live_order_submitted':False,
            'full_strategy_cycle_completed':False,'core_status':'NO_ACTIVE_CORE_MODEL',
            'minimum_new_entry_satisfied':False,'status':'HALTED','stages':{},'schedule_action':'NONE'}
    try:
        ledger.verify();report['stages']['health']='PASS'
        with ledger.tx() as c:
            existing=c.execute('SELECT payload FROM cycles WHERE cycle_key=?',(key,)).fetchone()
        if existing:
            result=loads(existing[0]);report['entry']=result;report['recovered_existing_entry']=True
        else:
            require(0<=(datetime.now(UTC)-scheduled).total_seconds()<=1200,'STALE_OR_FUTURE_CYCLE')
            ins,meta=instrument()
            bars=public_get('/api/v5/market/history-candles',{'instId':'BTC-USDT','bar':'1H','limit':'40'})
            feat=features(bars,int(time.time()*1000))
            q,book=quote();now_ms=int(time.time()*1000)
            report['market_snapshot']={'instrument':meta,'book':book,'candles':bars}
            report['features']=feat
            report['stages']['data']='PASS';report['stages']['features']='PASS'
            distance=max(F('1.5')*feat['atr14_arithmetic_mean'],F('0.01')*q.ask)
            stop=q.ask-distance
            day=datetime.now(UTC).astimezone(ADELAIDE).date().isoformat()
            result=ledger.enter(key,cid,EXPERIMENT,'exploration',EXPERIMENT,stop,q,ins,now_ms,day)
            report['entry']=result
        report['verification']=ledger.verify()
        report['minimum_new_entry_satisfied']=result['minimum_new_entry_satisfied']
        report['status']='PAPER_ENTRY_COMMITTED'
        report['stages'].update({'signals':'CORE_UNAVAILABLE_EXPLORATION_ONLY','portfolio':'NEW_INDEPENDENT_LOT',
             'risk':'PASS','execution':'SIMULATED_FULL_ENTRY','protection':'TP_AND_SL_ATOMICALLY_ARMED',
             'reconciliation':'PASS','accounting':'EXACT_LEDGER_REPLAY','attribution':'CORE_AND_EXPLORATION_SEPARATE',
             'research':'REGISTERED_EXPERIMENT_ONLY','adversarial_validation':'NO_STRATEGY_PROMOTION'})
    except Exception as e:
        report['blocker']=str(e) if isinstance(e,Blocked) else type(e).__name__
        with ledger.tx() as c:
            ledger.append(c,'BLOCKED_ATTEMPT',{'cycle_id':cid,'cycle_key':key,'reason':report['blocker'],
                                             'at_ms':int(time.time()*1000)})
    report['recorded_at_utc']=datetime.now(UTC).isoformat()
    save(out/'cycle-report.json',report)
    text=(f"# {cid}\n\nStatus: {report['status']}\n\n"
          f"New-entry requirement satisfied: {report['minimum_new_entry_satisfied']}\n\n"
          "CORE is unavailable. This is explicitly simulated paper execution, not a full alpha research cycle.\n\n"
          "Protective exits require the resident guardian to stay running on this host.\n\n"
          f"Blocker: {report.get('blocker','none')}\n")
    (out/'cycle-report.md').write_text(text)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',default=str(Path.home()/'.local/share/cairn/bracket500'))
    sub=parser.add_subparsers(dest='cmd',required=True)
    ini=sub.add_parser('init');ini.add_argument('--account-id',required=True)
    ini.add_argument('--ack-new-account-not-migration',action='store_true',required=True)
    sub.add_parser('guardian');sub.add_parser('verify')
    cyc=sub.add_parser('cycle');cyc.add_argument('--runner',type=int,required=True);cyc.add_argument('--scheduled-at',required=True)
    args=parser.parse_args();home=Path(args.home).expanduser().resolve()
    if args.cmd=='init':
        l=Ledger.initialize(home/'ledger.sqlite3',args.account_id);os.chmod(home/'ledger.sqlite3',0o600)
        print(dumps(l.verify()));return
    if args.cmd=='verify':print(dumps(Ledger(home/'ledger.sqlite3').verify()));return
    if args.cmd=='cycle':
        r=execute(home,args.runner,args.scheduled_at);print(dumps(r))
        raise SystemExit(0 if r['minimum_new_entry_satisfied'] else 2)
    ledger=Ledger(home/'ledger.sqlite3');ledger.verify();ins,_=instrument()
    refresh=time.monotonic()
    while True:
        started=time.monotonic()
        try:
            if started-refresh>=3600:ins,_=instrument();refresh=started
            q,_=quote();events=ledger.observe(q,ins,int(time.time()*1000))
            if events:print(dumps({'protective_fills':events,'verification':ledger.verify()}),flush=True)
        except KeyboardInterrupt:return
        except Exception as e:
            code=str(e) if isinstance(e,Blocked) else type(e).__name__
            save(home/'guardian-health.json',{'status':'DEGRADED','reason':code,'at_ms':int(time.time()*1000)})
            print(dumps({'guardian_error':code}),flush=True)
        time.sleep(max(0,1-(time.monotonic()-started)))

if __name__=='__main__':main()
