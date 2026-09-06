# Cairn

**Evidence-preserving crypto investment research on OKX.**  
`v0.5.0rc1` · research-only release candidate · 6 September 2026

> Cairn is not an autonomous trading bot and is not a promise of alpha. It is a research operating system designed to make crypto capital-allocation decisions more **traceable, reproducible, falsifiable, and risk-aware** before any live execution is permitted.

Cairn combines point-in-time evidence, typed research contracts, category-specific valuation, blind model review, deterministic paper accounting, forward evaluation, and OKX-wide market screening. The design deliberately keeps hard financial rules outside conversational model judgment.

**Current authority boundary:** public/read-only OKX market data, local research state, deterministic calculations, and observational paper accounting. **No private OKX API, signer, withdrawal credential, leverage, or live order transport exists in this repository.**

---

## Why Cairn exists

Most AI investment systems optimize for more agents, more generated text, or more trades. Cairn optimizes for a different objective:

> **Improve the expected quality of capital-allocation decisions while preserving evidence, uncertainty, reproducibility, and hard risk boundaries.**

The system therefore treats several common assumptions as hypotheses rather than truths:

- more agents do not automatically produce better analysis;
- model agreement is not independent confirmation;
- protocol revenue is not automatically token-holder value;
- a correct fundamental view can still be a bad trade if the price already discounts it;
- historical replay is not clean alpha evidence if the model can remember later events;
- a research recommendation is not a trade authorization.

Cairn was derived from an adversarial audit of [`xbtlin/ai-berkshire`](https://github.com/xbtlin/ai-berkshire). Reused concepts and MIT attribution are documented in [`UPSTREAM.md`](UPSTREAM.md) and [`LICENSES/`](LICENSES/).

---

## What is implemented

### 1. Evidence-to-valuation research pipeline

```text
Raw evidence / metrics
        ↓
Identity + time + methodology checks
        ↓
Numeric claims + explicit semantic review
        ↓
Value-capture graph
        ↓
Category-specific deterministic valuation
        ↓
Conditional reverse-valuation grid
        ↓
Frozen DecisionCard
        ↓
Blind research / optional bounded cross-examination
        ↓
Human adoption → immutable thesis revision
```

Important properties:

- Evidence records preserve source, publication/observation/ingestion time, method, content hash, and admission state.
- `PROSPECTIVE`, `RECONSTRUCTED`, and `SYNTHETIC` data are kept distinct.
- Data-source disagreement is surfaced as disagreement; it is not silently averaged.
- Numeric equality and semantic support are separate checks.
- Missing economic rights can produce `UNPRICED` / `ABSTAIN` instead of a fabricated DCF.
- Model output cannot override deterministic valuation records in the v0.5 research path.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/VALUATION.md`](docs/VALUATION.md), and [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md).

### 2. OKX full-universe research funnel

OKX is the selected venue for market discovery and market-structure analysis. The scanner can ingest the complete returned public universe for configured instrument classes, then allocate expensive analysis only to a bounded candidate set.

```text
OKX public instruments + tickers
            ↓
Universe registry + identity/unit validation
            ↓
Quote-currency / status / staleness / liquidity filters
            ↓
Existing holdings first
            ↓
Bounded 1H history + order-book diagnostics
            ↓
Research-priority ranking
            ↓
Deep-research drafts → Cairn evidence/valuation workflow
```

Supported research scope:

| OKX product | v0.5 treatment |
|---|---|
| Spot | Universe screening, history, order-book diagnostics, paper parameter preview |
| Perpetual swaps | Observational context only; funding/OI preserved separately |
| Futures | Observational context only |
| Options | Optional configured-family discovery; no Greeks/pricing engine yet |
| Private account state | Not connected; holdings can only be manually declared |
| Live execution | Not implemented |

The ranking is **research priority**, not predicted return or a buy list. Existing holdings remain visible even when they fail new-entry liquidity criteria.

See [`docs/OKX.md`](docs/OKX.md) and [`docs/UNIVERSE-ANALYSIS.md`](docs/UNIVERSE-ANALYSIS.md).

### 3. Blind model research with bounded debate

Skills, agents, and workflows are separate objects:

- **CapabilitySpec** — what a capability may consume, produce, and check;
- **AgentSpec** — role, provider/model configuration, thinking level, and allowed capabilities;
- **WorkflowSpec** — state transitions, attempt limits, budgets, and cross-examination limits.

A second model does not see the first model's initial answer. Cross-examination is a separate, bounded state, and no majority vote is allowed to create portfolio authority.

Real Claude Code / Codex cross-model superiority remains **unproven** until prospective experiments satisfy the evaluation gates in [`docs/EVALUATION.md`](docs/EVALUATION.md).

### 4. Deterministic paper ledger and evaluation lab

Cairn includes observational, spot-only paper accounting for experiments:

- cash and positions;
- fees and adverse slippage assumptions;
- distributions and migrations;
- write-downs;
- event hash chain and replay;
- NAV snapshots and comparison;
- preregistered paired model trials;
- Brier/error evaluation and promotion gates.

The paper ledger is intentionally not a simulated matching engine. Queue position, partial fills, full market impact, tax, and derivatives collateral are outside the current model.

---

## Architecture

Cairn is a **modular monolith**, not a microservice estate.

```text
CLI / handoff files / optional isolated model bridge
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
 Evidence + Lab     Research Engine    Trials / Paper
 metrics / claims   frozen dossier     outcomes / ledger
 capture / value    blind opinions     promotion gates
       └─────────────────┼─────────────────┘
                  typed contracts
                         │
        SQLite transactional state + audit log

Separate read-only boundary: OKX public GET → quarantine
Absent boundary: private exchange API / signer / live orders
```

Why this architecture:

- one trusted writer is easier to audit and recover;
- SQLite transactions are sufficient for the current scale;
- model workers remain externally replaceable;
- deterministic policy lives in code, not duplicated prompts;
- LangGraph/Temporal/Postgres remain future options only if measured operational requirements justify them.

See the ADRs under [`docs/adr/`](docs/adr/).

---

## Quick start

### Requirements

- Python **3.11–3.13**
- a local environment capable of installing the pinned development/runtime requirements

```bash
git clone https://github.com/Dingding-leo/Cairn.git
cd Cairn
bash scripts/bootstrap.sh
source .venv/bin/activate

cairn doctor
```

### Completely offline demos

```bash
cairn lab-demo --out ./local-lab-demo
cairn okx-demo --out ./local-okx-demo
```

These demos use explicitly synthetic data. They do **not** call OKX, Claude, Codex, or any trading endpoint and do not spend model/API money.

### Explicit read-only OKX scan

```bash
cairn okx-scan \
  --policy config/okx.policy.json \
  --ack-network \
  --out ./okx-scan-001
```

Network use is opt-in. The public scanner uses allow-listed OKX GET paths, does not accept arbitrary URLs, does not inherit proxy settings, does not retry/fallback silently, and does not read private account credentials.

The release package used to create this repository could not complete a real OKX public-network probe from its build environment, so **real endpoint availability/region behavior remains an external conformance task**.

### Reproduce a frozen scan

```bash
cairn okx-analyze ./okx-scan-001/snapshot.json --out ./replayed-analysis
cairn okx-diff ./okx-scan-001/snapshot.json ./okx-scan-002/snapshot.json
```

Replaying a snapshot does not turn reconstructed historical data into prospective evidence.

---

## Quality status

The packaged `0.5.0rc1` candidate was locally validated before publication with:

- **305 tests passed** with 0 failures/errors/skips;
- **98.00%** combined statement/branch coverage against a 95% floor;
- **53/53** active generated schemas synchronized;
- wheel build and installed CLI smoke checks;
- offline v0.4 compatibility checks;
- synthetic 1,000-product OKX scale-shape test;
- desktop/mobile HTML smoke tests;
- final release integrity verification.

These results are engineering evidence, **not** security certification, exchange conformance, model-quality proof, or investment-performance evidence. The exact release notes and caveats are in [`RELEASE-STATUS.md`](RELEASE-STATUS.md) and [`docs/QUALITY.md`](docs/QUALITY.md).

Run the local verification suite with:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python scripts/verify.py
```

CI is configured for Python 3.11, 3.12, and 3.13 under [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Safety model

The current repository intentionally has **no capital authority**.

It does not contain:

- private OKX trading credentials;
- withdrawal-enabled API keys;
- wallet/private-key signing;
- live order submission;
- leveraged execution;
- a hidden `--live` flag;
- an LLM override for deterministic hard rejection.

A future execution system, if ever authorized, must be a separate boundary:

```text
LLM research
    ↓
TradeProposal
    ↓
Human / Investment Committee authorization
    ↓
Fresh deterministic Risk Engine
    ↓
ApprovedOrder
    ↓
Isolated Execution Service
    ↓
OKX
    ↓
Reconciliation + audit ledger
```

Live trading remains blocked until the staged evidence gates are passed. See [`audit/docs/07-risk-security-execution.md`](audit/docs/07-risk-security-execution.md) and [`SECURITY.md`](SECURITY.md).

---

## Evaluation philosophy

Cairn does not treat a better-looking report as proof of a better investment system.

The project evaluates candidate enhancements against simpler baselines on:

- material factual error rate;
- citation/claim support;
- uncertainty calibration and Brier score;
- missed risks;
- answer coverage;
- human verification time;
- cost and latency;
- paper-portfolio outcomes and transaction assumptions.

Historical replay is treated cautiously because contemporary foundation models can remember later events even when retrieval is point-in-time filtered. Prospective, frozen predictions therefore carry more evidentiary weight.

All deployment Gates A–E remain **UNPASSED** in `0.5.0rc1`. See [`docs/EVALUATION.md`](docs/EVALUATION.md).

---

## Repository map

```text
src/cairn/              application, contracts, storage, research, OKX and paper logic
tests/                  regression, integration, failure-path and CLI tests
schemas/                generated JSON Schemas for typed public contracts
config/                 versioned capabilities, workflows and OKX policy
docs/                   architecture, valuation, workflows, OKX, evaluation and ADRs
audit/                  original feasibility/red-team audit and experiment designs
verification/           retained local verification evidence from the packaged candidate
examples/               synthetic input/output examples and offline demos
LICENSES/               upstream attribution
```

Generated build outputs and local databases are intentionally excluded by `.gitignore`.

---

## Project status and roadmap

`v0.5.0rc1` should be read as **research laboratory software**, not a finished fund.

Highest-priority next work:

1. real OKX public endpoint/region conformance in an authorized network environment;
2. authenticated Claude/Codex worker conformance and genuinely blind quality experiments;
3. broader real evidence ingestion and token-identity/value-capture validation;
4. prospective research and paper-portfolio collection long enough to evaluate calibration and net benefit;
5. independent code/security review;
6. only then consider a separately designed shadow-execution boundary.

The detailed dependency-ordered roadmap is in [`BACKLOG.md`](BACKLOG.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before proposing changes. In particular:

- do not weaken fail-closed behavior to make a demo pass;
- do not add a model/framework without a falsifiable benefit hypothesis;
- do not introduce live trading in a research pull request;
- every consequential financial calculation needs a reproducible typed input path;
- preserve point-in-time semantics and explicit UNKNOWN/UNPRICED states.

---

## License and attribution

Cairn is released under the repository's [`LICENSE`](LICENSE). Portions of the methodology were adapted from **AI Berkshire** under the MIT License; the required upstream notice is preserved in [`LICENSES/ai-berkshire-MIT.txt`](LICENSES/ai-berkshire-MIT.txt).

This software is for research and education. It is not financial advice. Past or simulated performance does not guarantee future results.
