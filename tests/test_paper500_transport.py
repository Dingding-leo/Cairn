"""Offline artifact-transport tests, never actual broker trades."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest
from cairn import paper500 as p

spec=importlib.util.spec_from_file_location('ops',Path(__file__).parents[1]/'scripts/paper500_ops.py')
ops=importlib.util.module_from_spec(spec); spec.loader.exec_module(ops)


def archive(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,data in files.items(): z.writestr(name,data)
    raw=out.getvalue()
    return raw,{'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}


def test_archive_digest_checked():
    raw,meta=archive({'manifest.json':'{}'})
    meta['digest']='sha256:'+'0'*64
    with pytest.raises(p.Halt,match='DIGEST'): ops.unzip_checked(raw,meta)


@pytest.mark.parametrize('path',['/absolute','../outside','sub/../../outside'])
def test_zip_path_escape_rejected(path):
    raw,meta=archive({path:'test'})
    with pytest.raises(p.Halt,match='UNSAFE_ZIP_PATH'): ops.unzip_checked(raw,meta)


def test_state_restore_hash_and_epoch(tmp_path):
    source=tmp_path/'source.sqlite3';p.initialize(source)
    audit=p.verify_database(source)
    manifest={'epoch':p.EPOCH,'config_sha':p.CONFIG_SHA,'ledger_sha256':ops.digest(source.read_bytes()),
              'audit_root':audit['audit_root'],'sequence':0}
    files={'ledger.sqlite3':source.read_bytes(),'manifest.json':json.dumps(manifest).encode()}
    assert ops.validate_state_files(files,tmp_path/'restored')['state']['sequence']==0
    manifest['epoch']='100000_USDT_OLD_EPOCH';files['manifest.json']=json.dumps(manifest).encode()
    with pytest.raises(p.Halt,match='WRONG_CHECKPOINT_EPOCH'): ops.validate_state_files(files,tmp_path/'bad')


def test_checkpoint_missing_files_rejected(tmp_path):
    with pytest.raises(p.Halt,match='FILE_SET'):ops.validate_state_files({'account.json':b'{}'},tmp_path)


def test_github_write_endpoint_out_of_scope():
    with pytest.raises(p.Halt,match='NOT_ALLOWED'):ops.gh('/repos/Dingding-leo/Cairn/contents/key')
