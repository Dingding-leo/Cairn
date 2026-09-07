# Cairn round: pull, analyze, decide, record, review

Active mode: `GITHUB_CHAT_PAPER_JOURNAL`. This implements the owner's September 7
instruction to run chat-led simulated rounds and record decisions on GitHub.
It is NOT `LOCAL_PAPER_LEDGER`. Do not invoke the host-only `cairn.local_runtime`
command or require TRIGGERcmd, a resident guardian, an exchange demo account,
private credentials, or a paid service for this mode.

## One round

1. Read the current `Dingding-leo/Cairn` main ref and pin its commit SHA. Read
   `AGENTS.md`, this file, and `scripts/cairn_chat_round.py` at that SHA. Pull with
   Git when supported; otherwise retrieve those exact source bytes through the
   GitHub connector and execute them in the current session. A git clone is not
   necessary when a connector can retrieve the source. Do not call a download
   or source read a completed workflow.
2. Read all new journal records since the last reviewed round. Follow the
   predecessor path/blob links from the latest record and preserve the existing
   `cairn-500-usdt-20260906-v1` epoch. Read the original scheduled timestamp from
   the invoking task; CAIRN-NN uses hourly Adelaide minute `4*(NN-1)`. For a manual
   owner-requested run, omit `--scheduled-at`; never invent a missed scheduled
   identity from the wall clock. Check the deterministic cycle path for an
   existing accepted record. Reuse it on retry, do not make another entry.
3. Fetch public OKX data using available read-only tools. Build `market.json`
   with these optional keys, each holding `endpoint`, `retrieved_at_utc`,
   `transport` (`PUBLIC_OKX_GET` or `WEB_PUBLIC_OKX_GET`), and exact JSON `body`:

   | Key | Allowlisted path |
   | --- | --- |
   | universe | `/api/v5/market/tickers?instType=SPOT` |
   | ticker | `/api/v5/market/ticker?instId=BTC-USDT` |
   | books | `/api/v5/market/books?instId=BTC-USDT&sz=5` |
   | candles | `/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=20` |
   | instruments | `/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT` |

   Retain failed-request evidence in a separate `request_failures` key. Do not
   label search snippets, truncated responses, or a handful of tickers a full
   universe scan. Quotes must pass the five-second admission check. Cached web
   responses may be useful observations but are not fresh execution evidence.
4. Execute the source in the current session, using the verified prior bytes:

   ```sh
   python scripts/cairn_chat_round.py \
     --previous previous-round.json \
     --previous-path paper-journal/rounds/ACTUAL_PREVIOUS_FILENAME.json \
     --previous-blob-sha ACTUAL_PREVIOUS_GIT_BLOB_SHA \
     --market market.json --runner ACTUAL_RUNNER_NUMBER \
     --scheduled-at ORIGINAL_TIME_WITH_UTC_OFFSET \
     --source-commit PINNED_MAIN_COMMIT --out next-round.json
   ```

   The arguments above are placeholders, not deployed paths or assumed IDs.
   Use actual values obtained in this round. For a manual run omit the complete
   `--scheduled-at` option. Standard Python 3.11+ is sufficient. No dependency
   installation or paid API call is required by this script.
5. Review the resulting report. The runner screens the returned spot universe
   by USDT turnover for research priority, validates BTC book/confirmed 1H ATR,
   processes observation-based exits before new-entry admission, and evaluates
   the approved BTC exploration sampler. It does NOT invent an approved CORE
   model, perform fundamental valuation, or claim alpha. Existing risk limits
   and modeled 10-basis-point entry/exit fees and 5-basis-point exit slippage
   are retained. New entries use top ask only with sufficient observed size;
   exits share one observed bid-depth budget and an OCO latch. Stops and targets
   are `OBSERVATION_RULES_ONLY`, never `ARMED` continuous protection.
6. Complete the public decision summary and previous-round review with the
   evidence actually obtained. Add any concrete new research or validation
   that was actually performed. A code-level validation audit is useful but
   is not a strategy improvement or proof of profitability. Keep no-change,
   insufficient-evidence, open-outcome, and CORE-unavailable states explicit.
   Never put private internal deliberation in the journal.
7. Persist ONE immutable round file under
   `paper-journal/rounds/<cycle_key>.json`, containing evidence, decisions,
   fills, review and resulting account state together. Use a commit whose sole
   parent is the exact main SHA read in step 1, then update main with
   `force=false`. This is the account writer's compare-and-swap. If another
   writer advanced main, discard the uncommitted outcome, reread state, fetch
   fresh market evidence and recompute; do not merge competing balances. Do
   not use a Contents API write without parent concurrency enforcement for
   account-changing rounds. Never force-push or overwrite earlier rounds.
8. Read the committed file back at the returned commit SHA; verify its bytes
   or blob hash. Only then report GitHub persistence as verified. A local
   `PAPER_ENTRY_RECORDED_LOCALLY_PENDING_PUBLICATION` is not durable success.

## Account continuity and scope

The existing setup record contains unknown cash/NAV/lots. This script has no
initialization or checkpoint-import option. Until a real current checkpoint is
reconciled, rounds still perform available observations, research, review and
recording; new fills are blocked with `CURRENT_ACCOUNT_CHECKPOINT_NOT_VERIFIED`,
not with a fictitious host-access dependency. Do not change `verification` to
make it pass. A reviewed checkpoint needs provenance, the existing epoch,
actual cash, all independent lots with cost basis and original risk, cumulative
fees/realized attribution, sequence, and the recorded Adelaide day baseline.
Its cost-basis accounting must reconcile to historical capital plus realized
net PnL. A prior unknown state cannot be converted to 500 cash by this task.

Tests and synthetic checkpoint fixtures belong only under `tests/`. They must
never be copied into the forward journal as an account or a performance result.
Known unsupported existing holdings must remain visible and block admission;
the initial journal runner supports BTC-USDT spot lots only.

## Scheduling is separate

Never invoke a task-management write from a round. Keep all existing native
recurrences unchanged, including after failure. No GitHub Actions, external
cron, cloud executor or trigger-file commits. This source prompt does not
activate or edit a native task. Only report active state after an actual native
scheduler read. If the old task prompt remains bound to local-runtime mode,
its native task must be updated to this owner-approved journal procedure by
an authorized task-management session; repository publication alone does not
make that change. Do not claim a recurring loop is running merely because a
manual round or a source patch succeeded.
