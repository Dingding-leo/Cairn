# Local-host handoff (not a deployment claim)

The default checkout now includes the source tree and package metadata from reviewed publication commit e17449f50f76a0eeca92998af0bfe229c65fdf15. No workflow directory was copied. Source publication does not access the owner's computer or start any process there.

## Authorized local operator

1. Use the owner's actual computer connector or existing local Work/Codex session. Establish the machine identity through that tool. Do not substitute the chat container.
2. Identify the existing authoritative account directory and account id from that machine's configuration. Never choose an uploaded test ledger, initialize an account or set cash to 500 as a workaround. Historical capital remains 500, current NAV is not necessarily 500.
3. Pull this repository. With the verified values, execute the read-only check:

    python scripts/cairn_host_check.py --home VERIFIED_SHARED_DIRECTORY --account-id VERIFIED_ACCOUNT_ID --challenge FRESH_RANDOM_ALPHANUMERIC_CHALLENGE

The echoed challenge is evidence of the invocation only, not machine authentication. Confirm the response came from the authorized host interface. The check reads SQLite in read-only mode and validates mode, configured policy, account identity, audit/cash/trade replay, guardian heartbeat/quote age and recovery flag. It does not claim that old-policy migration has been commissioned. A missing database is an error, never a request to initialize one.

4. Separately verify the audited migration/legacy-position history and the OS-supervised guardian. The code does not create that external evidence. Missing migration or recovery evidence blocks new entries.
5. Only after those gates pass, invoke the existing native runner command against the same directory and ORIGINAL scheduled timestamp. Do not replace the original slot with the current clock. No scheduler writes are part of a cycle.

## Native task status

This revision has no native task-management access. It did not restore previously disabled tasks and must not be advertised as 15/15 active. Restore the owner's fifteen existing task IDs, preserving their complete prompts and offsets, only in an owner-authorized session with actual native task-management tools. Do not substitute GitHub Actions or external cron.

## Verification performed for this revision

Locally ran the delivered Cairn_Local_Bracket_Upgrade package's 74 regression tests plus 13 new host-check tests: 87 passed using temporary synthetic fixtures. The new diagnostic source/tests are published here. No forward paper trade, local host deployment, migrated-account readback, guardian uptime, or native scheduled invocation is certified by that test run. The publication source tree was copied without changing its trading logic; the full repository suite and OS deployment have not been re-certified.

Existing release gates remain: supported host connection, preserved authoritative account migration, resident guardian supervision and recovery, actual native task wiring, and a forward bracketed entry/exit with durable readback. CORE is still unavailable. The connector offered in chat requires owner authorization; it is not installed by this source commit. No payment, paid execution, live-order transport, account reset or schedule mutation was performed.
