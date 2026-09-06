# Cairn paper-cycle audit and acceptance contract

Date: 2026-09-06. Audited release baseline: `50b4e081658bc4de1f53f9066a69c2b0e41b865e`
on `publication/v0.5.0rc1`. Audited default branch: `038561b98242be5139c3472934f7f2b5f46bfd91`.

**Operational verdict: NOT READY for unattended OKX Demo Trading.**
This is a code review and proposed evidence guard, not a deployment, schedule update,
OKX authentication test, or a completed paper-trading cycle. No real or demo order
was submitted during this review. Unit-test receipts are synthetic test fixtures
and MUST NOT be imported into any trading/performance database.

## Findings

1. `main` contains README.md and an upload-session document, not the executable release.
   The code is on `publication/v0.5.0rc1`. An unpinned repository URL is not an executable
   production baseline. Promote the release only after review, or explicitly deploy a
   reviewed immutable commit; never silently chase main during a trading cycle.
2. `cairn demo` writes `mode=SYNTHETIC`, zero orders and zero network calls. It is a
   fixture smoke test, not an authenticated exchange demo runner.
3. `OKXPublicClient` deliberately has public GET endpoints only. There is no authenticated
   demo order transport. A healthy public endpoint does not establish demo-account access.
4. `paper.py` is an in-memory, long-only spot accounting primitive. It does not provide
   durable broker execution, an exploration sub-ledger, derivatives accounting or a
   deployed quantitative strategy. Do not enable short/perpetual orders with this ledger.
5. `Store` supplies SQLite transactions, immutable records and an audit chain, but creating
   a fresh local database per chat run does not supply shared persistent trading state.
   There is no verified, configured execution host/database in this review.
6. Different cycle/client IDs do not prevent economic duplicates or account races. Runners
   can overlap, read the same portfolio and submit competing actions. Serialize mutation
   of one shared account and re-read positions, pending orders and NAV under that lock.
7. The prior CAIRN-04 run disabled its schedule. An operational failure must halt that
   execution only, not disable/rename/delete any task or alter its recurrence. Current
   task-management tools are unavailable to this reviewer; no schedule was modified here.
8. Prompt-level instructions to record a fill are not execution or persistence evidence.
   A submitted/acknowledged order, proposed trade, fixture, reused old fill or copied report
   cannot satisfy the per-cycle activity target.
9. Long research/backtest work in every four-minute invocation can block execution. Run
   bounded research review after trading/accounting commits and release the account lock;
   record deferred/no-eligible-research outcomes honestly. Never hot-swap the core strategy.

## Enforceable success contract

Each scheduled invocation attempts one full Cairn cycle. The original 15 separate
hourly tasks keep offsets `00,04,08,12,16,20,24,28,32,36,40,44,48,52,56`, Adelaide time.
This is 15 attempts/hour, not a promise of 15 fills under failures.

A healthy, eligible, connected cycle targets at least one non-zero confirmed paper fill.
It may report COMPLETE only after the fill and its ledger/accounting effects are committed,
all required stages are recorded, reconciliation matches, order lifecycle ambiguity is
resolved, and the final report is read back from the shared database.

If a genuine fill cannot be obtained, record HALTED, BLOCKED or INCOMPLETE_NO_FILL with an
exact reason. Do not weaken risk/data checks, fake a trade, reset an account, reuse another
cycle's trade or turn a fixture into an execution to meet the target. Once a fill exists,
retain it even if later reconciliation or accounting halts the cycle. `minimum_satisfied`
and `cycle_status` are separate facts.

## Proposed evidence guard: scope and limits

`src/cairn/cycle_guard.py` adds namespaced tables to a pre-existing SQLite database.
It supplies immutable, checksummed intent/fill/stage/report records, retry-stable 32-character
client IDs, cross-runner account locking, quantity/overfill validation, unique venue-trade
receipt handling, distinct filled-order counts, core/exploration separation and report
read-back. Stage hashes must match stored stage artifacts; a caller-supplied hash alone
cannot certify completion. A non-zero partial fill can satisfy activity, but remaining
orders must be explicitly reconciled/resolved before a complete cycle report.

The guard is NOT a broker adapter, strategy engine, fill simulator, portfolio-risk engine,
reconciliation implementation, credential verifier, remote service, queue or scheduler.
`OKX_DEMO` labels and hashes do not authenticate receipts. The real adapter must verify the
environment/account/instrument/side, confirm fills using the venue, check timestamps,
retain redacted source evidence, and invoke the guard only with real observations.
Stage-result correctness still belongs to deterministic components and their conformance tests.
The new table checksums are not an independently anchored tamper-proof audit system.

The existing CLI is unchanged: this PR does NOT add a `run-cycle` command and does NOT
wire the 15 tasks to the guard. Integration and deployment are explicit outstanding gates.
The guard rejects post-finalization order/fill changes. Late events require a separate
append-only amendment; do not change the historical report.

SQLite support is for ONE persistent host. Multiple containers with separate disks, copied
SQLite files or a network-filesystem database are not supported shared-account deployment.
A hard process crash leaves the account lock for recovery. Do not steal a lock on elapsed
time alone. A controlled exception may release the lock, so the runtime MUST globally check
and resolve all persisted unknown/open orders before admitting any subsequent cycle.
If lock acquisition fails, write an invocation/attempt incident through the host's durable
incident/outbox path, without overwriting a still-running cycle's final report.
If persistence is unavailable, emit a redacted failure through the external monitor and
state explicitly that database recording failed. No software can honestly claim durable
recording while the storage service is unavailable.

## Canonical full-cycle runtime contract

### Identity and startup

Use the scheduler's ORIGINAL timezone-aware scheduled timestamp, not the retry's current
wall-clock minute. Keep the requested display ID `YYYY-MM-DDTHH-mm-CAIRN-NN`. Also persist
`scheduled_at_utc`, `cycle_key`, account alias, runner ID, code SHA and configuration SHA.
The UTC-based primary key distinguishes the repeated Adelaide hour at daylight-saving end.
Resolve an existing cycle/attempt before doing work. Never reset balances or erase history.

Connect all runners to the same durable service and configured account. Require a pinned,
reviewed active strategy configuration; absence of an approved strategy is a blocker, not
an excuse to invent signals or silently declare the strategy "no trade".

Acquire a shared account lock before portfolio-dependent decisions. Reconcile previous
unknown/open orders before accepting a new cycle. Verify account identity, ledger sequence,
NAV, configuration, instrument support and demo mode.

### Market data and deterministic decisions

Fetch real OKX data directly, not cached search-engine quote snippets. Validate timestamps,
completeness, symbols, spreads, price positivity, contract/lot/minimum sizes and order-book
integrity. Recheck the executable quote and risk state immediately before each order.
Use separately declared freshness rules for quotes, books, instrument metadata, funding and
completed 1H bars. A quote's 120-second limit is NOT a candle-age limit. The latest completed
1H candle can legitimately be nearly an hour old; verify its expected exchange-bar boundary.
Candle closes are not automatically the Adelaide hourly `:00` scheduler boundary.

Run validated features, the frozen alpha model, portfolio targets and an independent
risk engine. Keep the core model's approved timeframe and rebalance policy. Fifteen runs
in one hour must not reinterpret the same hourly signal as fifteen independent bets or
inflate the IC sample size. Compare targets with filled AND pending quantities. Use an
additional economic-action identity (strategy, signal epoch, instrument, target/state version)
to prevent duplicate core exposure even across different cycle IDs.

### Execution and activity fallback

Use the authenticated OKX demo adapter only. Read secrets exclusively from the secure
runtime mechanism. Every private request must be hard-bound to the demo environment, with
no live fallback. Verify a read-only authenticated demo response before any order request.
Do not add keys, headers or signed requests to code, prompts, logs or test artifacts.

1. Execute independently risk-approved CORE orders; tag `trade_origin=core`.
2. Persist the intent BEFORE submission. On a timeout or retry, look up that same client
   ID and ingest its actual state; never blindly resubmit an uncertain order.
3. Poll within a bounded execution window. Acknowledgement is not a fill. A confirmed
   non-zero CORE fill satisfies activity. Resolve/cancel remaining quantities according
   to the approved lifecycle. Do not create an exploration trade merely because a passive
   core order has not yet been observed filling.
4. Only when no qualifying fill exists and core lifecycle ambiguity is resolved, select
   one predeclared informative exploration experiment in the approved liquid universe.
5. Apply the SAME independent risk gate to that exploration order. At rounded lot size,
   each exploration position must be <=0.25% of total account NAV gross; the entire
   exploration sleeve must be <=0.50%, INCLUDING outstanding-order reservations. These
   caps apply to all 15 runners combined, not independently to each runner. Closing or
   reducing an existing exploration position is preferable near the cap. If minimum
   order size exceeds the cap, report NO_FEASIBLE_EXPLORATION_SIZE; do not round upward.
6. For a fill-targeting experiment, an approved bounded marketable/IOC order can be more
   appropriate than an indefinitely resting maker order. Even that cannot guarantee a
   fill through an outage or liquidity failure. Respect price protection and record
   execution type; do not call IOC/taker evidence a maker experiment.
7. Confirm the fill from the demo broker, persist its unique trade/order/client IDs,
   cycle, instrument, origin, side, quantity, price, timestamp, fees and experiment ID.
   Duplicate partial-fill messages count once. Never count an older cycle's fill twice.

### Accounting, reports and research

Keep separate virtual CORE and EXPLORATION quantities, average costs, PnL, fees and funding
allocations. Do not infer sleeve ownership from netted broker positions. Reconcile the sum
of virtual sleeves to the demo account; aggregate gross exposure before virtual netting.

Check `previous_NAV + core_PnL + exploration_PnL + external_cashflows = current_NAV` within
the declared tolerance. Use actual fill prices; do not deduct spread/slippage twice when
already embedded in those prices. All components must use the same valuation timestamps.

Compute performance deterministically. Sharpe, IC, hit rate and drawdown must have explicit
sample windows and definitions. Insufficient history is `null / insufficient_data`, not an
invented zero or positive statistic. Exploration observations never enter core trade counts
or core Sharpe. More four-minute cycles do not create independent hourly return observations.

Always finalize an honest cycle/attempt outcome. The human summary is rendered from the
committed machine report, not recomputed by the LLM. Include order and fill counts, receipt
IDs, experiment, code/config/data provenance, NAV and PnL where available, stage outcomes,
reconciliation, storage confirmation, blockers, and whether activity was satisfied.

The recurring task must leave its own and all other schedule settings unchanged. It may
halt the current execution only. Only the user authorizes pausing or disabling recurrence.
Research may create controlled branches/PRs but must not self-promote an unreviewed strategy.

## Deployment acceptance: all still require actual verification

- Reviewed full-cycle driver wired to deterministic components and this evidence guard.
- Authentic OKX demo-only transport with negative live-mode/redirect/environment tests.
- Secure demo credentials and confirmed account configuration on the execution host.
- Shared durable datastore with restart recovery, global pending-order checks and an outbox.
- Frozen approved core strategy, feasible approved exploration experiment and instrument sizes.
- Reconciliation and separate sleeve accounting, including fees/funding as applicable.
- All fifteen actual task prompts wired to that same verified driver, with CAIRN-04 resumed.
- Real end-to-end proof: one genuine core/no-core cycle as appropriate, one genuine exploration
  fill when needed, a replay producing no extra order, two overlapping invocations, and a
  fresh-process read-back of receipts/accounting/report. No unit fixture counts as this proof.

## Authoritative external references

OKX API v5: https://www.okx.com/docs-v5/en/ (demo requests require `x-simulated-trading: 1`).
OKX API FAQ: https://www.okx.com/help/api-faq (demo API key/environment must match).
ChatGPT Tasks: https://help.openai.com/en/articles/10291617-tasks-in-chatgpt
(task management and recurrence; task configuration is distinct from runtime deployment).

## Review verification

Focused module tests are run locally and use synthetic unit fixtures only. Full-repository
lint, mypy, coverage matrix and CI remain separate results; do not inherit historical test
counts from the larger release archive. No deployment or genuine demo fill is certified by
this pull request. No active strategy, live transport or scheduled task is changed.
