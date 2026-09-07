# Cairn operating boundary

## Owner revision — 2026-09-07: GitHub chat paper journal

The owner explicitly selected chat-led simulated trading and instructed: "just record your processes on github". For `GITHUB_CHAT_PAPER_JOURNAL` mode, GitHub may store decision summaries, public market evidence, simulated account state, and round reviews under `paper-journal/`. Follow [paper-journal/README.md](paper-journal/README.md).

This supersedes the source-only / no-Git-state restrictions below ONLY for that owner-authorized simulated journal. A local host, official OKX demo account, and continuous guardian are not prerequisites for writing journal records. Do not claim continuous protection: journal stops/targets are observation-based simulated rules, not armed broker orders. Preserve existing capital, reconcile the current checkpoint before simulated account mutations, retain risk gates, and never fabricate prices, fills, outcomes, or execution times. No account reset is authorized.

No GitHub Actions, paid execution, live orders, scheduler-limit workaround, or schedule activation is authorized by journal storage. Never confuse a journal commit with a trade or a running schedule. The local-runtime requirements below still apply when actually using the local-runtime mode; they must not be used to mislabel chat-journal setup as a failed host deployment.

## Previous local-runtime operating boundary

This repository is SOURCE, not a remote executor or an authoritative account database.

## Non-negotiable

- Never use GitHub Actions, workflow artifacts, Git commits as a runtime database, paid model APIs or paid execution services.
- A scheduled invocation may NEVER invoke a scheduling write action: no disable, pause, delete, rename, recurrence edit, or create. Ending or blocking ONE run is not permission to stop its recurring task. Only an explicit owner task-management request authorizes changes.
- Never state a schedule is active without reading its actual state. If task-management tools are unavailable, report UNVERIFIED; do not claim restoration.
- Historical capital is 500 USDT TOTAL. Do not initialize, rebase, reset, silently import a chat attachment, or allocate new capital per worker.
- Use the owner's actual connected host, existing migrated account and continuously running guardian. A successful source pull or a fresh sandbox Python process is NOT host access or deployment.
- Do not run init in an hourly task. Never manufacture a heartbeat or fill. Never count a test fixture as a forward paper observation.
- Each eligible cycle requires a NEW bracketed entry with 0.50-0.51% current NAV planned stop risk including costs, TP >=2R net, and atomically armed SL/TP. Exits and carried positions do not satisfy the quota. Retain account-wide capacity and daily-loss gates.
- Respect the owner's latest approved policy and full runner prompt. This file is not a substitute for risk validation, position accounting, or current runtime configuration.
- A successful component test is not a successful full-cycle trading run. CORE_UNAVAILABLE is not proof of alpha.

## Source layout

The existing publication runtime is now available in main under src/cairn. It was copied from publication commit e17449f50f76a0eeca92998af0bfe229c65fdf15 without its .github/workflows directory. No workflow is required to clone or execute source on an authorized host.

scripts/cairn_host_check.py is a read-only diagnostic. Its challenge echo binds output to the invocation but does not authenticate machine ownership. A supported computer connector must independently establish which host executed it. It does not migrate or initialize any account, start a guardian, or create a trade.

## Honesty of operational results

Without actual host command execution and shared-ledger readback, report BLOCKED_RUNTIME_ACCESS_NOT_CONFIGURED. Do not claim 'working', 'deployed', 'all workers running' or 'trade recorded'. Preserve the recurring schedule unchanged. Keep real receipts and account data off GitHub.
