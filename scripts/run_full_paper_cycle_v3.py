from __future__ import annotations

from cairn.exact import fraction_decimal
import run_full_paper_cycle_v2 as runner

runner.D = fraction_decimal

if __name__ == "__main__":
    raise SystemExit(runner.main())
