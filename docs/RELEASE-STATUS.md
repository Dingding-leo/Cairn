# Release Status — v0.5.0rc1

**Date:** 2026-09-06  
**Status:** research-only release candidate

## Repository publication

This GitHub publication contains the canonical, reviewable core of the Cairn v0.5 OKX research architecture: typed contracts, evidence / valuation logic, public OKX boundary, universe analysis, workflow state machine, paper accounting, prospective evaluation, SQLite audit storage, tests, CI, and project documentation.

The larger local development package used during the engineering pass reported:

- 305 passing tests;
- 98.00% combined coverage;
- 53 synchronized schemas;
- 397 manifest checks;
- source-outside-package installation smoke;
- synthetic migration compatibility checks.

Those figures refer to that packaged development artifact and are **not automatically re-used as GitHub CI results**. The repository has its own CI and a publication-core coverage threshold that should be raised as the remaining generated-contract and extended-fixture suite is ported.

## External validations still outstanding

The following are not certified by publication:

- authenticated real Claude / Codex model runs;
- claimed thinking-effort behavior on the user's accounts;
- long-running public OKX connectivity in the deployment region;
- private OKX account eligibility or balances;
- current real token-contract / value-capture truth for every researched asset;
- long-horizon prospective alpha;
- shadow execution;
- live execution;
- independent security audit.

## Capital status

- live orders: **0**
- exchange trading credentials in repository: **none**
- withdrawal authority: **none**
- leverage engine: **none**
- capital permissions: **NONE**
- Gates A–E: **not passed by software publication alone**

## Product boundary

The public OKX adapter is a research data boundary. The paper ledger is observational. Neither is a trading service.

The next release should prioritize real-source conformance and prospective decision-quality measurement before any execution capability.
