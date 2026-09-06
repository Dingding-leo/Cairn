# Owner instruction: no GitHub Actions

Effective 2026-09-06. All 19 workflow definitions were removed from main's `.github/workflows` and preserved unchanged under `docs/retired-github-actions-20260906` for audit. That archive is documentation, not an executable workflow directory. Do not recreate schedules, workflow-dispatch triggers, test workflows, or artifact-backed runtime state. GitHub is source control only.

This change removes the default-branch execution definitions. It does not cancel jobs that were already queued/running, delete retained artifacts, or claim repository-wide Actions administration settings were disabled. The connected tools do not expose Actions cancellation/administration. The owner can additionally disable Actions in repository Settings > Actions > General and cancel active runs; preserve/download any required history first. Historical branches may still contain workflow files: do not manually dispatch them.

Replacement target: 15 separately configured ChatGPT hourly tasks supervising ONE persistent local paper-trading engine and continuous TP/SL watcher. No paid host/API or alternative scheduler may be provisioned without owner approval. Native task setup prompts are supplied separately; never claim tasks were activated merely because prompts exist.

Initial paper capital remains 500 USDT. New policy: >=0.50% planned account loss at the original stop per NEW entry (including modeled fees/slippage), protective stop and take-profit required, and one qualifying NEW entry per eligible cycle. Holding an old position or closing one does not satisfy the new-entry requirement. Safety/capital limits override activity. Do not run the retired micro-position entry/exit logic under the new policy or fabricate a CORE model.
