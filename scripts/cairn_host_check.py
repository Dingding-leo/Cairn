"""Read-only host and account preflight. No network, account creation or schedules.

Run through the owner's supported computer connection, not in a replacement chat
sandbox. A caller-provided challenge ties output to a real command invocation; it
is not cryptographic proof of host ownership. All state is opened mode=ro.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def decode(value):
    if isinstance(value, dict):
        if set(value) == {'n', 'd'}:
            return Fraction(int(value['n']), int(value['d']))
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def check(home: Path, account_id: str, challenge: str, *, now_ms: int | None = None):
    """Inspection does not mark migration, guardian or remote access commissioned."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', challenge):
        raise ValueError('INVALID_CHALLENGE')
    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    result = {
        'checked_at_utc': datetime.fromtimestamp(timestamp/1000, timezone.utc).isoformat(),
        'challenge': challenge, 'status': 'BLOCKED', 'blockers': [],
        'account_mutated': False, 'schedule_action': 'NONE', 'network_requests': 0,
        'full_cycle_executed': False, 'remote_connection_authenticated_by_this_script': False,
        'migration_commissioned_by_this_script': False,
    }
    database = home.expanduser().resolve() / 'ledger.sqlite3'
    result['database_path'] = str(database)
    if not database.is_file():
        result['blockers'] = ['PERSISTENT_ACCOUNT_MISSING_NO_AUTO_RESET']
        return result
    connection = None
    try:
        connection = sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=5)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLITE_CORRUPT')
        meta = {k: decode(json.loads(v)) for k,v in connection.execute('SELECT k,v FROM meta')}
        if meta.get('account_id') != account_id:
            raise ValueError('ACCOUNT_ID_MISMATCH')
        if meta.get('mode') != 'LOCAL_PAPER_LEDGER':
            raise ValueError('NOT_PAPER_ONLY')
        from cairn.bracket_policy import Policy
        if meta.get('policy') != asdict(Policy()):
            raise ValueError('POLICY_MIGRATION_REQUIRED')
        previous = '0'*64
        trades, fills, cycles = {}, {}, {}
        cash = Fraction(0)
        fees = Fraction(0)
        genesis_count = 0
        for number, row in enumerate(connection.execute('SELECT seq,kind,payload,prev_hash,entry_hash FROM audit ORDER BY seq')):
            seq, kind, payload, old, digest = row
            expected = hashlib.sha256(canonical([seq, kind, payload, old]).encode()).hexdigest()
            if seq != number or old != previous or expected != digest:
                raise ValueError('AUDIT_CHAIN_INVALID')
            previous = digest
            event = decode(json.loads(payload))
            if kind == 'GENESIS':
                genesis_count += 1
                if number != 0 or any(event.get(k) != meta.get(k) for k in ('initial_cash','account_id','mode','policy')):
                    raise ValueError('GENESIS_MISMATCH')
                cash = event['initial_cash']
            if 'trade' in event:
                trades[event['trade']['id']] = event['trade']
            if event.get('fill'):
                f = event['fill']
                if f['id'] in fills:
                    raise ValueError('DUPLICATE_FILL')
                fills[f['id']] = f
                cash += f['cash_delta']
                fees += f['fee']
            if event.get('cycle'):
                cycles[event['cycle']['cycle_key']] = event['cycle']
        if genesis_count != 1 or meta['initial_cash'] != 500:
            raise ValueError('INITIAL_HISTORY_NOT_500')
        for table, expected, key in [('trades',trades,'id'), ('fills',fills,'id'), ('cycles',cycles,'cycle_key')]:
            stored = [decode(json.loads(r[0])) for r in connection.execute('SELECT payload FROM '+table)]
            if len(stored) != len(expected) or {r[key]:r for r in stored} != expected:
                raise ValueError(table.upper()+'_REPLAY_MISMATCH')
        if cash != meta['cash'] or fees != meta['fees']:
            raise ValueError('ACCOUNT_REPLAY_MISMATCH')
        result.update(account_identity_matched=True, audit_chain_valid=True,
                      audit_root=previous, open_trades=sum(t['remaining']>0 for t in trades.values()),
                      recorded_entry_cycles=len(cycles), paper_mode_verified=True)
        for field in ('heartbeat_ms','last_quote_ms'):
            stamp = meta.get(field)
            valid = type(stamp) is int and 0 <= timestamp-stamp <= 5000
            result[field+'_age'] = timestamp-stamp if type(stamp) is int else None
            if not valid:
                result['blockers'].append('GUARDIAN_HEARTBEAT_UNHEALTHY' if field=='heartbeat_ms' else 'GUARDIAN_QUOTE_UNHEALTHY')
        if meta.get('recovery_required') is not False:
            result['blockers'].append('UNRESOLVED_PROTECTION_GAP')
        result['status'] = 'LOCAL_PREFLIGHT_PASS' if not result['blockers'] else 'BLOCKED'
        result['scope'] = 'POINT_IN_TIME_LOCAL_CHECK_ONLY_NOT_MIGRATION_OR_REMOTE_ACCESS_PROOF'
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) else type(error).__name__
        result['blockers'].append(code)
    finally:
        if connection is not None:
            connection.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--challenge', required=True)
    args = parser.parse_args()
    try:
        result = check(args.home, args.account_id, args.challenge)
    except ValueError as error:
        result = {'status':'BLOCKED', 'blockers':[str(error)], 'account_mutated':False,'schedule_action':'NONE'}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status']=='LOCAL_PREFLIGHT_PASS' else 2


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    raise SystemExit(main())
