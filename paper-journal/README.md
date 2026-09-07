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

Existing risk constraints remain: spot-only, no leverage/shorts; per-entry planned stop risk 0.50–0.51% NAV including costs; modeled target >=2R net; aggregate original stop-risk reservations <=5% NAV; at most 10 open lots; per-entry notional <=50% NAV; spot gross <=100% NAV; 5% marked daily loss blocks new entries. Planned stop risk is not guaranteed maximum loss.

## Observation-based exit model

This chat journal has no continuously running stop monitor. Stops and targets are simulated decision rules, not exchange orders or continuously protected brackets. Check positions at each actual observation. Without a complete timestamped price path, do not invent intervening trigger times or fills at a stop/target price. Record a detected exit using the current observed executable side plus declared adverse costs; preserve the unobserved interval. Any later candle-based reconstruction must be labeled reconstructed and kept distinct from forward observations.

## First record

See [2026-09-07-setup.json](rounds/2026-09-07-setup.json). It records setup and unresolved account continuity, not a market scan or trade.
