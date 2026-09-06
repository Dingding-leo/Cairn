# Architecture

**Version:** v0.5.0rc1  
**Boundary:** research and observational paper systems only.

## 1. Architectural objective

Cairn is designed to preserve evidence and decision history before it tries to automate trading. The architecture therefore optimizes for:

1. correctness;
2. auditability;
3. reproducibility;
4. explicit authority;
5. failure containment;
6. low operational complexity;
7. testability;
8. measurable rather than assumed model value.

The system is intentionally a **modular monolith** for v0.5. A distributed architecture is not a quality signal by itself.

## 2. Logical bounded contexts

```text
                    TRUSTED CONTROLLER
                           │
       ┌───────────────────┼────────────────────┐
       │                   │                    │
  Evidence & Data       Research            Evaluation
       │                   │                    │
identity / metrics     blind workers      forecasts / trials
capture / supply       thesis / drift     paper comparison
       │                   │                    │
       └───────────────────┼────────────────────┘
                           │
                     SQLite state

Public OKX GET ──> quarantine ──> explicit research input

Separate future boundary:
TradeProposal → deterministic risk → ApprovedOrder → executor → OKX → reconciliation
```

### Research

Owns evidence-backed claims, decision cards, analyst opinions, disputes, thesis revisions, and prospective forecasts.

### Portfolio / paper

Owns observational cash and position accounting. It does not infer that a research recommendation has been authorized as a paper action.

### Execution

Not implemented. No private OKX client belongs inside the current research package.

## 3. Dependency direction

```text
cli
 ↓
application use cases
 ↓
models / evidence / valuation / universe / workflow / paper / evaluation
 ↓
storage
```

Network code is isolated in `okx.py`. Pure valuation, accounting, and workflow logic does not depend on an HTTP client.

## 4. Authority model

| Object / decision | Authority |
|---|---|
| Asset identity | owner + typed validation |
| Evidence admission / revocation | owner |
| Market arithmetic | deterministic code |
| Value-capture interpretation | evidence + explicit review |
| Numerical valuation | deterministic category model |
| Qualitative analysis | replaceable model worker |
| Thesis adoption | human owner |
| Paper action | explicit observational intent |
| Portfolio hard limits | future deterministic risk boundary |
| Live order transmission | absent |
| Wallet / withdrawal authority | absent |

A model is not an authority because it is more capable, more confident, or supported by another model.

## 5. Data modes and time semantics

Cairn distinguishes:

- `SYNTHETIC` — deterministic fixtures and demos;
- `PROSPECTIVE` — evidence the system actually possessed by the decision cutoff;
- `RECONSTRUCTED` — historical information collected later.

Reconstructed data may be useful for replay, but it cannot be relabelled as evidence the system possessed in the past. This distinction is critical because a modern model can also remember future events even when retrieval is frozen.

## 6. Evidence lineage

A consequential statement should be traceable to:

- asset identity;
- source URI;
- source / content hash;
- publication time;
- observation time;
- ingestion time;
- extraction or calculation method;
- metric definition and period;
- data mode;
- review status.

Source disagreement is surfaced as disagreement or incompatibility. Cairn does not silently take a median of incompatible accounting definitions.

## 7. Exact arithmetic

Financial comparisons use exact rational arithmetic where practical. Floating point is restricted to statistical estimates such as volatility or bootstrap intervals, where it does not authorize cash movements.

The code intentionally refuses:

- non-finite values;
- zero denominators where a ratio requires a nonzero base;
- negative spot quantities in the spot-only paper ledger;
- partial portfolio NAV when marks are missing;
- category valuation when economic rights are unsupported.

## 8. OKX adapter boundary

The public client has a deliberately narrow attack surface:

- approved HTTPS host allowlist;
- `/api/v5/` path restriction;
- GET only;
- no API key or signature support;
- no redirect following by design;
- response-size cap;
- quote-freshness checks;
- explicit `--ack-network` at the CLI.

Public instrument discovery is not equivalent to account eligibility. Regional and account permissions remain an external concern until a future authenticated boundary is independently designed.

## 9. Full-universe strategy

The system does not run deep research on every listed instrument. It uses a cost-aware funnel:

1. discover products;
2. normalize identity and units;
3. remove unusable new-entry candidates while keeping held positions visible;
4. rank by research priority;
5. fetch detailed market diagnostics for a bounded shortlist;
6. build category-specific research dossiers;
7. deep research only the most consequential candidates.

Spot and derivatives are not forced into one liquidity score because their volume semantics differ.

## 10. Model isolation

The intended worker contract is:

```text
Frozen WorkPacket -> Submission
```

The packet should contain only the evidence and deterministic derived results required for the assigned role. It should not contain:

- database credentials;
- exchange credentials;
- controller lease secrets;
- private environment variables;
- another worker's blind first-pass output.

Subprocess isolation alone is not an OS security boundary. Strong experiments should use a separate OS account, container, VM, or host.

## 11. State and recovery

SQLite remains the default because it provides a single transactional authority with low operational burden. The store uses:

- `BEGIN IMMEDIATE` for write transactions;
- immutable record identifiers;
- canonical JSON hashes;
- an append-only audit hash chain;
- online SQLite backup followed by verification.

Move to Postgres only when measured multi-writer or multi-host requirements justify it. Add DuckDB for analytical snapshots if it improves evaluation ergonomics; do not replace transactional state with it.

## 12. Evolution criteria

A new framework, model, data vendor, service, or database must answer:

- What measured bottleneck does it fix?
- What simpler alternative was rejected and why?
- What new failure modes appear?
- What is the rollback path?
- What regression / fault-injection tests exist?
- What is the incremental cash and maintenance cost?
- What decision-quality or net-time improvement justifies it?

Live execution requires a separate architecture decision and security review. It must not arrive as a feature flag inside this research application.
