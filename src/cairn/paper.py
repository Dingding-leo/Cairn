from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .exact import decimal_fraction, fraction_decimal
from .models import PaperAction


@dataclass(frozen=True)
class Position:
    quantity: Fraction = Fraction(0, 1)
    cost_basis: Fraction = Fraction(0, 1)


@dataclass(frozen=True)
class PaperState:
    sequence: int
    cash: Fraction
    positions: dict[str, Position]
    fees_paid: Fraction = Fraction(0, 1)
    distributions: Fraction = Fraction(0, 1)


@dataclass(frozen=True)
class PaperReceipt:
    sequence: int
    action_id: str
    cash: str
    quantity: str
    cost_basis: str
    fee_paid: str


def create_account(initial_cash: str) -> PaperState:
    cash = decimal_fraction(initial_cash)
    if cash <= 0:
        raise ValueError("initial cash must be positive")
    return PaperState(sequence=0, cash=cash, positions={})


def apply_action(state: PaperState, action: PaperAction) -> tuple[PaperState, PaperReceipt]:
    if action.expected_sequence != state.sequence:
        raise ValueError("paper action sequence mismatch")
    qty = decimal_fraction(action.quantity)
    price = decimal_fraction(action.price)
    fee = decimal_fraction(action.fee)
    if qty <= 0 or price <= 0 or fee < 0:
        raise ValueError("invalid paper fill inputs")

    positions = dict(state.positions)
    current = positions.get(action.inst_id, Position())
    cash = state.cash

    if action.side == "BUY":
        notional = qty * price
        total = notional + fee
        if total > cash:
            raise ValueError("insufficient cash; margin creation is forbidden")
        new_quantity = current.quantity + qty
        new_cost = current.cost_basis + notional + fee
        positions[action.inst_id] = Position(new_quantity, new_cost)
        cash -= total
    else:
        if qty > current.quantity:
            raise ValueError("short selling is not supported in the paper ledger")
        proceeds = qty * price - fee
        if proceeds < 0:
            raise ValueError("fee exceeds sale proceeds")
        remaining = current.quantity - qty
        allocated_cost = current.cost_basis * qty / current.quantity
        remaining_cost = current.cost_basis - allocated_cost
        cash += proceeds
        if remaining == 0:
            positions.pop(action.inst_id, None)
        else:
            positions[action.inst_id] = Position(remaining, remaining_cost)

    new_state = PaperState(
        sequence=state.sequence + 1,
        cash=cash,
        positions=positions,
        fees_paid=state.fees_paid + fee,
        distributions=state.distributions,
    )
    p = positions.get(action.inst_id, Position())
    receipt = PaperReceipt(
        sequence=new_state.sequence,
        action_id=action.action_id,
        cash=fraction_decimal(cash),
        quantity=fraction_decimal(p.quantity),
        cost_basis=fraction_decimal(p.cost_basis),
        fee_paid=fraction_decimal(fee),
    )
    return new_state, receipt


def apply_distribution(state: PaperState, amount: str) -> PaperState:
    value = decimal_fraction(amount)
    if value < 0:
        raise ValueError("negative distributions require a separately modelled loss event")
    return PaperState(
        sequence=state.sequence + 1,
        cash=state.cash + value,
        positions=dict(state.positions),
        fees_paid=state.fees_paid,
        distributions=state.distributions + value,
    )


def mark_to_market(state: PaperState, marks: dict[str, str]) -> Fraction:
    missing = set(state.positions) - set(marks)
    if missing:
        raise ValueError(f"missing marks for held positions: {sorted(missing)}")
    nav = state.cash
    for inst_id, position in state.positions.items():
        price = decimal_fraction(marks[inst_id])
        if price <= 0:
            raise ValueError("marks must be positive")
        nav += position.quantity * price
    return nav
