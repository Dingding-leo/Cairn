# Changelog

All notable Cairn changes are documented here. Cairn follows semantic-versioning conventions while `0.x` releases remain research candidates.

## [0.5.0rc1] — 2026-09-06

### Added

- OKX-first public instrument discovery boundary.
- Full-universe, cost-aware spot screening with held-position priority.
- Strict separation of spot versus derivatives volume semantics.
- 1-hour return, volatility, drawdown, and aligned-correlation diagnostics.
- Conservative displayed order-book cost estimation.
- Portfolio exposure analysis that refuses partial NAV when marks are incomplete.
- Repository-grade README, architecture, workflow, security, evaluation, and contribution documentation.
- CI matrix for Python 3.11–3.13 with Ruff, mypy, tests, coverage, build, and CLI smoke.

### Preserved from v0.4 design

- Evidence / metric / supply / unlock lineage.
- Numeric versus semantic claim validation separation.
- Value-capture modelling.
- Category-specific scenario valuation and explicit `UNPRICED` states.
- Frozen DecisionCard concept.
- Blind first-pass model comparison and bounded cross-examination.
- Fully-funded observational spot paper ledger.
- Prospective model-quality evaluation.
- No live execution authority.

### Safety

- Public OKX client remains GET-only and unauthenticated.
- No wallet/private-key integration.
- No withdrawal or trade-key integration.
- No leverage engine.
- No hidden live-trading flag.
- Research, paper, and future execution authorities remain separate.

### Validation status

The development release that preceded this repository publication reported 305 passing local tests, 98.00% combined coverage, 53 synchronized schemas, and 397 manifest checks in its documented Linux/Python 3.13.5 environment. Those results are release-engineering evidence, not investment-performance evidence. GitHub CI is the canonical repository validation after publication.

## [0.4.0rc1] — 2026-09-06

- Added evidence-to-valuation lab.
- Added explicit claim verification and value-capture concepts.
- Added deterministic scenario valuation and reverse-price condition grids.
- Added DecisionCard / paper ledger / prospective experiment concepts.
- Retained all deployment gates as unpassed.

## [0.1.0] — 2026-09-05

- Established modular-monolith research architecture.
- Added typed research contracts, SQLite state, auditability, blind first-pass barrier, bounded cross-examination, immutable thesis revisions, event triage, and offline demonstration workflow.
- Deliberately omitted live capital execution.
