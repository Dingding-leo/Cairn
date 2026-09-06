# Superseding policy: local bracketed PAPER trading

Owner revision, 2026-09-06. This supersedes the GitHub Actions deployment and micro-notional entry/exit sampler in PAPER500-OPERATIONS.md. It is NOT a claim that a local replacement has already been installed.

## Non-negotiable requirements

1. No GitHub Actions for scheduling, execution, testing or runtime persistence. GitHub stores source/config/tests/docs only. All 19 workflow definitions were removed from main and preserved outside .github/workflows in commit 6ebec5299af01a815a345f85ec91038c4fdec242. Repository-wide Actions administration and historical-branch definitions are separate: the owner can disable Actions in repository settings. No existing artifacts/history were deleted.
2. ONE shared account, historical initial capital 500 USDT. Preserve current state and PnL. Do not reset an account at each cycle or allocate 500 to each worker.
3. At least ONE NEW qualifying entry per eligible cycle, not merely a held position or any execution. An exit, stop fill, TP fill or older cycle's entry does not count. A new entry that subsequently closes during its own cycle still counts. Every trade is a separate logical lot with its own IDs, entry, SL, TP and PnL; several BTC lots may coexist.
4. Each new entry has at least 0.50% current NAV of planned loss at the ORIGINAL stop, including declared entry/exit fees and exit slippage. At NAV 500 the risk floor is 2.50 USDT, not a 2.50-USDT notional. Use the smallest valid lot meeting the floor; default ceiling 0.51% NAV solely allows rounding. Reject infeasible sizing instead of weakening the floor or raising risk indefinitely.
5. Choose a strategy/experiment stop BEFORE quantity. Every new entry must atomically arm both stop-loss and take-profit, with at least 2R net modeled reward. Existing 0.25%-position-notional and 0.50%-sleeve-notional caps are superseded by this stop-risk policy, not applied in conflict with it.
6. Additional reference defaults: original open-stop-risk reservations <=5% NAV, max 10 open trades, per-entry notional <=50% NAV, total spot gross <=100% NAV, no leverage/shorts/derivatives, 5% marked daily loss halts new entries. Risk-reducing exits remain enabled. Capacity/data failures override activity and are reported; do not close/reopen trades just to satisfy a quota.
7. Resident LOCAL protection service, targeting one-second quote observation and <=five-second healthy heartbeat/quote age. Hourly LLM tasks do not monitor stops. New entries are blocked during stale/missing protection or unresolved recovery. OCO state must prevent double-closing, handle partial exits and consume shared depth only once. Gaps/slippage can exceed planned stop loss; do not fabricate a fill exactly at the stop.
8. Fifteen separate native ChatGPT recurring tasks at Adelaide offsets 00,04,...,56, if supported by the owner's actual account. They must use the same verified local host/service. Do not assume cloud ChatGPT can reach localhost. Complete each cycle without disabling its schedule; unavailable runtime means blocked execution, not a substitute hosted workflow.
9. Strict LOCAL_PAPER_LEDGER labels: simulated_fill=true, live_order_submitted=false. Public OKX market data only. No private/live order transport. CORE remains unavailable unless a real reviewed model is integrated. Exploration is not CORE alpha, and a bracket execution is not a completed investment-research cycle.

## Implemented in the delivered local source package

- bracket_policy.py: exact rational stop-based sizing, cost-aware 2R targets, independent risk gates, new-entry qualification and conservative protective decisions.
- bracket_ledger.py: separate durable trade lots, atomic entry/bracket/cash updates, OCO exit latching, partial exits, shared depth limits, retry identity and cash/fill/trade audit replay.
- local_runtime.py: local CLI and resident public-data guardian; no remote endpoint and no native task creation.
- 74 local synthetic tests passed, including offline CLI cycle/retry, concurrent same-cycle calls, multiple open lots, exits not counting, stop gaps, partial OCO exits and persistence failures. No GitHub Actions were used for these tests. No forward paper trade was submitted in this delivery.
- Full setup prompt and 15 self-contained native task prompts are included in the download, together with a local-host deployment prompt and workflow review.

The source package was delivered as a downloadable artifact, not deployed to the user's computer or silently substituted for the existing running account. The legacy-state importer, OS process supervision, supported host connection from Scheduled Tasks, complete operational dashboard, automatic gap-recovery/re-arming and production CORE integration remain release gates. The account was not migrated/reset and no native tasks were created/resumed by this revision.

## Release order

Stop/retire disallowed runtime -> preserve authoritative current paper state -> locally integrate and test the supplied source -> perform an audited policy/ledger migration without resetting capital -> supervise and validate the continuous guardian -> verify native task access to that exact host -> create/update the fifteen tasks -> prove bracketed forward paper entries, TP/SL exits, retry safety and accounting -> evaluate CORE only after actual validated model integration.

Do not advertise perfection, continuous uptime, active native tasks, genuine OKX demo-account fills or investment edge without evidence for those specific claims.
