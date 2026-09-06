"""Offline test fixtures, not trading results or observed uptime."""
from datetime import timedelta
from pathlib import Path
import importlib.util

spec=importlib.util.spec_from_file_location('monitor',Path(__file__).parents[1]/'scripts'/'cairn_continuity_monitor.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def workflows():
    return [{'id':i,'name':f'CAIRN-{i:02d} Full Paper Cycle (500 USDT)','state':'active'} for i in range(1,16)]


def test_commissioning_is_never_scheduled_proof():
    runs=[{'name':w['name'],'event':'push','head_branch':'main','created_at':m.ACTIVATED_AT.isoformat(),
           'conclusion':'success','status':'completed'} for w in workflows()]
    r=m.analyse(workflows(),runs,m.ACTIVATED_AT+timedelta(hours=2),[])
    assert r['scheduled_workers_seen']==0 and r['status']=='DEGRADED'
    assert all(w['missing_slots'] for w in r['workers'])


def test_grace_period_is_not_claimed_as_healthy_recurrence():
    r=m.analyse(workflows(),[],m.ACTIVATED_AT+timedelta(minutes=10),[])
    assert r['status']=='WARMING_UP' and r['due_slots']==0


def test_failure_of_one_worker_prevents_global_pass():
    ws=workflows();ws[-1]['state']='disabled_manually'
    r=m.analyse(ws,[],m.ACTIVATED_AT+timedelta(minutes=1),[])
    assert r['active_workers']==14 and r['status']=='DEGRADED'


def test_github_success_without_saved_fill_does_not_pass():
    now=m.ACTIVATED_AT+timedelta(hours=1)
    due=m.slot_for(now-timedelta(minutes=21),1)
    run={'name':workflows()[0]['name'],'event':'schedule','head_branch':'main',
         'created_at':due.isoformat(),'status':'completed','conclusion':'success'}
    r=m.analyse(workflows(),[run],now,[])
    assert r['workers'][0]['unproven_slots']


def test_complete_saved_scheduled_window_can_pass():
    now=m.ACTIVATED_AT+timedelta(hours=2)
    run=[];records=[]
    t=m.ACTIVATED_AT.replace(second=0)+timedelta(minutes=1)
    while t <= now-timedelta(minutes=20):
        local=t.astimezone(m.ADELAIDE)
        if local.minute%4==0:
            i=local.minute//4+1
            run.append({'id':int(t.timestamp()),'name':f'CAIRN-{i:02d} Full Paper Cycle (500 USDT)',
                        'event':'schedule','head_branch':'main','created_at':t.isoformat(),
                        'status':'completed','conclusion':'success'})
            records.append({'runner':f'CAIRN-{i:02d}','invocation_kind':'schedule','scheduled_at_utc':t.isoformat(),
                            'status':'LOCAL_COMMITTED','minimum_paper_trade_per_cycle_satisfied':True,
                            'fills':[{'fill_quantity':'0.00001','simulated_fill':True,'live_order_submitted':False}]})
        t+=timedelta(minutes=1)
    r=m.analyse(workflows(),run,now,records)
    assert r['status']=='PASS_WINDOW' and r['verified_due_slots']==r['due_slots']
    assert r['scheduled_workers_seen']==15
    assert not r['all_time_uptime_claimed']
    assert m.analyse(workflows(),run+[run[0]],now,records)['status']=='DEGRADED'
    assert m.analyse(workflows(),run,now,records,complete=False)['status']=='DEGRADED'


def test_live_or_zero_receipt_cannot_prove_paper_execution():
    now=m.ACTIVATED_AT+timedelta(hours=1)
    due=m.slot_for(now-timedelta(minutes=21),1)
    run={'name':workflows()[0]['name'],'event':'schedule','head_branch':'main',
         'created_at':due.isoformat(),'status':'completed','conclusion':'success'}
    for fill in [{'fill_quantity':'0','live_order_submitted':False,'simulated_fill':True},
                 {'fill_quantity':'1','live_order_submitted':True,'simulated_fill':True}]:
        rec={'runner':'CAIRN-01','invocation_kind':'schedule','scheduled_at_utc':due.isoformat(),
             'status':'LOCAL_COMMITTED','minimum_paper_trade_per_cycle_satisfied':True,'fills':[fill]}
        assert m.analyse(workflows(),[run],now,[rec])['workers'][0]['unproven_slots']
