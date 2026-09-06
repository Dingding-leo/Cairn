from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    asset_id TEXT,
    mode TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_type_asset ON records(record_type, asset_id);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_id TEXT NOT NULL,
    details_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS idempotency (
    namespace TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY(namespace, idempotency_key)
);
"""


class StoreError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1')"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _audit(
        self,
        conn: sqlite3.Connection,
        *,
        ts: str,
        actor: str,
        action: str,
        object_id: str,
        details: dict[str, Any],
    ) -> str:
        row = conn.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = "0" * 64 if row is None else str(row[0])
        details_json = canonical_json(details)
        material = canonical_json(
            {
                "ts": ts,
                "actor": actor,
                "action": action,
                "object_id": object_id,
                "details": json.loads(details_json),
                "prev_hash": prev_hash,
            }
        )
        entry_hash = sha256_text(material)
        conn.execute(
            """
            INSERT INTO audit_log(ts, actor, action, object_id, details_json, prev_hash, entry_hash)
            VALUES(?,?,?,?,?,?,?)
            """,
            (ts, actor, action, object_id, details_json, prev_hash, entry_hash),
        )
        return entry_hash

    def put_record(
        self,
        *,
        record_id: str,
        record_type: str,
        created_at: str,
        payload: Any,
        actor: str,
        asset_id: str | None = None,
        mode: str | None = None,
    ) -> str:
        payload_json = canonical_json(payload)
        digest = sha256_text(payload_json)
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT payload_sha256 FROM records WHERE record_id=?", (record_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] == digest:
                    return digest
                raise StoreError("record id already exists with different content")
            conn.execute(
                """
                INSERT INTO records(record_id, record_type, asset_id, mode, created_at, payload_json, payload_sha256)
                VALUES(?,?,?,?,?,?,?)
                """,
                (record_id, record_type, asset_id, mode, created_at, payload_json, digest),
            )
            self._audit(
                conn,
                ts=created_at,
                actor=actor,
                action="PUT_RECORD",
                object_id=record_id,
                details={"record_type": record_type, "payload_sha256": digest},
            )
        return digest

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM records WHERE record_id=?", (record_id,)
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def records(self, record_type: str, asset_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT payload_json FROM records WHERE record_type=?"
        args: list[Any] = [record_type]
        if asset_id is not None:
            sql += " AND asset_id=?"
            args.append(asset_id)
        sql += " ORDER BY created_at, record_id"
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def verify_audit_chain(self) -> bool:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
        prev = "0" * 64
        for row in rows:
            if row["prev_hash"] != prev:
                return False
            material = canonical_json(
                {
                    "ts": row["ts"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "object_id": row["object_id"],
                    "details": json.loads(row["details_json"]),
                    "prev_hash": row["prev_hash"],
                }
            )
            expected = sha256_text(material)
            if row["entry_hash"] != expected:
                return False
            prev = expected
        return True

    def backup(self, destination: str | Path) -> Path:
        destination = Path(destination)
        if destination.exists():
            raise StoreError("backup destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        check = Store(destination)
        if not check.verify_audit_chain():
            destination.unlink(missing_ok=True)
            raise StoreError("backup failed audit verification")
        return destination
