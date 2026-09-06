"""Read-only liveness verification for the fifteen existing 500-USDT workers.

A successful commissioning run is not a scheduled run. This monitor never trades,
resets the ledger, enables/disables schedules, reruns jobs, or alters strategies.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
import zipfile
from zoneinfo import ZoneInfo

UTC = timezone.utc
ADELAIDE = ZoneInfo('Australia/Adelaide')
REPOSITORY = 'Dingding-leo/Cairn'
EPOCH = 'cairn-500-usdt-20260906-v1'
ACTIVATED_AT = datetime(2026, 9, 6, 13, 14, 10, tzinfo=UTC)
GRACE_MINUTES = 20
WORKER = re.compile(r'^CAIRN-(\d{2}) Full Paper Cycle \(500 USDT\)$')
STATE_NAME = 'cairn-state-' + EPOCH


def stamp(value: str) -> datetime:
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('NAIVE_TIMESTAMP')
    return d.astimezone(UTC)


def slot_for(created: datetime, runner: int) -> datetime:
    minute = created.astimezone(UTC).replace(second=0, microsecond=0)
    for delta in range(61):
        candidate = minute - timedelta(minutes=delta)
        if candidate.astimezone(ADELAIDE).minute == 4 * (runner - 1):
            return candidate
    raise ValueError('SLOT_NOT_FOUND')


def analyse(workflows: list[dict[str, Any]], runs: list[dict[str, Any]],
            clock: datetime, records: list[dict[str, Any]],
            complete: bool = True) -> dict[str, Any]:
    """Coverage uses the SAME creation-derived slot identity as the trading code.

    GitHub does not supply the nominal dispatch time here. Delays crossing another
    hourly slot cannot be reconstructed with certainty and are not backfilled.
    """
    if clock.tzinfo is None:
        raise ValueError('NAIVE_TIMESTAMP')
    evidence = {(r.get('runner'), r.get('scheduled_at_utc')): r for r in records
                if r.get('invocation_kind') == 'schedule'}
    start = max(ACTIVATED_AT, clock.astimezone(UTC) - timedelta(hours=3))
    cutoff = clock.astimezone(UTC) - timedelta(minutes=GRACE_MINUTES)
    rows = []
    for runner in range(1, 16):
        name = f'CAIRN-{runner:02d} Full Paper Cycle (500 USDT)'
        configured = [w for w in workflows if w.get('name') == name]
        worker_runs = [r for r in runs if r.get('name') == name and r.get('event') == 'schedule'
                       and r.get('head_branch') == 'main']
        by_slot: dict[datetime, list[dict[str, Any]]] = {}
        for run in worker_runs:
            slot = slot_for(stamp(run['created_at']), runner)
            by_slot.setdefault(slot, []).append(run)
        due = []
        minute = start.replace(second=0, microsecond=0)
        while minute <= cutoff:
            if minute >= ACTIVATED_AT and minute.astimezone(ADELAIDE).minute == 4 * (runner-1):
                due.append(minute)
            minute += timedelta(minutes=1)
        missing, failed, unproven, passed, collisions = [], [], [], [], []
        for slot in due:
            candidates = by_slot.get(slot, [])
            # Distinct run ids for one creation-derived slot are a warning, not
            # proof of duplicate trades; the ledger's idempotency still applies.
            if len(candidates) > 1:
                collisions.append(slot.isoformat())
            item = evidence.get((f'CAIRN-{runner:02d}', slot.isoformat()))
            successful = any(r.get('status') == 'completed' and r.get('conclusion') == 'success'
                             for r in candidates)
            if not candidates:
                missing.append(slot.isoformat())
            elif not successful:
                failed.append(slot.isoformat())
            elif not item or item.get('status') != 'LOCAL_COMMITTED' or not item.get('fills'):
                unproven.append(slot.isoformat())
            elif (item.get('minimum_paper_trade_per_cycle_satisfied') is not True
                  or any(f.get('live_order_submitted') is not False
                         or f.get('simulated_fill') is not True for f in item['fills'])):
                unproven.append(slot.isoformat())
            else:
                from fractions import Fraction
                if not any(Fraction(f.get('fill_quantity', '0')) > 0 for f in item['fills']):
                    unproven.append(slot.isoformat())
                else:
                    passed.append(slot.isoformat())
        state = configured[0].get('state') if len(configured) == 1 else 'MISSING_OR_DUPLICATE'
        unhealthy = bool(missing or failed or unproven or collisions or state != 'active')
        rows.append({'runner':f'CAIRN-{runner:02d}', 'minute':4*(runner-1),
                     'workflow_id':configured[0]['id'] if len(configured)==1 else None,
                     'configured_state':state, 'scheduled_runs_seen':len(worker_runs),
                     'latest_scheduled_run':max((r['created_at'] for r in worker_runs), default=None),
                     'due_slots':len(due), 'verified_slots':passed, 'missing_slots':missing,
                     'failed_or_unfinished_slots':failed, 'unproven_slots':unproven,
                     'duplicate_dispatch_slots':collisions,
                     'continuity_status':'DEGRADED' if unhealthy else ('PASS' if due else 'NOT_YET_DUE')})
    checks_due = sum(r['due_slots'] for r in rows)
    healthy = complete and all(r['continuity_status'] != 'DEGRADED' for r in rows)
    return {'checked_at_utc':clock.astimezone(UTC).isoformat(),
            'checked_at_adelaide':clock.astimezone(ADELAIDE).isoformat(),
            'worker_platform':'GITHUB_ACTIONS_NOT_CHATGPT_TASKS', 'epoch':EPOCH,
            'status': 'DEGRADED' if not healthy else ('PASS_WINDOW' if checks_due else 'WARMING_UP'),
            'active_workers':sum(r['configured_state']=='active' for r in rows),
            'scheduled_workers_seen':sum(r['scheduled_runs_seen']>0 for r in rows),
            'verified_due_slots':sum(len(r['verified_slots']) for r in rows),
            'due_slots':checks_due, 'delivery_grace_minutes':GRACE_MINUTES,
            'lookback_hours':3, 'retrieval_complete':complete,
            'identity_limitation':'Slots derived from original GitHub run creation, not authoritative cron delivery.',
            'schedule_action':'NONE', 'trading_action':'NONE', 'account_reset':False,
            'all_time_uptime_claimed':False,
            'external_independent_monitor':False, 'workers':rows}


def api(path: str) -> dict[str, Any]:
    if not path.startswith(f'/repos/{REPOSITORY}/actions/'):
        raise ValueError('OUT_OF_SCOPE_ENDPOINT')
    r = subprocess.run(['gh', 'api', path], check=True, capture_output=True, timeout=30)
    if len(r.stdout) > 8_000_000:
        raise ValueError('API_RESPONSE_TOO_LARGE')
    return json.loads(r.stdout)


def collection(path: str, field: str, max_pages: int = 10) -> tuple[list[dict[str, Any]], bool]:
    rows = []
    for page in range(1, max_pages+1):
        sep = '&' if '?' in path else '?'
        p = api(f'{path}{sep}per_page=100&page={page}')
        batch = p[field]
        rows.extend(batch)
        if len(batch) < 100 or len(rows) >= p.get('total_count', len(rows)+1):
            return rows, True
    return rows, False


def read_checkpoint(metadata: dict[str, Any], folder: Path) -> list[dict[str, Any]]:
    """Validate all stored payloads and the hash chain without loading trading code."""
    if metadata.get('expired'):
        raise ValueError('CHECKPOINT_EXPIRED')
    remote = metadata.get('workflow_run', {})
    if remote.get('head_repository_id') != 1358810971 or remote.get('head_branch') != 'main':
        raise ValueError('CHECKPOINT_PROVENANCE_MISMATCH')
    a = int(metadata['id'])
    result = subprocess.run(['gh','api',f'/repos/{REPOSITORY}/actions/artifacts/{a}/zip'],
                            check=True,capture_output=True,timeout=60)
    raw = result.stdout
    if len(raw)>60_000_000 or 'sha256:'+hashlib.sha256(raw).hexdigest()!=metadata.get('digest'):
        raise ValueError('CHECKPOINT_DIGEST_MISMATCH')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sorted(z.namelist()) != ['ledger.sqlite3','manifest.json']:
            raise ValueError('CHECKPOINT_FILE_SET_MISMATCH')
        if sum(x.file_size for x in z.infolist()) > 100_000_000:
            raise ValueError('CHECKPOINT_TOO_LARGE')
        ledger=z.read('ledger.sqlite3'); manifest=json.loads(z.read('manifest.json'))
    if (manifest.get('epoch') != EPOCH
            or hashlib.sha256(ledger).hexdigest() != manifest.get('ledger_sha256')):
        raise ValueError('MANIFEST_MISMATCH')
    db = folder/'checked.sqlite3'; db.write_bytes(ledger)
    conn = sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)
    conn.row_factory=sqlite3.Row
    try:
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLITE_CORRUPT')
        meta=dict(conn.execute('SELECT key,value FROM meta').fetchall())
        if meta.get('paper_epoch')!=EPOCH or meta.get('config_sha')!=manifest['config_sha']:
            raise ValueError('DATABASE_EPOCH_OR_CONFIG_MISMATCH')
        canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        previous='0'*64; covered={}
        for row in conn.execute('SELECT * FROM audit_log ORDER BY seq'):
            detail=json.loads(row['details_json'])
            material={'ts':row['ts'],'actor':row['actor'],'action':row['action'],
                      'object_id':row['object_id'],'details':detail,'prev_hash':row['prev_hash']}
            h=hashlib.sha256(canonical(material).encode()).hexdigest()
            if previous!=row['prev_hash'] or h!=row['entry_hash']:
                raise ValueError('AUDIT_CHAIN_INVALID')
            previous=h
            if row['action']=='PUT_RECORD':
                if row['object_id'] in covered:
                    raise ValueError('DUPLICATE_AUDIT_RECORD')
                covered[row['object_id']]=detail['payload_sha256']
        records=conn.execute('SELECT * FROM records').fetchall()
        if previous!=manifest['audit_root'] or len(covered)!=len(records):
            raise ValueError('AUDIT_ROOT_OR_COVERAGE_MISMATCH')
        for row in records:
            h=hashlib.sha256(row['payload_json'].encode()).hexdigest()
            if h!=row['payload_sha256'] or covered.get(row['record_id'])!=h:
                raise ValueError('PAYLOAD_TAMPERING')
        genesis=next(json.loads(r['payload_json']) for r in records if r['record_id']==EPOCH+':genesis')
        from fractions import Fraction
        if Fraction(*map(int,genesis['cash']))!=500 or genesis['sequence']!=0:
            raise ValueError('INITIAL_CAPITAL_NOT_500')
        return [json.loads(r['payload_json']) for r in records if r['record_type']=='cycle_report']
    finally:
        conn.close()


def main() -> int:
    out=Path('continuity-output');out.mkdir(exist_ok=True)
    clock=datetime.now(UTC)
    try:
        workflows,w_complete=collection(f'/repos/{REPOSITORY}/actions/workflows','workflows')
        cutoff=(clock-timedelta(hours=4)).isoformat().replace('+00:00','Z')
        runs,r_complete=collection(f'/repos/{REPOSITORY}/actions/runs?event=schedule&branch=main&created=%3E%3D{cutoff}', 'workflow_runs')
        state=api(f'/repos/{REPOSITORY}/actions/artifacts?name={STATE_NAME}&per_page=100')['artifacts']
        state=[a for a in state if a['name']==STATE_NAME]
        if not state:raise ValueError('SHARED_CHECKPOINT_MISSING')
        latest=max(state,key=lambda a:(a['created_at'],a['id']))
        with tempfile.TemporaryDirectory() as directory:
            records=read_checkpoint(latest,Path(directory).resolve())
        result=analyse(workflows,runs,clock,records,w_complete and r_complete)
        result['checkpoint']={'artifact_id':latest['id'],'digest':latest['digest'],
                              'created_at':latest['created_at'],'verified':True,
                              'recorded_cycles':len(records)}
        (out/'workflow-state.json').write_text(json.dumps(workflows,indent=2))
        (out/'scheduled-runs.json').write_text(json.dumps(runs,indent=2))
    except Exception as e:
        # Provider output, headers and token values are never echoed.
        reason=str(e) if isinstance(e,ValueError) else type(e).__name__
        result={'checked_at_utc':clock.isoformat(),'status':'VERIFICATION_FAILED','reason':reason,
                'schedule_action':'NONE','trading_action':'NONE','account_reset':False}
    (out/'continuity-report.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    text=['# Cairn continuous-operation verification','',f"Status: {result['status']}",'',
          'This is a read-only monitor, not a trading worker or external uptime guarantee.','',
          '| Worker | Active | Scheduled runs seen | Due slots | Verified slots | Status |',
          '|---|---|---:|---:|---:|---|']
    for row in result.get('workers',[]):
        text.append(f"| {row['runner']} | {row['configured_state']} | {row['scheduled_runs_seen']} | {row['due_slots']} | {len(row['verified_slots'])} | {row['continuity_status']} |")
    text += ['', 'A startup/commissioning fill never counts as scheduled-run evidence.',
             'Missing or failed runs are reported, not backfilled with invented or additional trades.',
             'This monitor never disables a worker or rewrites a balance.']
    if 'reason' in result:text += ['', 'Reason: '+result['reason']]
    (out/'continuity-report.md').write_text('\n'.join(text)+'\n')
    if 'GITHUB_STEP_SUMMARY' in os.environ:
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('\n'.join(text)+'\n')
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status'] in {'PASS_WINDOW','WARMING_UP'} else 1


if __name__=='__main__':
    raise SystemExit(main())
