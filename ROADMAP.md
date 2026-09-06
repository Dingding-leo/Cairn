# Cairn Roadmap

The roadmap is ordered by evidence and dependency, not by feature excitement.

## v0.5 — OKX research workbench

Status: **release candidate**

- [x] Evidence-first research architecture
- [x] OKX public instrument and ticker boundary
- [x] Cost-aware spot-universe screening
- [x] 1-hour market diagnostics
- [x] Displayed order-book cost estimation
- [x] Category-specific scenario valuation
- [x] Explicit `UNPRICED` / `ABSTAIN`
- [x] Bounded blind-analysis workflow
- [x] Transactional local state and audit chain
- [x] Fully-funded spot paper ledger
- [x] Prospective model-evaluation utilities
- [x] CI for Python 3.11–3.13

## P0 — prove research quality

- [ ] Run real Claude/Codex conformance tests against explicit model IDs and effort settings
- [ ] Build a sealed evaluation set for factuality, source entailment, and critical-risk detection
- [ ] Add real protocol/governance source adapters with source methodology metadata
- [ ] Implement authoritative asset/contract registry with native/wrapped/bridged identity rules
- [ ] Add current supply/unlock adapters with revision history
- [ ] Add deterministic data-health dashboard and stale-source alerts
- [ ] Run ≥40 real dossiers / ≥500 consequential claims through Gate A scoring
- [ ] Measure human verification time and actual model/data cost

## P1 — prove decision usefulness

- [ ] Expand point-in-time dataset to failed, delisted, exploited, and depegged assets
- [ ] Build walk-forward research replay with explicit model-memory contamination limitations
- [ ] Pre-register two narrow crypto hypotheses before observing outcomes
- [ ] Maintain a forward paper portfolio for at least 180 days
- [ ] Compare against simple risk-matched baselines
- [ ] Add distribution, migration, write-down, and corporate-action equivalent handling for paper accounting
- [ ] Add longer-horizon market/liquidity datasets rather than relying on ~200 hourly bars
- [ ] Attribute errors to facts, forecasts, pricing, sizing, costs, or data insufficiency

## P2 — prove market-operational realism

- [ ] Build shadow order proposal schema
- [ ] Model partial fills, queue uncertainty, stale orders, and rate limits
- [ ] Add expected-versus-observed slippage evaluation
- [ ] Build deterministic portfolio risk engine as a separate authority boundary
- [ ] Add exchange/account reconciliation model without live trading
- [ ] Run fault injection for duplicate orders, outages, stale data, and corrupted local state

## P3 — only after Gates A–D

A separate security and architecture review may consider a tiny-cap live spot executor. Requirements include:

- least-privilege trade-only credentials;
- no withdrawal authority;
- explicit subaccount separation;
- hard deterministic risk rejection;
- idempotent client order IDs;
- reconciliation;
- kill switch;
- human authorization;
- tiny capital cap.

This is not automatically part of Cairn merely because previous phases succeed.

## Explicit non-goals

Until evidence justifies otherwise, Cairn will not prioritize:

- permanent ten-agent committees;
- unbounded debates;
- universal token DCFs;
- autonomous leverage;
- self-modifying live strategies;
- Kubernetes / distributed workflow infrastructure for a single-user research workload;
- maximizing trade frequency.
