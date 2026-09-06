# Evaluation and Deployment Gates

Engineering correctness and investment usefulness are separate claims. A release may have excellent unit-test coverage while still having no demonstrated investment edge.

## Gate A — research quality

Before treating Cairn as a reliable research assistant, measure on real dossiers:

- material factual-error rate;
- fabricated-citation count;
- citation entailment;
- consequential-input lineage coverage;
- reproducibility;
- data discrepancy rate;
- human verification time;
- cash cost per dossier.

A system that says `UNKNOWN` for everything can appear accurate, so coverage / abstention must be reported beside error rate.

## Gate B — historical replay

Historical testing must preserve what was knowable at time `t`:

- point-in-time supply;
- announcement time for unlocks;
- historical liquidity;
- delisted and failed assets;
- exploits and depegs only after they became knowable;
- fees, slippage, funding, and market impact.

A modern LLM may remember future events even when retrieval is frozen. Historical replay is therefore not sufficient evidence of unbiased LLM forecasting alpha.

## Gate C — forward paper portfolio

Track a frozen forward process against simple risk-matched baselines:

- total and benchmark-relative return;
- max drawdown;
- turnover;
- hit rate and payoff ratio;
- expected versus realized return;
- fees and estimated trading costs;
- model / data / human intervention attribution.

Do not change the scoring rule after seeing outcomes.

## Gate D — shadow execution

Generate candidate orders but do not transmit them. Compare:

- proposed versus actually executable price;
- quote age;
- spread and order-book depth;
- partial-fill behavior;
- stale-order frequency;
- latency;
- duplicate-order and reconciliation fault injection.

The current `market_structure.py` is only a displayed-depth diagnostic. It is not Gate D certification.

## Gate E — tiny-cap live pilot

Gate E requires a separate execution architecture and human authorization. It should begin, if ever approved, with a tiny fully-funded spot allocation and explicit per-order approval.

Live credentials must be least privilege and unable to withdraw. LLM workers must never receive them.

## Multi-model experiment

The default baseline is one strong model. Candidate enhancements should be compared using preregistered paired cases.

Recommended primary metrics:

- Brier score for probabilistic outcomes;
- material factual errors;
- missed critical risks;
- answer coverage;
- human verification time;
- cash cost;
- latency.

A candidate should not be promoted merely because it creates more disagreement or longer reports.

A useful candidate threshold can require, for example:

- at least 0.02 absolute Brier-score improvement, **or** at least 20% relative reduction in material error rate;
- no increase in critical errors;
- no material coverage deterioration;
- no deterioration in the other preregistered primary metric;
- cost no more than 2× the baseline;
- median latency no more than 3× the baseline;
- a paired / cluster-aware interval that excludes no improvement.

These are research criteria, not statements that current Cairn has met them.

## Error taxonomy

Postmortems should separate:

- `FACT_ERROR`
- `FORECAST_ERROR`
- `PRICING_ERROR`
- `SIZING_ERROR`
- `COST_ERROR`
- `EXECUTION_ERROR`
- `INSUFFICIENT_DATA`

A profitable trade can be based on a factual mistake; an unprofitable trade can follow a sound thesis. Outcome alone does not rewrite history.
