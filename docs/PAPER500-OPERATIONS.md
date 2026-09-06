# Cairn 500-USDT paper operations

## Scope and authority

Owner request, 2026-09-06: reduce initial paper capital to 500 and repair continuous operation of 15 workers. Currency is USDT, consistent with the existing BTC-USDT ledger. This is a NEW account epoch, `cairn-500-usdt-20260906-v1`, not a scaled or rewritten 100,000-USDT history.

The available interface could not modify ChatGPT Scheduled Tasks. These fifteen workers are **separate GitHub Actions hourly workflows**, not restored ChatGPT account-level Tasks and not fifteen LLM research agents. No native ChatGPT task was enabled or disabled by this deployment. Never report that they were.

The source used by every worker is pinned to `4aeb5920ac81875b92b636d330e645170d429f59`. Python 3.11 and 3.13 hosted validation passed: 92 full regression tests; 56 focused tests; 98% focused new-engine coverage. Full-repository strict lint/type checks were not certified. Test fills are synthetic fixtures, not forward-trading evidence.

## Scheduling

CAIRN-01 through CAIRN-15 each have their OWN hourly schedule, Adelaide timezone, at minutes 00,04,08,12,16,20,24,28,32,36,40,44,48,52,56. Each calls the same pinned deterministic engine; these are not fifteen stages of one cycle. No worker has schedule-write permissions or self-disabling logic. Each failure ends only that invocation.

All mutations serialize through concurrency group `cairn-paper500-account`, `queue: max`, `cancel-in-progress: false`. This avoids the old single-pending concurrency cancellation problem. New deployments trigger clearly labelled commissioning cycles; these must not be called scheduled executions. Retries reuse the original GitHub run creation identity, not a mutable repository marker or the retry's wall clock. UTC keys distinguish repeated Adelaide daylight-saving wall times. GitHub does not expose an authoritative originally intended cron delivery timestamp here; schedule slot attribution is explicitly derived from run creation time. Invocations delayed more than 20 minutes after creation halt rather than pretend to trade at their nominal time.

GitHub schedules are best-effort: delays/dropped triggers are possible, and public-repository scheduled workflows can be disabled by GitHub after 60 days with no repository activity. Therefore this is not an exact-time, perpetual-uptime guarantee. Monitor Actions failures and expected-versus-observed runs. The current deployment adds no automated repository-touch keepalive and no external SLA monitor.

## Capital and risk

Initial state is exactly 500 USDT cash, zero positions and sequence zero. Initialization is explicit and refuses overwrite. Normal execution MUST restore the newest correct-epoch checkpoint; a missing/expired/corrupt checkpoint halts, with no automatic reset to 500 or 100,000. Legacy `cairn-shared-state` artifacts are never consumed by the new epoch. The old state artifact 9989391508 from run 34033509877 was separately downloaded and preserved; its history is unchanged.

Exploration position maximum: 0.25% NAV (initially 1.25 USDT). Total exploration maximum: 0.50% NAV (initially 2.50 USDT). These are shared-account limits, not per-worker budgets. The old implementation incorrectly treated the position rule primarily as a single-order rule. The new independent risk check enforces the post-fee position limit. When the normal 0.1% target is below OKX's minimum, use the smallest valid lot ONLY if the full post-fee risk limits still pass. Otherwise halt with an explicit infeasible-size reason. Keep the existing approved BTC-USDT spot universe; do not invent a new universe to force a fill.

Exploration is controlled entry -> observation -> full exit, rather than endless accumulation up to a shared ceiling. Fees are an explicit conservative 10-bps assumption, not an observed or verified OKX account fee. The changed fee assumption belongs only to this new epoch.

## Truthful execution and strategy reporting

Execution is `LOCAL_PAPER_LEDGER`, `simulated_fill=true`, `live_order_submitted=false`. Only four allowlisted public OKX GET endpoints are available. Redirects are rejected. There are no private endpoints, exchange keys, broker orders, withdrawals or live-money transport. A local simulation is NOT an authenticated OKX demo-account fill.

The published CORE alpha remains unavailable. The new runner does not fabricate alpha or claim research is complete: `full_strategy_cycle_completed=false`, `scope=EXPLORATION_EXECUTION_ONLY`. CORE orders/fills remain zero, Sharpe and IC unavailable, and the validation stage records no strategy promotion/backtest. This system currently tests operational paper execution/accounting, not investment edge. Do not label its output a fully functioning autonomous quantitative investment strategy.

## Evidence and accounting

Persist exact rational cash/quantity/cost/NAV values in one cumulative SQLite ledger. Stage records, fill, next account state and report commit together. Validate SQLite integrity, all payload hashes, audit-chain coverage, epoch/config hash and contiguous account sequence. Retry idempotency is not truncated after 100 cycles. Concurrent invocations cannot apply two transitions from the same starting state.

Market validation rejects stale/future quotes, crossed/off-tick/unordered books, inadequate depth, missing/duplicate/gapped/unconfirmed 1H candles, incorrect expected last completed UTC candle, invalid OHLCV, inadequate capital and unsupported positions. Executable book price and available quantity come from the same book snapshot, checked immediately before applying the local fill.

PnL includes both inter-cycle mark-to-market and current execution fees/spread; the old same-quote pre/post-only report omitted the former. CORE remains separated. State replay and record checks do not constitute independent exchange reconciliation: broker reconciliation is explicitly not applicable.

A local committed cycle has `LOCAL_COMMITTED`, not an uploaded-success claim. The workflow then uploads the complete account checkpoint and cycle output, downloads both by returned artifact IDs, validates the GitHub ZIP digests, opens the uploaded ledger, matches the saved report and confirms a nonzero fill, safety labels and reconciliation. Only the delivery acceptance receipt may say `COMPLETED` with `remote_persistence_verified=true`.

Artifact names:
- State: `cairn-state-cairn-500-usdt-20260906-v1` (cumulative ledger plus manifest).
- Cycle: `cairn-cycle500-<run_id>`.
- Verified acceptance: `cairn-acceptance500-<run_id>`.

Artifacts request 90-day retention. Each new state checkpoint contains the cumulative ledger, not only the latest 100 cycles. This is still artifact-backed persistence, not a managed database: provider limits, growing checkpoint size and long-run read/verification costs require monitoring and eventually a durable database/object-store deployment. If storage cannot be verified, do not trade or claim success.

## Remaining gaps

No functioning CORE strategy, real exchange-demo adapter, calibrated queue/impact model, meaningful CORE performance history or perpetual scheduler SLA is certified. This repair does not imply profitability or perfection. Preserve failures and legacy results; use controlled research/validation to qualify a future CORE strategy before enabling it.
