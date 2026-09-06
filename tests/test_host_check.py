"""Synthetic temporary ledgers only; never forward paper execution."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import sqlite3
import pytest
from cairn.bracket_ledger import Ledger, dumps
from cairn.bracket_policy import Quote, Instrument
from fractions import Fraction as F
spec=spec_from_file_location('hc', Path(__file__).parents[1]/'scripts/cairn_host_check.py')
hc=module_from_spec(spec);spec.loader.exec_module(hc)
CHALLENGE='diagnostic_123456789'
T=1788753600000

@pytest.fixture
def home(tmp_path):
    Ledger.initialize(tmp_path/'ledger.sqlite3','unit_test_only')
    return tmp_path

def test_missing_state_is_not_created(tmp_path):
    r=hc.check(tmp_path,'unit_test_only',CHALLENGE,now_ms=T)
    assert r['blockers']==['PERSISTENT_ACCOUNT_MISSING_NO_AUTO_RESET']
    assert list(tmp_path.iterdir())==[]

def test_explicit_account_identity(home):
    assert hc.check(home,'different',CHALLENGE,now_ms=T)['blockers']==['ACCOUNT_ID_MISMATCH']

def test_no_guardian_no_pass_and_no_writes(home):
    path=home/'ledger.sqlite3';before=path.read_bytes()
    r=hc.check(home,'unit_test_only',CHALLENGE,now_ms=T)
    assert r['status']=='BLOCKED' and 'GUARDIAN_HEARTBEAT_UNHEALTHY' in r['blockers']
    assert r['audit_chain_valid'] and path.read_bytes()==before

def test_recent_real_observation_preflight_not_full_cycle(home):
    ledger=Ledger(home/'ledger.sqlite3')
    q=Quote(F('79999.9'),F('80000.1'),F(1),F(1),T,'unit_only')
    i=Instrument('BTC-USDT',F('.00000001'),F('.1'),F('.00001'))
    ledger.observe(q,i,T)
    raw=(home/'ledger.sqlite3').read_bytes()
    r=hc.check(home,'unit_test_only',CHALLENGE,now_ms=T+1000)
    assert r['status']=='LOCAL_PREFLIGHT_PASS'
    assert r['challenge']==CHALLENGE and not r['full_cycle_executed']
    assert not r['remote_connection_authenticated_by_this_script']
    assert not r['migration_commissioned_by_this_script']
    assert (home/'ledger.sqlite3').read_bytes()==raw

@pytest.mark.parametrize('key,value,reason',[
    ('heartbeat_ms',T-5001,'GUARDIAN_HEARTBEAT_UNHEALTHY'),
    ('heartbeat_ms',T+1,'GUARDIAN_HEARTBEAT_UNHEALTHY'),
    ('last_quote_ms',T-5001,'GUARDIAN_QUOTE_UNHEALTHY'),
    ('recovery_required',True,'UNRESOLVED_PROTECTION_GAP'),
    ('policy',{},'POLICY_MIGRATION_REQUIRED'),
    ('mode','LIVE','NOT_PAPER_ONLY'),
    ('cash',F(501),'ACCOUNT_REPLAY_MISMATCH')])
def test_fail_closed(home,key,value,reason):
    with sqlite3.connect(home/'ledger.sqlite3') as c:
        c.execute('UPDATE meta SET v=? WHERE k=?',(dumps(value),key))
    r=hc.check(home,'unit_test_only',CHALLENGE,now_ms=T)
    assert r['status']=='BLOCKED' and reason in r['blockers']

def test_audit_damage_rejected(home):
    with sqlite3.connect(home/'ledger.sqlite3') as c:
        c.execute("UPDATE audit SET entry_hash='tampered'")
    assert hc.check(home,'unit_test_only',CHALLENGE,now_ms=T)['blockers']==['AUDIT_CHAIN_INVALID']

def test_challenge_not_shell_command(home):
    with pytest.raises(ValueError,match='INVALID_CHALLENGE'):
        hc.check(home,'unit_test_only','$(echo not_a_challenge)',now_ms=T)
