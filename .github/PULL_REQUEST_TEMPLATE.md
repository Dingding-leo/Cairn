## What changed

Describe the behavior change and the problem it solves.

## Evidence

- [ ] Added/updated deterministic tests
- [ ] Added failure-path or leakage tests where relevant
- [ ] Updated docs for authority/data semantics
- [ ] No unsupported performance claims

## Architecture

- Invariants changed:
- Schema/migration impact:
- Security implications:
- Model/data cost implications:
- Rollback path:

## Safety boundary

- [ ] Does not silently introduce private exchange access
- [ ] Does not grant LLMs capital authority
- [ ] Does not weaken point-in-time or evidence-lineage checks
- [ ] Does not convert `UNKNOWN`/`UNPRICED` into fabricated certainty

## Validation

```text
ruff:
mypy:
pytest:
coverage:
```
