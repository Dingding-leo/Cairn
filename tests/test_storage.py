from pathlib import Path

import pytest

from cairn.storage import Store, StoreError


def test_store_is_immutable_and_auditable(tmp_path: Path):
    store = Store(tmp_path / "cairn.sqlite3")
    store.initialize()
    digest = store.put_record(
        record_id="r1",
        record_type="fixture",
        created_at="2026-09-06T00:00:00Z",
        payload={"a": 1},
        actor="tester",
    )
    assert len(digest) == 64
    assert store.get_record("r1") == {"a": 1}
    assert store.verify_audit_chain()
    assert store.put_record(
        record_id="r1",
        record_type="fixture",
        created_at="2026-09-06T00:00:00Z",
        payload={"a": 1},
        actor="tester",
    ) == digest
    with pytest.raises(StoreError):
        store.put_record(
            record_id="r1",
            record_type="fixture",
            created_at="2026-09-06T00:00:01Z",
            payload={"a": 2},
            actor="tester",
        )


def test_backup_is_verified_and_no_overwrite(tmp_path: Path):
    store = Store(tmp_path / "cairn.sqlite3")
    store.initialize()
    store.put_record(
        record_id="r1",
        record_type="fixture",
        created_at="2026-09-06T00:00:00Z",
        payload={"a": 1},
        actor="tester",
    )
    backup = store.backup(tmp_path / "backup.sqlite3")
    assert Store(backup).verify_audit_chain()
    with pytest.raises(StoreError):
        store.backup(backup)
