"""Deterministic PAPER-only bracket policy. No network, keys or live-order transport.

This module is an integration component, not a deployed trading service. Input
market observations must come from a verified public-data adapter. Unit-test
observations must never enter the forward paper account. Quantities are base-asset
units for long-only spot. Short/leveraged/contract orders fail closed.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from fractions import Fraction
from hashlib import sha256
import json
from typing import Iterable

class Blocked(ValueError):
    pass

def require(condition: bool, code: str) -> None:
    if not condition:
        raise Blocked(code)

def number(value: str) -> Fraction:
    require(isinstance(value, str) and 0 < len(value) <= 80, 'INVALID_NUMBER')
    import re
    require(bool(re.fullmatch(r'-?\d{1,30}(?:\.\d{1,30})?', value)), 'INVALID_NUMBER')
    return Fraction(value)

def decimal(value: Fraction, places: int = 18) -> str:
    from decimal import Decimal, localcontext
    with localcontext() as c:
        c.prec = 100
        return format(Decimal(value.numerator) / Decimal(value.denominator), f'.{places}f')

def up(value: Fraction, lot: Fraction) -> Fraction:
    require(lot > 0, 'INVALID_INCREMENT')
    return -(-value // lot) * lot

def down(value: Fraction, lot: Fraction) -> Fraction:
    require(lot > 0, 'INVALID_INCREMENT')
    return (value // lot) * lot

@dataclass(frozen=True)
class Policy:
    risk_min: Fraction = Fraction('0.005')
    risk_max: Fraction = Fraction('0.0051')
    open_risk_max: Fraction = Fraction('0.05')
    single_notional_max: Fraction = Fraction('0.50')
    gross_notional_max: Fraction = Fraction('1')
    max_open_trades: int = 10
    reward_risk_min: Fraction = Fraction('2')
    entry_fee_rate: Fraction = Fraction('0.001')
    exit_fee_rate: Fraction = Fraction('0.001')
    exit_slippage_rate: Fraction = Fraction('0.0005')
    daily_loss_stop: Fraction = Fraction('0.05')
    watcher_max_age_s: int = 5
    quote_max_age_s: int = 5
    policy_id: str = 'paper500-bracket-new-entry-v1'

    def __post_init__(self):
        require(0 < self.risk_min <= self.risk_max <= self.open_risk_max < 1, 'INVALID_RISK_POLICY')
        require(0 < self.single_notional_max <= self.gross_notional_max <= 1, 'NO_LEVERAGE_POLICY')
        require(type(self.max_open_trades) is int and 1 <= self.max_open_trades <= 10, 'INVALID_TRADE_LIMIT')
        require(self.reward_risk_min >= 2, 'INVALID_REWARD_POLICY')
        require(all(0 <= x < 1 for x in (self.entry_fee_rate, self.exit_fee_rate, self.exit_slippage_rate)), 'INVALID_COST_POLICY')
        require(0 < self.daily_loss_stop < 1, 'INVALID_DAILY_LOSS_STOP')

@dataclass(frozen=True)
class Instrument:
    symbol: str
    lot: Fraction
    tick: Fraction
    minimum: Fraction
    spot: bool = True
    def __post_init__(self):
        require(self.spot, 'DERIVATIVES_NOT_IMPLEMENTED')
        require(self.lot > 0 and self.tick > 0 and self.minimum > 0, 'INVALID_INSTRUMENT')
        require(self.symbol == 'BTC-USDT', 'UNAPPROVED_INSTRUMENT')

@dataclass(frozen=True)
class Bracket:
    quantity: Fraction
    entry: Fraction
    stop: Fraction
    take_profit: Fraction
    stop_model_price: Fraction
    risk_per_unit: Fraction
    planned_risk: Fraction
    planned_reward: Fraction
    notional: Fraction
    entry_fee: Fraction
    nav_at_entry: Fraction
    policy_id: str
    def report(self):
        return {k: decimal(v) if isinstance(v, Fraction) else v for k,v in asdict(self).items()}

@dataclass(frozen=True)
class Exposure:
    cash_available: Fraction
    gross_existing: Fraction = Fraction(0)
    original_open_stop_risk: Fraction = Fraction(0)
    open_trades: int = 0
    start_day_nav: Fraction = Fraction(500)

@dataclass(frozen=True)
class Quote:
    bid: Fraction
    ask: Fraction
    bid_quantity: Fraction
    ask_quantity: Fraction
    observed_at_ms: int
    quote_id: str
    source: str = 'OKX_PUBLIC'
    def validate(self, now_ms: int, policy: Policy):
        require(self.source == 'OKX_PUBLIC', 'UNVERIFIED_MARKET_SOURCE')
        require(0 < self.bid < self.ask and self.bid_quantity >= 0 and self.ask_quantity >= 0, 'INVALID_QUOTE')
        require(isinstance(self.observed_at_ms, int) and bool(self.quote_id), 'INVALID_QUOTE_ID')
        require(-1000 <= now_ms-self.observed_at_ms <= policy.quote_max_age_s*1000, 'STALE_OR_FUTURE_QUOTE')

def size_bracket(nav: Fraction, entry: Fraction, proposed_stop: Fraction,
                 instrument: Instrument, policy: Policy = Policy(), side: str = 'LONG') -> Bracket:
    require(side == 'LONG', 'SHORTS_NOT_IMPLEMENTED')
    require(nav > 0 and entry > 0, 'INVALID_NAV_OR_ENTRY')
    require(entry % instrument.tick == 0, 'OFF_TICK_ENTRY')
    stop = down(proposed_stop, instrument.tick)
    require(0 < stop < entry, 'INVALID_STOP')
    stop_model = stop * (1-policy.exit_slippage_rate)
    cost_in = entry * (1+policy.entry_fee_rate)
    unit_risk = cost_in - stop_model * (1-policy.exit_fee_rate)
    require(unit_risk > 0, 'INVALID_STOP_RISK')
    qty = up(max(nav*policy.risk_min/unit_risk, instrument.minimum), instrument.lot)
    risk = qty*unit_risk
    require(nav*policy.risk_min <= risk <= nav*policy.risk_max, 'LOT_ROUNDING_EXCEEDS_RISK_BAND')
    tp = up((cost_in+policy.reward_risk_min*unit_risk)/
            ((1-policy.exit_slippage_rate)*(1-policy.exit_fee_rate)), instrument.tick)
    reward = qty*(tp*(1-policy.exit_slippage_rate)*(1-policy.exit_fee_rate)-cost_in)
    require(tp > entry and reward >= policy.reward_risk_min*risk, 'INVALID_TAKE_PROFIT')
    return Bracket(qty, entry, stop, tp, stop_model, unit_risk, risk, reward,
                   qty*entry, qty*entry*policy.entry_fee_rate, nav, policy.policy_id)

def gate(bracket: Bracket, exposure: Exposure, quote: Quote, now_ms: int,
         watcher_heartbeat_ms: int | None, instrument: Instrument, policy: Policy = Policy()) -> None:
    quote.validate(now_ms, policy)
    require(bracket == size_bracket(bracket.nav_at_entry, bracket.entry, bracket.stop, instrument, policy),
            'BRACKET_RECOMPUTATION_MISMATCH')
    require(watcher_heartbeat_ms is not None and
            0 <= now_ms-watcher_heartbeat_ms <= policy.watcher_max_age_s*1000,
            'PROTECTION_WATCHER_UNHEALTHY')
    require(all(x >= 0 for x in (exposure.cash_available, exposure.gross_existing,
                               exposure.original_open_stop_risk)), 'INVALID_EXPOSURE_STATE')
    require(0 <= exposure.open_trades < policy.max_open_trades, 'MAX_OPEN_TRADES')
    require(exposure.start_day_nav > 0, 'INVALID_DAY_NAV')
    nav = bracket.nav_at_entry
    require(nav > exposure.start_day_nav*(1-policy.daily_loss_stop), 'DAILY_LOSS_LIMIT')
    require(bracket.entry == quote.ask and bracket.quantity <= quote.ask_quantity, 'ENTRY_NOT_FULLY_EXECUTABLE')
    require(bracket.notional+bracket.entry_fee <= exposure.cash_available, 'INSUFFICIENT_FREE_CASH')
    require(exposure.original_open_stop_risk+bracket.planned_risk <= nav*policy.open_risk_max,
            'TOTAL_OPEN_RISK_LIMIT')
    require(bracket.notional <= nav*policy.single_notional_max, 'SINGLE_TRADE_NOTIONAL_LIMIT')
    require(exposure.gross_existing+bracket.notional <= (nav-bracket.entry_fee)*policy.gross_notional_max,
            'TOTAL_GROSS_LIMIT')

def entry_id(cycle_key: str, strategy: str, instrument: str, origin: str) -> str:
    require(bool(cycle_key) and bool(strategy), 'MISSING_IDENTITY')
    require(origin in {'core', 'exploration'}, 'INVALID_ORIGIN')
    return sha256(json.dumps([cycle_key,strategy,instrument,'OPEN_LONG',origin],
                             separators=(',',':')).encode()).hexdigest()[:32]

def qualifies_for_cycle(cycle_key: str, fills: Iterable[dict], policy: Policy = Policy()) -> bool:
    groups: dict[str,list[dict]] = {}
    for f in fills:
        if (f.get('cycle_key') == cycle_key and f.get('position_effect') == 'OPEN'
            and f.get('trade_origin') in {'core','exploration'} and f.get('simulated_fill') is True
            and f.get('live_order_submitted') is False and f.get('bracket_armed') is True
            and f.get('entry_order_id') and f.get('fill_id')):
            groups.setdefault(f['entry_order_id'],[]).append(f)
    for group in groups.values():
        unique={f['fill_id']:f for f in group}
        if any(f != unique[f['fill_id']] for f in group):
            continue
        first=group[0]
        try:
            risk=sum((number(f['filled_planned_risk']) for f in unique.values()), Fraction(0))
            nav=number(first['nav_at_entry'])
            if (nav > 0 and all(number(f['quantity']) > 0 and number(f['filled_planned_risk']) > 0
                               and f['nav_at_entry']==first['nav_at_entry'] for f in unique.values())
                and nav*policy.risk_min <= risk <= nav*policy.risk_max):
                return True
        except (Blocked, KeyError):
            pass
    return False

@dataclass(frozen=True)
class ExitDecision:
    reason: str | None
    quantity: Fraction = Fraction(0)
    fill_price: Fraction | None = None
    execution_pending: bool = False

def protective_exit(bracket: Bracket, remaining: Fraction, quote: Quote, now_ms: int,
                    instrument: Instrument, policy: Policy = Policy(), latched: str | None = None,
                    depth_available: Fraction | None = None) -> ExitDecision:
    quote.validate(now_ms, policy)
    require(0 < remaining <= bracket.quantity, 'INVALID_REMAINING_QUANTITY')
    require(latched in {None,'STOP_LOSS','TAKE_PROFIT'}, 'INVALID_OCO_STATE')
    reason=latched
    if reason is None:
        if quote.bid <= bracket.stop: reason='STOP_LOSS'
        elif quote.bid >= bracket.take_profit: reason='TAKE_PROFIT'
    if reason is None: return ExitDecision(None)
    available=quote.bid_quantity if depth_available is None else min(quote.bid_quantity,depth_available)
    require(available >= 0, 'INVALID_AVAILABLE_DEPTH')
    qty=down(min(remaining,available),instrument.lot)
    if qty <= 0: return ExitDecision(reason, execution_pending=True)
    price=quote.bid*(1-policy.exit_slippage_rate)
    return ExitDecision(reason,qty,price,qty<remaining)

def recover_bar_exit(stop: Fraction, take_profit: Fraction, open_px: Fraction,
                     high: Fraction, low: Fraction) -> dict:
    require(0 < low <= open_px <= high and 0 < stop < take_profit, 'INVALID_RECOVERY_BAR')
    sl=low<=stop; tp=high>=take_profit
    if sl:
        return {'reason':'STOP_LOSS','reference_price':min(open_px,stop),
                'ambiguous_both_hit':tp,'evidence_mode':'BAR_RECOVERY_ESTIMATE'}
    if tp:
        return {'reason':'TAKE_PROFIT','reference_price':take_profit,
                'ambiguous_both_hit':False,'evidence_mode':'BAR_RECOVERY_ESTIMATE'}
    return {'reason':None,'evidence_mode':'BAR_RECOVERY_ESTIMATE'}
