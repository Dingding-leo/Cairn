# Cairn simulated trading journal

## Owner-authorized mode — 2026-09-07

The owner explicitly requested chat-led simulated trading: make decisions using real market observations, record simulated trades, and review them next round. The owner then authorized recording the process on GitHub. This supersedes the older source-only storage restriction for this journal. No exchange demo account, trading credentials, or local execution host is required to WRITE this journal.

GitHub is storage, not a scheduler or trading executor. No GitHub Actions, paid runtime, or live orders are authorized by this change. No recurring task was created or verified by this setup.

## Records

Use one immutable JSON record per round under `paper-journal/rounds/<UTC-cycle-id>.json`. Include the previous record's path and blob SHA. Use a single writer; if the head has changed, re-read and reconcile before committing. Do not run concurrent account writers. Never overwrite earlier rounds; append explicit corrections. Commit the decisions, simulated fills, review, and resulting account state together in ONE round file and read it back before claiming persistence.

Each trading round must contain:

- Unique cycle ID, actual UTC observation/decision times, strategy version, and previous record.
- Market source URLs/endpoints, source timestamps, retrieved prices, spread/depth where available, scan universe, returned count, exclusions, and data gaps. Claim a full scan only when the stated universe was actually covered.
- Starting cash, individual position lots, cost basis, and prior account sequence, reconciled to the previous accepted record.
- Concise decision rationale: evidence, assumptions, alternatives, invalidation conditions, and uncertainty. Record an auditable decision summary, not private internal deliberation.
- At least one NEW simulated entry per eligible round. Quota cannot override missing data, unavailable cash, or account risk limits. Mark quota entries as exploration, separate from strategy-selected entries.
- Quantity, observed reference price, modeled execution price, explicit fees/slippage assumptions, stop and target, expected risk, and a `simulated_fill: true` / `live_order_submitted: false` label.
- Updated cash, lots, realized and unrealized PnL net of modeled costs, NAV and drawdown. Use exact decimal arithmetic and distinguish unknown marks from zero values.
- Prior-round outcome review: observed price movement, costs, execution-model effects, thesis status, and uncertainty. Open trades are pending outcomes. One win or loss does not establish causality or profitability.
- One concrete improvement activity per round: hypothesis, evidence, change or experiment, evaluation criterion, result or pending status, and rollback condition. Do not claim every change helps; preserve the baseline and avoid promoting changes on a single outcome.
- Limitations, failure codes, quota status, and whether a complete trading cycle actually occurred.

## Account continuity

Historical account epoch: `cairn-500-usdt-20260906-v1`. Historical starting capital: 500 USDT TOTAL. This is not proof of current cash or NAV. Do not reset, silently import the older 100,000-USDT epoch, or allocate capital per runner. A verified current checkpoint is required before account-affecting simulated fills.

Owner-approved margin policy (2026-09-07): long-only simulated spot borrowing, maximum gross leverage 100x; per-entry planned stop risk 0.50–0.51% NAV including costs; modeled target >=2R net; aggregate original stop-risk reservations <=5% NAV; at most 10 open lots; per-entry notional <=50% NAV; gross exposure <=100 times post-fee, bid-marked equity; 5% marked daily loss blocks new entries. Planned stop risk is not guaranteed maximum loss.

## Observation-based exit model

This chat journal has no continuously running stop monitor. Stops and targets are simulated decision rules, not exchange orders or continuously protected brackets. Check positions at each actual observation. Without a complete timestamped price path, do not invent intervening trigger times or fills at a stop/target price. Record a detected exit using the current observed executable side plus declared adverse costs; preserve the unobserved interval. Any later candle-based reconstruction must be labeled reconstructed and kept distinct from forward observations.

## First record

See [2026-09-07-setup.json](rounds/2026-09-07-setup.json). It records setup and unresolved account continuity, not a market scan or trade.

## Simulated leverage accounting — v2

The owner requested **100x maximum**, not a target leverage. Existing per-entry notional <=50% NAV, <=10 lots, aggregate original stop risk <=5% NAV and per-entry planned risk 0.50–0.51% NAV remain binding, so actual permitted exposure can be far below 100x. Existing unleveraged lots retain their original brackets and cost basis. Missing debt fields in a valid v1 checkpoint mean zero existing debt, not a balance reset.

Only the cash shortfall of a new entry is borrowed. `borrowed_usdt` is deducted from equity: cash + bid-marked assets - debt. Cash from exits repays debt before additional borrowing. Exact cost-basis continuity is cash + remaining cost basis - debt = 500 + cumulative realized net PnL.

Declared simulation assumptions, **not OKX account terms**: borrowing APR 10%, accrued over the actual observation interval and added to debt, with cumulative financing costs recorded separately and debited to EXPLORATION realized PnL. The maintenance threshold is equity/gross <=0.5%; detected breaches latch observation-based liquidation exits using the current bid, shared available depth, 5bp adverse slippage and the modeled exit fee. Partial exits keep their liquidation latch. Gap losses and residual debt are preserved, including negative equity.

For each new v2 entry, planned stop risk and net 2R target include a conservative 3bp/24-hour financing reserve on full notional (including a buffer for borrowing the entry fee). New lots have a 24-hour observation-based time exit. Actual exit occurs at the next available observation, so delayed runs can exceed this financing allowance and planned loss. Older lots keep their existing exit rules. No continuous protection, live loan, futures position or exchange liquidation fidelity is claimed.
