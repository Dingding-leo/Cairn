"""GitHub artifact transport for the 500-USDT epoch; no trading APIs or task controls.

Only GitHub CLI read operations are used. The caller serializes ALL jobs sharing the
account through one concurrency group. Archived JSON from the old 100k epoch is
never interpreted as 500-USDT state.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from cairn import paper500 as p

REPO = 'Dingding-leo/Cairn'
DB = Path('state500/ledger.sqlite3')
OUT = Path('paper500-output')
META = Path('paper500-trigger.json')


def gh(endpoint: str) -> bytes:
    p.require(endpoint.startswith('/repos/'+REPO+'/actions/'), 'GITHUB_ENDPOINT_NOT_ALLOWED')
    r = subprocess.run(['gh','api',endpoint],check=True,capture_output=True,timeout=60)
    p.require(len(r.stdout)<=60_000_000,'ARTIFACT_RESPONSE_TOO_LARGE')
    return r.stdout


def js(endpoint: str):
    return json.loads(gh(endpoint))


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unzip_checked(raw: bytes, metadata: dict) -> dict[str,bytes]:
    p.require(metadata.get('digest')=='sha256:'+digest(raw),'ARTIFACT_DIGEST_MISMATCH')
    result={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for entry in z.infolist():
            parts=Path(entry.filename).parts
            p.require(not entry.filename.startswith('/') and '..' not in parts,'UNSAFE_ZIP_PATH')
            p.require(entry.file_size<=100_000_000,'UNSAFE_ZIP_SIZE')
            if not entry.is_dir(): result[entry.filename]=z.read(entry)
    return result


def output(name: str,value: str) -> None:
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'],'a') as f: f.write(name+'='+value+'\n')


def manifest() -> dict:
    verified=p.verify_database(DB)
    value={'epoch':p.EPOCH,'config_sha':p.CONFIG_SHA,'ledger_sha256':digest(DB.read_bytes()),
           'audit_root':verified['audit_root'],'sequence':verified['state']['sequence'],
           'record_count':verified['records'],'created_at':p.now().isoformat()}
    save(DB.parent/'manifest.json',value)
    return value


def validate_state_files(files: dict[str,bytes],destination: Path) -> dict:
    p.require(set(files)=={'ledger.sqlite3','manifest.json'},'CHECKPOINT_FILE_SET_MISMATCH')
    m=json.loads(files['manifest.json'])
    p.require(m['epoch']==p.EPOCH and m['config_sha']==p.CONFIG_SHA,'WRONG_CHECKPOINT_EPOCH')
    p.require(digest(files['ledger.sqlite3'])==m['ledger_sha256'],'CHECKPOINT_HASH_MISMATCH')
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'ledger.sqlite3').write_bytes(files['ledger.sqlite3'])
    check=p.verify_database(destination/'ledger.sqlite3')
    p.require(check['audit_root']==m['audit_root'] and check['state']['sequence']==m['sequence'],
              'CHECKPOINT_METADATA_MISMATCH')
    (destination/'manifest.json').write_bytes(files['manifest.json'])
    return check


def restore(initialize: bool=False) -> None:
    p.require(os.environ.get('GITHUB_REPOSITORY')==REPO,'WRONG_REPOSITORY')
    run_id=os.environ['GITHUB_RUN_ID']
    p.require(run_id.isdigit(),'INVALID_RUN_ID')
    run=js(f'/repos/{REPO}/actions/runs/{run_id}')
    save(META,{'created_at':run['created_at'],'run_id':run_id,'event':run['event'],
               'head_sha':run['head_sha'],'run_attempt':run.get('run_attempt')})
    entries=js(f'/repos/{REPO}/actions/artifacts?name={p.STATE_ARTIFACT}&per_page=100')['artifacts']
    entries=[a for a in entries if a['name']==p.STATE_ARTIFACT]
    p.require(not DB.exists(),'LOCAL_STATE_NOT_EMPTY')
    if entries:
        a=max(entries,key=lambda x:(x['created_at'],x['id']))
        p.require(not a['expired'],'LATEST_CHECKPOINT_EXPIRED_NO_RESET')
        p.require(a['workflow_run']['head_repository_id']==1358810971
                  and a['workflow_run']['head_branch'] in {'main','auto/paper-cycle-runner'},
                  'UNTRUSTED_CHECKPOINT_PROVENANCE')
        files=unzip_checked(gh(f"/repos/{REPO}/actions/artifacts/{a['id']}/zip"),a)
        validate_state_files(files,DB.parent)
        save(OUT/'restore-receipt.json',{'epoch':p.EPOCH,'restored_artifact_id':a['id'],
                                       'digest':a['digest'],'reset':False})
    else:
        p.require(initialize,'SHARED_STATE_MISSING_NO_AUTO_RESET')
        p.require(os.environ.get('GITHUB_RUN_ATTEMPT','1')=='1','BOOTSTRAP_RETRY_REQUIRES_REVIEW')
        p.initialize(DB)
        save(OUT/'initialization.json',{'epoch':p.EPOCH,'initial_capital':'500','currency':'USDT',
                                      'owner_authorized_new_epoch':True,'old_account_overwritten':False})
    manifest()
    output('state_verified','true')


def execute(runner: int) -> None:
    p.verify_database(DB)
    meta=json.loads(META.read_text())
    kind='schedule' if meta['event']=='schedule' else 'commissioning'
    ident=p.identity(runner,datetime.fromisoformat(meta['created_at'].replace('Z','+00:00')),
                     kind,str(meta['run_id']))
    report=p.Store(DB).get_record(ident['cycle_key']+':report')
    if report is None:
        try: market=p.acquire()
        except Exception: market=None
        report=p.run_cycle(DB,ident,market,os.environ['CAIRN_CODE_SHA'])
    p.write_report(OUT,report)
    m=manifest()
    save(OUT/'local-verification.json',{'cycle_id':report['cycle_id'],
           'cycle_key':report['cycle_key'],'ledger_sha256':m['ledger_sha256'],
           'audit_root':m['audit_root'],'local_status':report['status']})
    output('state_verified','true')
    print(json.dumps({'cycle_id':report['cycle_id'],'local_status':report['status'],
                       'fills':report['fills'],'incidents':report['incidents']},sort_keys=True))


def verify_delivery(state_id: str,cycle_id: str) -> None:
    p.require(state_id.isdigit() and cycle_id.isdigit(),'UPLOAD_IDS_MISSING')
    run_id=int(os.environ['GITHUB_RUN_ID'])
    filesets=[]
    for aid,name in [(state_id,p.STATE_ARTIFACT),(cycle_id,'cairn-cycle500-'+str(run_id))]:
        m=js(f'/repos/{REPO}/actions/artifacts/{aid}')
        p.require(not m['expired'] and m['name']==name and m['workflow_run']['id']==run_id,
                  'WRONG_DELIVERY_ARTIFACT')
        filesets.append(unzip_checked(gh(f'/repos/{REPO}/actions/artifacts/{aid}/zip'),m))
    remote=validate_state_files(filesets[0],Path('delivery-check'))
    report=json.loads((OUT/'cycle-report.json').read_text())
    received=json.loads(filesets[1]['cycle-report.json'])
    p.require(report==received,'UPLOADED_REPORT_MISMATCH')
    saved=p.Store('delivery-check/ledger.sqlite3').get_record(report['cycle_key']+':report')
    p.require(saved==report,'UPLOADED_LEDGER_REPORT_MISMATCH')
    passed=(report['status']=='LOCAL_COMMITTED'
            and report['minimum_paper_trade_per_cycle_satisfied'] is True
            and len(report['fills'])==1
            and p.F(report['fills'][0]['fill_quantity'])>0
            and report['fills'][0]['simulated_fill'] is True
            and report['fills'][0]['live_order_submitted'] is False
            and report['stages']['reconciliation']['status']=='MATCH')
    receipt={**report,'status':'COMPLETED' if passed else 'HALTED',
             'remote_persistence_verified':True,'audit_chain_valid':remote['audit_chain_valid'],
             'state_artifact_id':int(state_id),'cycle_artifact_id':int(cycle_id),
             'remote_audit_root':remote['audit_root'],'github_run_id':run_id,
             'meaning':'Paper execution/accounting completion only; CORE remains unavailable.'}
    p.write_report(Path('paper500-acceptance'),receipt)
    print(json.dumps({'cycle_id':receipt['cycle_id'],'status':receipt['status'],
                     'initial_capital':p.INITIAL,'remote_persistence_verified':True,
                     'audit_chain_valid':True,'fills':receipt['fills'],
                     'account_after':receipt['account_after'],'core':receipt['core']},sort_keys=True))
    p.require(passed,'CYCLE_HALTED_CHECK_PERSISTED_INCIDENT')


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['restore','initialize','run','verify'])
    parser.add_argument('--runner',type=int)
    parser.add_argument('--state-id',default='')
    parser.add_argument('--cycle-id',default='')
    args=parser.parse_args()
    if args.command in {'restore','initialize'}: restore(args.command=='initialize')
    elif args.command=='run': execute(args.runner)
    else: verify_delivery(args.state_id,args.cycle_id)


if __name__=='__main__':
    try: main()
    except Exception as error:
        # No provider response body, request headers or environment values are printed.
        reason=str(error) if isinstance(error,p.Halt) else type(error).__name__
        save(OUT/'operational-failure.json',{'epoch':p.EPOCH,'status':'HALTED','reason':reason,
                                          'schedule_action':'NONE','orders_not_asserted_successful':True})
        print('CAIRN_HALTED '+reason)
        raise SystemExit(1)
