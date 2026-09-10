"""Paper-cycle evidence guard, not an execution adapter or a trading strategy.

This module never manufactures fills and cannot place exchange orders. It requires
normalized receipts from a separately verified OKX DEMO adapter. A source label is
not proof of authenticity: adapter conformance and shared-host deployment remain
separate acceptance gates. Synthetic fixtures belong exclusively in tests.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo

ADELAIDE = ZoneInfo("Australia/Adelaide")
SCHEMA = """
CREATE TABLE IF NOT EXISTS cycle_guard_events(
    event_key TEXT PRIMARY KEY, kind TEXT NOT NULL, cycle_key TEXT NOT NULL,
    payload TEXT NOT NULL, digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cycle_guard_locks(
    account TEXT PRIMARY KEY, owner TEXT NOT NULL
);
"""
STAGES = (
    "health", "data", "features", "signals", "portfolio", "risk", "execution",
    "reconciliation", "accounting", "attribution", "monitoring", "research", "validation",
)


class CycleError(RuntimeError):
    """Fail-closed error; not a request to disable a recurring schedule."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def positive(value: str) -> Fraction:
    if not isinstance(value, str) or len(value) > 64:
        raise CycleError("INVALID_DECIMAL")
    # Avoid unbounded exponents and implicit binary-float conversion.
    if not re.fullmatch(r"\d{1,32}(?:\.\d{1,24})?", value):
        raise CycleError("INVALID_DECIMAL")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CycleError("INVALID_DECIMAL") from exc
    if not result.is_finite() or result <= 0:
        raise CycleError("NON_POSITIVE_VALUE")
    return Fraction(result)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CycleError("NAIVE_TIMESTAMP")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CycleIdentity:
    account: str
    runner: int
    scheduled_at: datetime
    code_sha: str
    config_sha: str

    def __post_init__(self) -> None:
        local = utc(self.scheduled_at).astimezone(ADELAIDE)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.account):
            raise CycleError("INVALID_ACCOUNT_ALIAS")
        if type(self.runner) is not int or not 1 <= self.runner <= 15:
            raise CycleError("INVALID_RUNNER")
        if local.minute != 4 * (self.runner - 1) or local.second or local.microsecond:
            raise CycleError("WRONG_SCHEDULED_SLOT")
        if not re.fullmatch(r"[0-9a-f]{40}", self.code_sha):
            raise CycleError("UNPINNED_CODE")
        if not re.fullmatch(r"[0-9a-f]{64}", self.config_sha):
            raise CycleError("UNPINNED_CONFIG")

    @property
    def cycle_id(self) -> str:
        return self.scheduled_at.astimezone(ADELAIDE).strftime(
            f"%Y-%m-%dT%H-%M-CAIRN-{self.runner:02d}"
        )

    @property
    def key(self) -> str:
        # UTC disambiguates repeated Adelaide wall-clock times at DST fall-back.
        return digest([self.account, self.runner, utc(self.scheduled_at).isoformat()])

    def payload(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id, "cycle_key": self.key, "account": self.account,
            "runner": self.runner, "scheduled_at_utc": utc(self.scheduled_at).isoformat(),
            "timezone": "Australia/Adelaide", "code_sha": self.code_sha,
            "config_sha": self.config_sha, "execution_mode": "OKX_DEMO",
        }


class CycleGuard:
    """Use the SAME pre-existing durable SQLite file on ONE execution host.

    No implicit directory/database creation: provisioning is a deployment action.
    These namespaced tables may coexist with cairn.storage.Store's tables. SQLite
    over a network filesystem or independent chat sandboxes is not shared state.
    """

    def __init__(self, database: str | Path, identity: CycleIdentity) -> None:
        self.identity = identity
        self.path = Path(database).resolve(strict=True)
        if not self.path.is_file():
            raise CycleError("DATABASE_NOT_FILE")
        self.owner: str | None = None
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            self.put(connection, identity.key, "cycle", identity.payload())

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def put(self, conn: sqlite3.Connection, key: str, kind: str, body: dict[str, Any]) -> bool:
        payload = {**body, "cycle_id": self.identity.cycle_id, "cycle_key": self.identity.key}
        encoded, checksum = canonical(payload), digest(payload)
        row = conn.execute(
            "SELECT kind,cycle_key,payload,digest FROM cycle_guard_events WHERE event_key=?", (key,)
        ).fetchone()
        expected = (kind, self.identity.key, encoded, checksum)
        if row is not None:
            if row != expected:
                raise CycleError("IDEMPOTENCY_CONFLICT")
            return False
        conn.execute("INSERT INTO cycle_guard_events VALUES(?,?,?,?,?)", (key, *expected))
        return True

    def read(self, conn: sqlite3.Connection, kind: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT payload,digest FROM cycle_guard_events WHERE cycle_key=? AND kind=?",
            (self.identity.key, kind),
        ).fetchall()
        result = []
        for payload, checksum in rows:
            item = json.loads(payload)
            if digest(item) != checksum:
                raise CycleError("CORRUPT_RECORD")
            result.append(item)
        return result

    def require_lock(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT owner FROM cycle_guard_locks WHERE account=?", (self.identity.account,)
        ).fetchone()
        if self.owner is None or row != (self.owner,):
            raise CycleError("ACCOUNT_LOCK_REQUIRED")

    @contextmanager
    def account_lock(self) -> Iterator[None]:
        """Serialize runners, including duplicate invocations of the same slot.

        A hard process crash leaves the lock in place. Do not expire/steal it on a
        timer: first reconcile pending/unknown orders through the demo adapter.
        """
        owner = uuid4().hex
        with self.connection() as conn:
            if conn.execute(
                "SELECT 1 FROM cycle_guard_locks WHERE account=?", (self.identity.account,)
            ).fetchone():
                raise CycleError("ACCOUNT_BUSY")
            conn.execute("INSERT INTO cycle_guard_locks VALUES(?,?)", (self.identity.account, owner))
        self.owner = owner
        try:
            yield
        finally:
            with self.connection() as conn:
                conn.execute(
                    "DELETE FROM cycle_guard_locks WHERE account=? AND owner=?",
                    (self.identity.account, owner),
                )
            self.owner = None

    def reserve_order(
        self, *, strategy: str, instrument: str, action: str, quantity: str,
        origin: str, risk_evidence_sha: str,
    ) -> tuple[str, bool]:
        """Commit an intent BEFORE submission; False means lookup, never resend.

        Risk evidence must be generated by the real independent risk component;
        this method does not replace mathematical risk validation.
        """
        positive(quantity)
        if origin not in {"core", "exploration"} or action not in {"buy", "sell"}:
            raise CycleError("INVALID_ORDER")
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,79}", instrument):
            raise CycleError("INVALID_INSTRUMENT")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", strategy):
            raise CycleError("INVALID_STRATEGY")
        if not re.fullmatch(r"[0-9a-f]{64}", risk_evidence_sha):
            raise CycleError("RISK_EVIDENCE_REQUIRED")
        client_id = "c" + digest([self.identity.key, strategy, instrument, action, origin])[:31]
        body = {
            "client_order_id": client_id, "instrument": instrument, "action": action,
            "quantity": quantity, "trade_origin": origin, "strategy": strategy,
            "risk_evidence_sha": risk_evidence_sha,
        }
        with self.connection() as conn:
            self.require_lock(conn)
            if self.read(conn, "report"):
                raise CycleError("CYCLE_ALREADY_FINALIZED")
            if origin == "exploration" and self.read(conn, "fill"):
                raise CycleError("UNNECESSARY_EXPLORATION")
            fresh = self.put(conn, "order:" + client_id, "order", body)
        return client_id, fresh

    def record_fill(
        self, *, client_order_id: str, venue_order_id: str, venue_trade_id: str,
        quantity: str, price: str, source: str, evidence_sha: str,
    ) -> str:
        """Record a normalized broker receipt, never an order acknowledgement.

        The adapter must authenticate/verify DEMO, match account/instrument/side,
        validate timestamps, and retain the redacted receipt identified by the
        hash. Receipt authenticity is NOT established by a string or this method.
        """
        qty = positive(quantity)
        positive(price)
        if source != "OKX_DEMO":
            raise CycleError("NOT_OKX_DEMO")
        if not re.fullmatch(r"[0-9]{1,64}", venue_order_id) or not re.fullmatch(
            r"[0-9]{1,64}", venue_trade_id
        ):
            raise CycleError("BROKER_RECEIPT_REQUIRED")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha):
            raise CycleError("BROKER_EVIDENCE_REQUIRED")
        with self.connection() as conn:
            self.require_lock(conn)
            if self.read(conn, "report"):
                raise CycleError("CYCLE_ALREADY_FINALIZED")
            orders = [x for x in self.read(conn, "order") if x["client_order_id"] == client_order_id]
            if len(orders) != 1:
                raise CycleError("UNRESERVED_ORDER")
            order = orders[0]
            key = "fill:" + digest([self.identity.account, order["instrument"], venue_trade_id])
            body = {
                "fill_key": key, "client_order_id": client_order_id,
                "venue_order_id": venue_order_id, "venue_trade_id": venue_trade_id,
                "instrument": order["instrument"], "trade_origin": order["trade_origin"],
                "quantity": quantity, "price": price, "source": source, "evidence_sha": evidence_sha,
            }
            if not self.put(conn, key, "fill", body):
                return key
            filled = sum(
                (positive(x["quantity"]) for x in self.read(conn, "fill")
                 if x["client_order_id"] == client_order_id), Fraction(0)
            )
            if qty > positive(order["quantity"]) or filled > positive(order["quantity"]):
                raise CycleError("OVERFILL")
        return key

    def record_stage(self, stage: str, result: dict[str, Any]) -> str:
        """Persist a redacted stage result; a supplied hash alone is not evidence.

        The caller owns the deterministic computation/verification. Never pass
        credentials, request headers or unredacted provider errors in result.
        """
        if stage not in STAGES or result.get("status") not in {"COMPLETED", "BLOCKED"}:
            raise CycleError("INVALID_STAGE_RESULT")
        body = {
            "stage": stage, "result": result,
            "cycle_id": self.identity.cycle_id, "cycle_key": self.identity.key,
        }
        with self.connection() as conn:
            self.require_lock(conn)
            self.put(conn, "stage:" + self.identity.key + ":" + stage, "stage", body)
        return digest(body)

    def finish(
        self, *, stage_evidence: dict[str, str], reconciled_fill_keys: list[str],
        unresolved_orders: bool, blockers: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Commit and read back a report before returning it to the caller.

        Call only after broker lifecycle resolution, ledger/accounting commit and
        reconciliation. All thirteen stage hashes refer to durable artifacts.
        Late events need a separately versioned amendment, never history rewriting.
        """
        with self.connection() as conn:
            self.require_lock(conn)
            existing = self.read(conn, "report")
            if existing:
                return existing[0]
            fills = self.read(conn, "fill")
            issues = list(blockers)
            if any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", x) for x in issues):
                raise CycleError("USE_REDACTED_REASON_CODES")
            saved_stages = {x["stage"]: x for x in self.read(conn, "stage")}
            for stage in STAGES:
                value = stage_evidence.get(stage, "")
                if not re.fullmatch(r"[0-9a-f]{64}", value):
                    issues.append("MISSING_STAGE_" + stage.upper())
                elif stage not in saved_stages or digest(saved_stages[stage]) != value:
                    issues.append("UNVERIFIED_STAGE_" + stage.upper())
                elif saved_stages[stage]["result"]["status"] != "COMPLETED":
                    issues.append("BLOCKED_STAGE_" + stage.upper())
            if unresolved_orders:
                issues.append("UNRESOLVED_ORDERS")
            if len(reconciled_fill_keys) != len(set(reconciled_fill_keys)) or set(
                reconciled_fill_keys
            ) != {x["fill_key"] for x in fills}:
                issues.append("RECONCILIATION_MISMATCH")
            core = {x["client_order_id"] for x in fills if x["trade_origin"] == "core"}
            exploration = {x["client_order_id"] for x in fills if x["trade_origin"] == "exploration"}
            satisfied = bool(core | exploration)
            status = "HALTED" if issues else ("COMPLETE" if satisfied else "INCOMPLETE_NO_FILL")
            report = {
                **self.identity.payload(), "status": status,
                "minimum_paper_trade_per_cycle": 1, "minimum_satisfied": satisfied,
                "core_filled_orders": len(core), "exploration_filled_orders": len(exploration),
                "distinct_filled_orders": len(core | exploration), "fill_events": len(fills),
                "fill_keys": sorted(x["fill_key"] for x in fills),
                "stage_evidence": stage_evidence, "blockers": sorted(set(issues)),
                "reason": "NO_CONFIRMED_NONZERO_FILL" if not satisfied else None,
                "schedule_action": "NONE", "schedule_state_required": "ACTIVE",
            }
            self.put(conn, "report:" + self.identity.key, "report", report)
        # A new connection proves read-back, not cross-host or indefinite durability.
        with self.connection() as conn:
            return self.read(conn, "report")[0]


def human_report(report: dict[str, Any]) -> str:
    """Render ONLY the committed machine report, not independently authored totals."""
    return (
        f"Cairn cycle {report['cycle_id']} - {report['status']}\n"
        f"CORE filled orders: {report['core_filled_orders']}\n"
        f"EXPLORATION filled orders: {report['exploration_filled_orders']}\n"
        f"Distinct filled orders: {report['distinct_filled_orders']}\n"
        f"minimum_paper_trade_per_cycle=1 satisfied: {report['minimum_satisfied']}\n"
        f"Blockers: {', '.join(report['blockers']) or report['reason'] or 'none'}\n"
        f"Fill records: {', '.join(report['fill_keys']) or 'none'}\n"
        "Recurring schedule: leave active; this report does not modify it.\n"
    )
