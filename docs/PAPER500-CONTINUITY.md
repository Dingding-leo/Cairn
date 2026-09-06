# Continuous-operation verification for the 500-USDT epoch

This supplements PAPER500-OPERATIONS.md. It does not alter account capital, trading configuration, the frozen execution code, the original 15 hourly offsets, or any ChatGPT Scheduled Task.

## Read-only monitor

`.github/workflows/cairn-continuity-monitor.yml` runs separately from the fifteen trading workers, at Adelaide minutes 07,22,37,52. It calls `scripts/cairn_continuity_monitor.py` and stores results in `cairn-continuity-<run_id>-<attempt>` artifacts, retained for 30 days. It has only contents-read and actions-read permissions. It cannot trade, reset an account, enable/disable a schedule, or rerun missing trades.

Each check retrieves actual workflow state and scheduled-trigger runs, downloads the newest 500-epoch checkpoint, checks artifact/manifest hashes, validates SQLite integrity, payload hashes and the cumulative audit chain, confirms the genesis capital is 500 USDT, and compares scheduled-run records with persisted local-paper fill evidence.

The reporting window is the latest three hours after deployment, excluding a 20-minute delivery grace period. Grace is an operational monitoring allowance, not a relaxation of the trading engine's quote-freshness or risk limits. A job that was never dispatched cannot be proven from a commissioning fill.

Statuses:

- `WARMING_UP`: no expected slot has reached its monitoring deadline. This is NOT proof of recurrence.
- `PASS_WINDOW`: every due creation-derived slot in the observed window has successful workflow and persisted nonzero paper-fill evidence, and all fifteen workers are enabled. This is NOT an indefinite uptime guarantee.
- `DEGRADED`: a worker is disabled/missing, a slot is missing or unsuccessful, saved evidence is absent, dispatch identity is duplicated, or retrieval is incomplete.
- `VERIFICATION_FAILED`: data, checkpoint integrity, provider access or other required verification failed. No healthy state is assumed.

A completed push/manual/commissioning run never substitutes for a scheduled-trigger run. A successful GitHub job without a persisted nonzero fill does not pass. Monitoring errors fail the job and preserve its report; they never disable the fifteen workers.

## Remaining identity and availability limits

GitHub does not expose a canonical originally intended cron-delivery timestamp through this integration. The engine and monitor explicitly derive schedule slots from the original workflow-run creation time. Delays spanning the next hourly slot cannot be reliably reconstructed as original-time executions. Historical slots must not be filled using new quotes and described as trades that occurred earlier.

The monitor itself is hosted on GitHub and therefore is NOT an independent availability monitor. A GitHub scheduler outage can affect both workers and monitor. GitHub schedules are best-effort, and platform inactivity policies can disable public-repository schedules after prolonged inactivity. No component here guarantees perpetual exact-time operation or automatically defeats a user-disabled schedule.

The fifteen configured trading workers are GitHub Actions workflows, NOT fifteen resumed native ChatGPT Tasks or autonomous LLM research agents. Native ChatGPT schedule state must be verified and managed through a supported account-level task interface; this deployment has not done that.

CORE remains unavailable. Successful local paper execution/accounting and continuity checks are not a completed quantitative investment-strategy cycle, a backtest, exchange-side OKX demo execution, proof of alpha, or proof of profitability.

## Verification of monitoring logic

Six offline regression tests cover commissioning exclusion, grace-period honesty, a disabled worker, successful jobs without fill evidence, a complete scheduled window, duplicate dispatch, incomplete retrieval, and invalid zero/live receipts. These tests contain synthetic monitoring fixtures only, never forward paper trades. The independent checkpoint reader is also checked against the previously downloaded commissioning ledger.

Do not change initial capital again on a retry of the owner's request. Restore the existing `cairn-500-usdt-20260906-v1` account and keep its cumulative audit history.
