# Workflows

## 1. Candidate research

```text
Evidence QUARANTINED
        │ owner admit
        ▼
INPUTS_FROZEN
        │ lease / bounded budget
        ▼
RUNNING
 ├─ failure / timeout / uncertain billing → BLOCKED
 ├─ owner cancel                       → CANCELLED
 └─ all blind first passes complete    → READY_FOR_REVIEW
                                            │
                         ┌──────────────────┼──────────────────┐
                         │                  │                  │
                       adopt              reject       cross-examine once
                         │                  │                  │
                      ACCEPTED           REJECTED      CROSS_EXAMINING
                                                               │
                                                       READY_FOR_REVIEW
```

`ACCEPTED`, `REJECTED`, and `CANCELLED` are terminal. New evidence or a changed view creates a new run / thesis revision; old history is not overwritten.

## 2. Evidence-to-valuation

```text
asset identity
  → source admission
  → metric definition
  → observations / revisions
  → numeric claim checks
  → explicit semantic review
  → value-capture map
  → category-specific valuation inputs
  → deterministic scenarios or UNPRICED
  → market-price comparison
  → frozen DecisionCard
```

A valid refusal is better than fake precision. `UNPRICED` and `ABSTAIN` are first-class outcomes.

## 3. Blind analysis

Single-model analysis is the baseline. When a challenger is used:

1. both analysts receive the same frozen evidence or separately preregistered retrieval scope;
2. neither sees the other's first-pass answer;
3. the controller validates both outputs;
4. only after both are sealed can one bounded cross-examination occur;
5. disputed factual premises should resolve through evidence, not majority vote.

Two models citing the same upstream source are not two independent confirmations.

## 4. OKX universe workflow

```text
public instruments + public tickers
        ↓
identity / state / freshness / unit checks
        ↓
held-position override + quote-currency partition
        ↓
cheap deterministic research-priority screen
        ↓
limited detail set
        ↓
1h history + book depth + derivatives context
        ↓
category / mechanism classification
        ↓
deep-research candidates
```

Default policy deliberately limits expensive detail work. The shortlist is not a trade signal.

### Existing holdings

A held position is never allowed to disappear merely because it fails a new-entry liquidity screen. Non-live, stale, incomplete, or illiquid held positions are escalated for review.

### Product families

- Spot: comparable quote-currency turnover may be used within a common quote currency.
- Swaps / futures: contract and base-volume semantics remain separate.
- Options: must be configured by explicit family; Greeks / option valuation are outside v0.5.

## 5. Slow Brain / Fast Brain

### Slow Brain

Deep protocol research, tokenomics, value capture, valuation, thesis creation, and major thesis review.

### Fast Brain

Deterministic event triage: price moves, security incidents, governance changes, supply events, review deadlines, data-health failures.

The Fast Brain's job is to decide whether the Slow Brain should wake up. It does **not** rewrite the thesis every time price changes.

## 6. Paper workflow

```text
explicit observational PaperAction
        ↓
sequence / idempotency / cash / quantity checks
        ↓
deterministic transition
        ↓
append receipt / audit
        ↓
complete marks
        ↓
NAV / comparison
```

The paper ledger is spot-only and fully funded. It refuses margin creation, short selling, and partial NAV when required marks are missing.

A paper action remains an observational decision; it is not transmitted to OKX.

## 7. Prospective model experiment

```text
preregister TrialSpec
   ↓
freeze baseline + candidate forecasts
   ↓
wait until resolution time
   ↓
resolve against admitted outcome evidence
   ↓
paired Brier / error / cost / latency comparison
   ↓
cluster-aware uncertainty
   ↓
human decision: retain baseline or approve research-only enhancement
```

Positive synthetic results cannot prove real augmentation. A model enhancement does not acquire capital permissions.

## 8. Incident workflow

For data or research incidents:

1. stop affected research runs;
2. identify the frozen input hash and affected records;
3. revoke or quarantine compromised evidence without deleting history;
4. generate a new run rather than modifying an accepted thesis in place;
5. record the failure category;
6. add a regression or fault-injection test;
7. only then resume.

For a future execution incident, the required path will be stricter: kill switch, stop new orders, reconcile exchange/account state, reserve ambiguous fills, and require human reauthorization. That execution system is not in v0.5.
