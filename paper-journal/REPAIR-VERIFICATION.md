# Chat-round repair verification — 2026-09-07

Implemented a stateless, dependency-free session runner in
`scripts/cairn_chat_round.py` for the already owner-approved GitHub chat journal.
The resident-host execution path is unchanged and is not used by this mode.

Validation actually performed in the development chat container:

- Python compilation of the new script.
- `python -m unittest discover -s tests -p test_chat_round.py -v`
- **35 tests passed**, zero failures/errors. All test market/account inputs are
  synthetic and are not forward observations or authoritative account state.

Covered: new exploration entry, original stop-risk band, net 2R after costs,
unknown-state preservation, missing/stale/future market data, duplicate and
non-latest cycle retries, correct manual/scheduled identity, UTC identity across
DST, invalid decimals, invalid source endpoints, lot rounding, confirmed/gapped
candles, wrong account epoch, reconciled cost-basis identity, daily loss/no reset,
partial exits, reduce-only OCO behavior, bid-depth limits, fees, and exit activity
not counting as a new entry. The original local guardian policy is not weakened.

Not certified by this test run: the complete pre-existing Cairn test suite,
active native schedules, a recovered current 500-USDT checkpoint, current OKX
network access from every scheduled session, profitable CORE models, continuous
protection, or an accepted forward paper entry. Source publication is not
schedule activation. Account-changing reports require a non-force parent-bound
Git commit plus readback; this script deliberately does not contain credentials
or a GitHub mutation transport.
