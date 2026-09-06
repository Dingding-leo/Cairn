# Contributing to Cairn

Cairn values correctness and falsifiability over feature count. A contribution is useful when it improves measured research quality, auditability, reproducibility, safety, cost, or net operator time.

## Before writing code

For significant work, open an issue describing:

- the problem;
- evidence that the problem matters;
- the smallest solution considered;
- new failure modes;
- migration / rollback requirements;
- how success will be measured.

Do not add an agent, framework, data vendor, or database solely because it is fashionable or “more sophisticated.”

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'

ruff check src tests
mypy src/cairn
pytest --cov=cairn --cov-branch
```

The default suite must not require live network calls or paid model credentials.

## Design rules

### Deterministic rules live in code

Do not duplicate hard portfolio, validation, or state-transition rules across prompts. Prompts may explain policy, but they are not the authority.

### Preserve history

Do not mutate old evidence, opinions, thesis revisions, or settled paper events to make a new analysis look cleaner. Add a new revision or corrective event.

### Point-in-time honesty

Never relabel reconstructed historical data as prospectively known. Tests involving historical dates must specify data availability semantics.

### Unknown is valid

Do not fabricate a valuation merely to fill a schema. `UNPRICED`, `ABSTAIN`, `INCOMPARABLE`, and explicit blockers are valid outcomes.

### No silent fallbacks

A requested provider or model that fails must fail visibly unless the caller explicitly configured a fallback and the fallback preserves the experiment's meaning.

### Capital authority is separate

Research code must not gain live trading authority as a side effect of an unrelated change. Private exchange APIs belong in a future separately reviewed execution package.

## Pull-request checklist

A PR should state:

- what changed and why;
- user-visible behavior;
- invariant or schema changes;
- migration impact;
- tests added;
- security implications;
- evaluation implications;
- cost / latency implications if a model or data call was added;
- rollback path for risky changes.

For generated schemas or artifacts, update the source of truth rather than editing generated output directly.

## Testing expectations

Add regression cases for failure paths, not only happy paths. Relevant examples include:

- stale / future data;
- unit mismatch;
- duplicate economic events;
- incomplete portfolio marks;
- insufficient order-book depth;
- revoked evidence;
- illegal workflow transitions;
- retry / timeout ambiguity;
- model-output schema failures;
- point-in-time leakage.

## Documentation

Architecture behavior must be documented at the level an independent reviewer needs to understand authority, data provenance, failure behavior, and recovery. Do not use documentation to imply a capability that is not implemented.

## Commit style

Prefer small, reviewable commits with imperative subjects, for example:

- `feat: add source methodology lineage`
- `fix: reject stale OKX quote snapshot`
- `test: cover duplicate paper action`
- `docs: explain reconstructed data boundary`

## Investment claims

Do not describe backtest, synthetic, or paper results as live alpha. Any performance claim must identify data period, benchmark, fees, slippage assumptions, sample construction, and whether results were prospective or reconstructed.
