# OKX Universe Analysis

Cairn uses OKX as the selected venue for market discovery and market-structure research. The goal of the universe layer is **coverage with bounded cost**, not a pseudo-precise ranking of expected returns.

## Scope

Default public research surfaces:

- `SPOT`
- `SWAP`
- `FUTURES`
- explicitly configured `OPTION` families

Out of scope in v0.5: private account endpoints, margin borrowing, Earn products, DEX routing, live order placement, withdrawals, and unrestricted options analytics.

## Why a funnel is required

Deep LLM research for every listed instrument is expensive, slow, and likely to magnify noise. Cairn therefore separates cheap deterministic triage from expensive fundamental research.

### Tier 0 — identity and availability

For every returned instrument preserve:

- `instId`;
- product family;
- live state;
- base / quote / settlement currency;
- tick / lot / minimum size;
- derivative contract value and expiry when relevant.

Never infer that similarly named symbols across chains are economically identical.

### Tier 1 — broad deterministic screen

For spot pairs within a common quote currency, the default triage considers:

- instrument state;
- quote freshness;
- 24-hour quote-currency turnover;
- bid/ask completeness;
- spread;
- whether the instrument represents an existing holding.

Thresholds are policy parameters. They are not learned alpha signals.

### Tier 2 — bounded detail

For a limited shortlist, fetch:

- completed 1-hour candles;
- order-book depth;
- derivatives context where relevant;
- funding / open interest in a future provider expansion.

The default detail budget is deliberately small. More coverage should be justified by missed-opportunity evidence, not by a desire to make the system look comprehensive.

### Tier 3 — mechanism research

Only after market-data quality checks does Cairn spend research budget on token identity, protocol economics, supply, value capture, governance, security, catalysts, and valuation.

## Unit discipline

OKX product families expose different volume semantics. Cairn does not rank spot quote turnover and derivatives contract volume as though they were one field.

Comparable rankings should use a documented normalization method, common currency, common observation period, and instrument-specific contract metadata.

## Holdings override

Existing positions receive review priority even when they fail new-entry filters. A position with poor liquidity, stale quotes, or a non-live instrument is **more** important to surface, not less.

## Market diagnostics

The built-in 1-hour history diagnostics can estimate:

- 24-hour return when enough complete bars exist;
- 7-day return when enough complete bars exist;
- sample maximum drawdown;
- annualized historical volatility;
- aligned pairwise correlation.

A 200-bar sample is only a short market diagnostic. It is not a long-horizon risk model or strategy backtest.

## Book-cost estimate

Displayed depth can be conservatively haircutted and walked to estimate a potential adverse average price. The estimate intentionally omits:

- queue position;
- hidden liquidity;
- cancellation probability;
- latency;
- self-impact;
- cross-venue liquidity;
- partial-fill timing.

Those omissions are why shadow execution must be a later gate.

## Research-priority ranking is not investment ranking

A high score means “worth spending research budget on sooner,” often because the instrument is liquid and easy to evaluate or already held. It does **not** mean:

- highest expected return;
- safest token;
- strongest fundamental value;
- buy now;
- acceptable position size.

Those questions belong to later evidence, valuation, portfolio, and risk stages.
