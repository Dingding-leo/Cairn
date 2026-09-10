"""Synthetic unit fixtures only. These tests are NOT real OKX paper trades."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from cairn.cycle_guard import (
    ADELAIDE, STAGES, CycleError, CycleGuard, CycleIdentity, human_report, positive,
)


@pytest.fixture
def identity():
    return CycleIdentity(
        account="cairn_demo", runner=4,
        scheduled_at=datetime(2026, 9, 6, 19, 12, tzinfo=ADELAIDE),
        code_sha="a" * 40, config_sha="b" * 64,
    )


@pytest.fixture
def guard(tmp_path, identity):
    path = tmp_path / "existing-cairn.sqlite3"
    sqlite3.connect(path).close()
    return CycleGuard(path, identity)


def reserve(guard, origin="core", qty="1"):
    return guard.reserve_order(
        strategy="unit_fixture", instrument="BTC-USDT", action="buy", quantity=qty,
        origin=origin, risk_evidence_sha="c" * 64,
    )


def fill(guard, client_id, trade="100", qty="1", source="OKX_DEMO"):
    return guard.record_fill(
        client_order_id=client_id, venue_order_id="99", venue_trade_id=trade,
        quantity=qty, price="100", source=source, evidence_sha="d" * 64,
    )


def finish(guard, keys=(), **kwargs):
    args = dict(
        stage_evidence=(
            {x: guard.record_stage(x, {"status": "COMPLETED", "fixture": True}) for x in STAGES}
            if guard.owner is not None else {}
        ),
        reconciled_fill_keys=list(keys), unresolved_orders=False,
    )
    args.update(kwargs)
    return guard.finish(**args)


def test_zero_fills_cannot_be_complete(guard):
    with guard.account_lock():
        report = finish(guard)
    assert report["status"] == "INCOMPLETE_NO_FILL"
    assert report["minimum_satisfied"] is False
    assert report["schedule_action"] == "NONE"
    assert "satisfied: False" in human_report(report)


def test_acknowledged_order_is_not_fill(guard):
    with guard.account_lock():
        reserve(guard)
        report = finish(guard, unresolved_orders=True)
    assert report["distinct_filled_orders"] == 0
    assert report["status"] == "HALTED"


@pytest.mark.parametrize("origin", ["core", "exploration"])
def test_confirmed_persisted_fill_can_satisfy_gate(guard, origin):
    with guard.account_lock():
        cid, fresh = reserve(guard, origin)
        assert fresh
        key = fill(guard, cid)
        report = finish(guard, [key])
        assert finish(guard, [key]) == report
    assert report["status"] == "COMPLETE"
    assert report["core_filled_orders"] == int(origin == "core")
    assert report["exploration_filled_orders"] == int(origin == "exploration")
    reopened = CycleGuard(guard.path, guard.identity)
    with reopened.connection() as conn:
        assert reopened.read(conn, "report") == [report]


@pytest.mark.parametrize("qty", ["0", "-1", "NaN", "Infinity", "1e999999", "", "1/2"])
def test_invalid_quantity_never_counts(guard, qty):
    with guard.account_lock():
        cid, _ = reserve(guard)
        with pytest.raises(CycleError):
            fill(guard, cid, qty=qty)
        assert finish(guard)["minimum_satisfied"] is False


@pytest.mark.parametrize("source", ["LIVE", "OKX_PUBLIC", "SYNTHETIC", "LOCAL_PAPER", ""])
def test_only_explicit_demo_receipts_accepted(guard, source):
    with guard.account_lock():
        cid, _ = reserve(guard)
        with pytest.raises(CycleError, match="NOT_OKX_DEMO"):
            fill(guard, cid, source=source)


def test_retry_reserves_same_order_without_resubmission(guard):
    with guard.account_lock():
        cid, first = reserve(guard)
        cid2, second = reserve(guard)
        assert cid == cid2 and first and not second
        assert len(cid) == 32 and cid.isalnum()
        with pytest.raises(CycleError, match="IDEMPOTENCY_CONFLICT"):
            reserve(guard, qty="2")


def test_fill_retry_and_split_fills_count_one_order(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        a = fill(guard, cid, qty="0.4")
        assert fill(guard, cid, qty="0.4") == a
        b = fill(guard, cid, trade="101", qty="0.6")
        report = finish(guard, [a, b])
    assert report["distinct_filled_orders"] == 1
    assert report["fill_events"] == 2


def test_overfill_is_rolled_back(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        a = fill(guard, cid, qty="0.9")
        with pytest.raises(CycleError, match="OVERFILL"):
            fill(guard, cid, trade="101", qty="0.2")
        assert finish(guard, [a])["fill_events"] == 1


def test_exploration_not_added_after_core_fill(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        fill(guard, cid)
        with pytest.raises(CycleError, match="UNNECESSARY_EXPLORATION"):
            reserve(guard, "exploration")


def test_reconciliation_failure_keeps_real_fill_but_halts(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        fill(guard, cid)
        report = finish(guard)
    assert report["minimum_satisfied"] is True
    assert report["status"] == "HALTED"
    assert "RECONCILIATION_MISMATCH" in report["blockers"]


def test_missing_stage_or_safety_failure_prevents_success(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        key = fill(guard, cid)
        report = finish(guard, [key], stage_evidence={}, blockers=("STALE_QUOTE",))
    assert report["status"] == "HALTED"
    assert "STALE_QUOTE" in report["blockers"]
    assert "MISSING_STAGE_ACCOUNTING" in report["blockers"]


def test_account_lock_blocks_distinct_and_duplicate_runners(guard, identity):
    same = CycleGuard(guard.path, identity)
    other = CycleGuard(guard.path, replace(
        identity, runner=5, scheduled_at=identity.scheduled_at.replace(minute=16)
    ))
    with guard.account_lock():
        for runner in [same, other]:
            with pytest.raises(CycleError, match="ACCOUNT_BUSY"), runner.account_lock():
                pytest.fail("must not obtain shared-account lock")
    with other.account_lock():
        reserve(other)


def test_other_cycle_cannot_reuse_same_exchange_trade(guard, identity):
    with guard.account_lock():
        cid, _ = reserve(guard)
        fill(guard, cid)
    next_cycle = CycleGuard(guard.path, replace(
        identity, scheduled_at=identity.scheduled_at.replace(hour=20)
    ))
    with next_cycle.account_lock():
        cid, _ = reserve(next_cycle)
        with pytest.raises(CycleError, match="IDEMPOTENCY_CONFLICT"):
            fill(next_cycle, cid)


def test_lock_required_for_reservations_and_finalization(guard):
    with pytest.raises(CycleError, match="ACCOUNT_LOCK_REQUIRED"):
        reserve(guard)
    with pytest.raises(CycleError, match="ACCOUNT_LOCK_REQUIRED"):
        finish(guard)


def test_finalized_cycle_cannot_accept_late_fill(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        finish(guard)
        with pytest.raises(CycleError, match="CYCLE_ALREADY_FINALIZED"):
            fill(guard, cid)
        with pytest.raises(CycleError, match="CYCLE_ALREADY_FINALIZED"):
            reserve(guard)


def test_same_slot_cannot_change_config(guard, identity):
    with pytest.raises(CycleError, match="IDEMPOTENCY_CONFLICT"):
        CycleGuard(guard.path, replace(identity, config_sha="f" * 64))


def test_no_implicit_empty_database(tmp_path, identity):
    with pytest.raises(FileNotFoundError):
        CycleGuard(tmp_path / "absent.sqlite3", identity)
    assert not (tmp_path / "absent.sqlite3").exists()


def test_future_retry_preserves_scheduled_identity(identity):
    assert identity.cycle_id == "2026-09-06T19-12-CAIRN-04"
    assert identity.key == replace(
        identity, scheduled_at=identity.scheduled_at.astimezone(UTC)
    ).key


def test_dst_repeated_local_time_has_distinct_key(identity):
    early = replace(identity, scheduled_at=datetime(2026, 4, 5, 2, 12, tzinfo=ADELAIDE, fold=0))
    late = replace(identity, scheduled_at=datetime(2026, 4, 5, 2, 12, tzinfo=ADELAIDE, fold=1))
    assert early.cycle_id == late.cycle_id
    assert early.key != late.key


@pytest.mark.parametrize("runner", range(1, 16))
def test_all_fifteen_schedule_offsets(identity, runner):
    context = replace(identity, runner=runner,
                      scheduled_at=identity.scheduled_at.replace(minute=4 * (runner - 1)))
    assert context.cycle_id.endswith(f"CAIRN-{runner:02d}")


def test_exact_arithmetic_does_not_round_small_increment_away():
    from fractions import Fraction
    assert positive("10000000000000000000000000000000.00000001") > Fraction(10**31)


def test_corrupt_record_is_rejected(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        fill(guard, cid)
        with guard.connection() as conn:
            conn.execute("UPDATE cycle_guard_events SET digest='bad' WHERE kind='fill'")
        with pytest.raises(CycleError, match="CORRUPT_RECORD"):
            finish(guard)


def test_external_hashes_without_durable_stage_records_do_not_pass(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        key = fill(guard, cid)
        report = guard.finish(
            stage_evidence={x: "e" * 64 for x in STAGES},
            reconciled_fill_keys=[key], unresolved_orders=False,
        )
    assert report["status"] == "HALTED"
    assert "UNVERIFIED_STAGE_DATA" in report["blockers"]


def test_blocked_stage_overrides_fill_success(guard):
    with guard.account_lock():
        cid, _ = reserve(guard)
        key = fill(guard, cid)
        hashes = {x: guard.record_stage(x, {
            "status": "BLOCKED" if x == "data" else "COMPLETED", "fixture": True
        }) for x in STAGES}
        report = guard.finish(stage_evidence=hashes, reconciled_fill_keys=[key],
                              unresolved_orders=False)
    assert report["status"] == "HALTED"
    assert "BLOCKED_STAGE_DATA" in report["blockers"]


@pytest.mark.parametrize("change", [
    {"account": "bad/account"}, {"runner": 0}, {"runner": 16}, {"runner": True},
    {"code_sha": "main"}, {"config_sha": "latest"},
    {"scheduled_at": datetime(2026, 9, 6, 19, 13, tzinfo=ADELAIDE)},
    {"scheduled_at": datetime(2026, 9, 6, 19, 12, 1, tzinfo=ADELAIDE)},
    {"scheduled_at": datetime(2026, 9, 6, 19, 12, tzinfo=None)},
])
def test_invalid_cycle_identity(identity, change):
    with pytest.raises(CycleError):
        replace(identity, **change)


@pytest.mark.parametrize("change", [
    {"origin": "fake"}, {"action": "withdraw"}, {"instrument": "../BTC"},
    {"strategy": ""}, {"risk_evidence_sha": ""},
])
def test_invalid_order_fields(guard, change):
    values = dict(strategy="fixture", instrument="BTC-USDT", action="buy",
                  quantity="1", origin="core", risk_evidence_sha="c" * 64)
    values.update(change)
    with guard.account_lock(), pytest.raises(CycleError):
        guard.reserve_order(**values)


@pytest.mark.parametrize("change", [
    {"venue_order_id": ""}, {"venue_trade_id": ""}, {"evidence_sha": ""},
    {"client_order_id": "unreserved"},
])
def test_incomplete_broker_receipt(guard, change):
    with guard.account_lock():
        cid, _ = reserve(guard)
        values = dict(client_order_id=cid, venue_order_id="99", venue_trade_id="100",
                      quantity="1", price="100", source="OKX_DEMO", evidence_sha="d" * 64)
        values.update(change)
        with pytest.raises(CycleError):
            guard.record_fill(**values)


@pytest.mark.parametrize("value", ["0" * 65, 1.2, None])
def test_unbounded_or_nonstring_numeric_values(value):
    with pytest.raises(CycleError):
        positive(value)


def test_directory_is_not_a_database(tmp_path, identity):
    with pytest.raises(CycleError, match="DATABASE_NOT_FILE"):
        CycleGuard(tmp_path, identity)


def test_invalid_stage_and_unredacted_errors_rejected(guard):
    with guard.account_lock():
        with pytest.raises(CycleError, match="INVALID_STAGE_RESULT"):
            guard.record_stage("invented", {"status": "COMPLETED"})
        with pytest.raises(CycleError, match="USE_REDACTED_REASON_CODES"):
            finish(guard, blockers=("raw provider response containing credentials",))


def test_report_commit_failure_does_not_return_success(guard, monkeypatch):
    original = guard.put
    def fail_report(conn, key, kind, body):
        if kind == "report":
            raise sqlite3.OperationalError("fixture disk failure")
        return original(conn, key, kind, body)
    with guard.account_lock():
        cid, _ = reserve(guard)
        key = fill(guard, cid)
        monkeypatch.setattr(guard, "put", fail_report)
        with pytest.raises(sqlite3.OperationalError):
            finish(guard, [key])
    with guard.connection() as conn:
        assert guard.read(conn, "report") == []


def test_lock_is_released_after_controlled_failure(guard):
    with pytest.raises(CycleError, match="TEST_FAILURE"), guard.account_lock():
        raise CycleError("TEST_FAILURE")
    with guard.account_lock():
        reserve(guard)
